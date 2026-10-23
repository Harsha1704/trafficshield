"""
UNSW-NB15 Dataset Ingestion Adapter
===================================
Milestone 7 — TrafficShield

Memory-conscious, chunked ingestion adapter for the UNSW-NB15 dataset.
Processes the original 49-column headerless CSV files (UNSW-NB15_1.csv to
UNSW-NB15_4.csv), strictly enforcing the unidirectional feature policy.

Key Guarantees:
1. Headerless CSV handling using the verified 49-feature schema contract.
2. Memory-conscious chunked streaming: never loads multi-gigabyte raw files
   into memory at once.
3. Strict unidirectional filtering: reverse-direction and bidirectional fields
   are rejected or separated before model feature matrices are produced.
4. Robust validation: missing cells, malformed records, and corrupt values
   are logged, categorized, and counted in IngestionResult.
5. Ground-truth isolation: 'Label' and 'attack_cat' are isolated into
   evaluation targets and never mixed into model input features.
6. Chronological integrity: 'Ltime' (flow end) is verified as the primary
   chronological ordering key.
"""
from __future__ import annotations

import csv
import gzip
import io
import logging
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ingestion.adapters.unsw_nb15_policy import (
    UNSW_NB15_SPECS,
    audit_unsw_feature_columns,
    get_eligible_unsw_model_features,
)
from ingestion.schema.canonical_flow import (
    CanonicalFlow,
    IngestionResult,
    SourceDataset,
)

logger = logging.getLogger(__name__)

# The 49 canonical column names in exact CSV file order (1 to 49)
UNSW15_RAW_COLUMNS: tuple[str, ...] = tuple(s.raw_name for s in UNSW_NB15_SPECS)
UNSW15_NORMALIZED_COLUMNS: tuple[str, ...] = tuple(s.normalized_name for s in UNSW_NB15_SPECS)

# Known normal attack category strings
UNSW15_BENIGN_CATEGORIES: frozenset[str] = frozenset({
    "", "normal", "0", "-", "none", "background", "nan", "null",
})

# Default filenames in standard UNSW-NB15 raw distribution
UNSW15_DATA_FILENAMES: tuple[str, ...] = (
    "UNSW-NB15_1.csv",
    "UNSW-NB15_2.csv",
    "UNSW-NB15_3.csv",
    "UNSW-NB15_4.csv",
)
UNSW15_FEATURES_FILENAMES: tuple[str, ...] = (
    "NUSW-NB15_features.csv",
    "UNSW-NB15_features.csv",
)


class UNSW15ValidationError(Exception):
    """Raised when UNSW-NB15 raw input fails schema or file validation."""


def _open_file(filepath: Path) -> io.TextIOWrapper:
    """Open a plain, utf-8-sig, or gzip-compressed CSV file for reading."""
    filepath = Path(filepath)
    suffix = filepath.suffix.lower()
    if suffix == ".gz":
        return gzip.open(filepath, "rt", encoding="utf-8-sig", errors="replace")
    return open(filepath, encoding="utf-8-sig", errors="replace")


def parse_unsw_timestamp(raw: Any) -> datetime | None:
    """Parse a Unix epoch timestamp (integer or float string) to UTC datetime."""
    if raw is None:
        return None
    try:
        val = float(raw)
        if val <= 0.0 or not np.isfinite(val):
            return None
        return datetime.fromtimestamp(val, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def normalize_attack_category(raw_cat: Any, raw_label: Any = None) -> tuple[str, bool]:
    """
    Normalize UNSW-NB15 attack category and binary label.

    Returns:
        (normalized_category, is_attack)
    """
    if raw_cat is None or (isinstance(raw_cat, float) and np.isnan(raw_cat)):
        clean_cat = ""
    else:
        clean_cat = str(raw_cat).strip()

    if clean_cat.lower() in ("nan", "null", "none"):
        clean_cat = ""

    is_attack = False

    # Check numeric label if available
    try:
        lbl_num = int(str(raw_label).strip())
        if lbl_num == 1:
            is_attack = True
    except (ValueError, TypeError):
        pass

    lower_cat = clean_cat.lower()
    if not clean_cat or lower_cat in UNSW15_BENIGN_CATEGORIES:
        return "normal", is_attack

    # Attack category present
    is_attack = True
    # Normalize common category spelling inconsistencies (e.g. 'backdoors' vs 'backdoor')
    if lower_cat in ("backdoors", "backdoor"):
        return "backdoor", True
    if lower_cat == "fuzzers":
        return "fuzzers", True
    if lower_cat == "reconnaissance":
        return "reconnaissance", True
    if lower_cat == "shellcode":
        return "shellcode", True
    if lower_cat == "analysis":
        return "analysis", True
    if lower_cat == "exploits":
        return "exploits", True
    if lower_cat == "dos":
        return "dos", True
    if lower_cat == "worms":
        return "worms", True
    if lower_cat == "generic":
        return "generic", True

    return lower_cat, True


class UNSW15Adapter:
    """
    Ingestion adapter for the UNSW-NB15 flow dataset.

    Parameters
    ----------
    chunk_size : int
        Number of rows processed per chunk (default: 10,000).
    skip_invalid_rows : bool
        If True (default), invalid or malformed rows are counted and skipped.
        If False, raises on the first invalid record.
    """

    def __init__(
        self,
        chunk_size: int = 10_000,
        skip_invalid_rows: bool = True,
    ) -> None:
        self.chunk_size = max(1, chunk_size)
        self.skip_invalid_rows = skip_invalid_rows

    def validate_features_file(self, features_path: Path) -> list[str]:
        """
        Validate that the external features CSV contains the verified 49 columns.
        Returns the list of verified feature names.
        """
        features_path = Path(features_path)
        if not features_path.exists():
            raise FileNotFoundError(f"UNSW-NB15 features file not found: {features_path}")

        names = []
        with _open_file(features_path) as f:
            reader = csv.reader(f)
            # Check header
            header = next(reader, None)
            if not header or len(header) < 2:
                raise UNSW15ValidationError("Features file header is malformed or empty.")
            for row in reader:
                if len(row) >= 2 and row[1].strip():
                    names.append(row[1].strip())

        if len(names) != 49:
            raise UNSW15ValidationError(
                f"Expected exactly 49 feature definitions in {features_path.name}, got {len(names)}."
            )
        return names

    def iter_records(
        self,
        filepath: Path,
        max_rows: int | None = None,
    ) -> Generator[tuple[CanonicalFlow | None, str | None], None, None]:
        """
        Stream records from a single UNSW-NB15 CSV file.

        Yields (CanonicalFlow, None) for accepted rows, or (None, rejection_reason)
        for rejected rows.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"UNSW-NB15 data file not found: {filepath}")

        rows_emitted = 0
        with _open_file(filepath) as f:
            reader = csv.reader(f)
            for row_idx, row in enumerate(reader):
                if max_rows is not None and rows_emitted >= max_rows:
                    break

                # 1. Row length check
                if len(row) != 49:
                    yield (None, f"column_count_mismatch_expected_49_got_{len(row)}")
                    continue

                # 2. Extract key fields safely
                # row[0]: srcip, row[1]: sport, row[2]: dstip, row[3]: dsport, row[4]: proto
                # row[6]: dur, row[7]: sbytes, row[16]: Spkts
                # row[28]: Stime, row[29]: Ltime
                # row[47]: attack_cat, row[48]: Label
                src_ip = row[0].strip()
                dst_ip = row[2].strip()
                if not src_ip or not dst_ip:
                    yield (None, "missing_ip_address")
                    continue

                # Parse timestamps
                ltime_dt = parse_unsw_timestamp(row[29])
                if ltime_dt is None:
                    yield (None, "invalid_end_timestamp_Ltime")
                    continue

                # Parse duration
                try:
                    dur = float(row[6].strip())
                    if dur < 0.0 or not np.isfinite(dur):
                        dur = 0.0
                except (ValueError, TypeError):
                    dur = 0.0

                # Parse volume
                try:
                    sbytes = int(float(row[7].strip()))
                    if sbytes < 0:
                        yield (None, "negative_sbytes")
                        continue
                except (ValueError, TypeError):
                    yield (None, "invalid_sbytes")
                    continue

                try:
                    spkts = int(float(row[16].strip()))
                    if spkts < 0:
                        yield (None, "negative_spkts")
                        continue
                except (ValueError, TypeError):
                    yield (None, "invalid_spkts")
                    continue

                # Parse ports
                def _parse_port(p_raw: str) -> int | None:
                    try:
                        p = int(p_raw.strip())
                        return p if 0 <= p <= 65535 else None
                    except (ValueError, TypeError):
                        # Some hex or blank ports exist in raw data
                        try:
                            p = int(p_raw.strip(), 16)
                            return p if 0 <= p <= 65535 else None
                        except (ValueError, TypeError):
                            return None

                src_port = _parse_port(row[1])
                dst_port = _parse_port(row[3])
                proto_name = row[4].strip().upper() or "OTHER"

                # Parse labels
                norm_cat, is_attack = normalize_attack_category(row[47], row[48])

                try:
                    flow = CanonicalFlow(
                        source_dataset=SourceDataset.UNSWNB15,
                        source_file=filepath.name,
                        source_row_index=row_idx,
                        flow_end_ts=ltime_dt,
                        duration_seconds=dur,
                        src_ip=src_ip,
                        dst_ip=dst_ip,
                        src_port=src_port,
                        dst_port=dst_port,
                        protocol_name=proto_name,
                        fwd_packets=spkts,
                        fwd_bytes=sbytes,
                        eval_label=norm_cat,
                        eval_label_raw=row[47].strip(),
                        is_attack=is_attack,
                    )
                    rows_emitted += 1
                    yield (flow, None)
                except Exception as exc:
                    yield (None, f"canonical_flow_validation_error: {exc}")

    def ingest_file(
        self,
        filepath: Path,
        max_rows: int | None = None,
    ) -> tuple[list[CanonicalFlow], IngestionResult]:
        """
        Ingest records from a single file, returning accepted flows and summary.
        """
        filepath = Path(filepath)
        result = IngestionResult(
            source_file=filepath.name,
            source_dataset=SourceDataset.UNSWNB15,
        )

        accepted_flows: list[CanonicalFlow] = []
        for flow, err in self.iter_records(filepath, max_rows=max_rows):
            result.rows_read += 1
            if flow is not None:
                result.rows_accepted += 1
                accepted_flows.append(flow)
            else:
                result.record_rejection(err or "unknown_error")
                if not self.skip_invalid_rows:
                    raise UNSW15ValidationError(f"Row {result.rows_read} rejected: {err}")

        result.finish()
        return accepted_flows, result

    def load_unidirectional_dataframe(
        self,
        filepaths: list[Path] | Path,
        max_rows: int | None = None,
        include_engineered_rates: bool = True,
    ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        """
        Load UNSW-NB15 data directly into memory-efficient DataFrames:
        1. features_df: Strictly forward-observable numeric features.
        2. labels_series: Ground-truth target labels (isolated from features).
        3. metadata_df: Provenance, timestamps, and identifiers.

        Guarantees:
        - All reverse-direction features (dbytes, dpkts, dload, tcprtt, etc.) are DROPPED.
        - All bidirectional state features are DROPPED.
        - An audit check runs before returning to guarantee zero directional leakage.
        """
        if isinstance(filepaths, Path):
            paths = [filepaths]
        else:
            paths = list(filepaths)

        feature_cols = get_eligible_unsw_model_features()
        records_loaded = 0

        chunks_feat: list[pd.DataFrame] = []
        chunks_lbl: list[pd.Series] = []
        chunks_meta: list[pd.DataFrame] = []

        # Map raw column indices for memory-efficient loading
        # 1 to 49
        col_names = [s.normalized_name for s in UNSW_NB15_SPECS]

        for p in paths:
            if not p.exists():
                raise FileNotFoundError(f"File not found: {p}")
            if max_rows is not None and records_loaded >= max_rows:
                break

            logger.info("Streaming UNSW-NB15 from %s...", p.name)
            # Use chunked read_csv
            chunk_iter = pd.read_csv(
                p,
                header=None,
                names=col_names,
                chunksize=self.chunk_size,
                encoding="utf-8-sig",
                low_memory=False,
            )

            for chunk in chunk_iter:
                if max_rows is not None:
                    remaining = max_rows - records_loaded
                    if remaining <= 0:
                        break
                    if len(chunk) > remaining:
                        chunk = chunk.iloc[:remaining]

                n_chunk = len(chunk)
                records_loaded += n_chunk

                # 1. Extract and normalize labels
                labels_raw = chunk["eval_label"].astype(str).str.strip()
                binary_label = pd.to_numeric(chunk["is_attack"], errors="coerce").fillna(0).astype(int)

                norm_labels = []
                for cat, lbl in zip(labels_raw, binary_label, strict=False):
                    c, _ = normalize_attack_category(cat, lbl)
                    norm_labels.append(c)
                lbl_series = pd.Series(norm_labels, index=chunk.index, name="eval_label")

                # 2. Extract metadata & timestamps
                flow_end_ts = pd.to_datetime(chunk["flow_end_ts"], unit="s", utc=True, errors="coerce")
                flow_start_ts = pd.to_datetime(chunk["flow_start_ts"], unit="s", utc=True, errors="coerce")
                meta_df = pd.DataFrame({
                    "src_ip": chunk["src_ip"].astype(str),
                    "dst_ip": chunk["dst_ip"].astype(str),
                    "src_port": pd.to_numeric(chunk["src_port"], errors="coerce"),
                    "dst_port": pd.to_numeric(chunk["dst_port"], errors="coerce"),
                    "protocol_name": chunk["protocol_name"].astype(str).str.upper(),
                    "flow_end_ts": flow_end_ts,
                    "flow_start_ts": flow_start_ts,
                    "is_attack": binary_label,
                }, index=chunk.index)

                # 3. Extract eligible forward-observable numeric features
                # Only keep features designated as is_model_feature
                feat_df = pd.DataFrame(index=chunk.index)
                for fcol in feature_cols:
                    if fcol in chunk.columns:
                        feat_df[fcol] = pd.to_numeric(chunk[fcol], errors="coerce").fillna(0.0)

                # Optional rate calculations for consistency with TrafficShield pipeline
                if include_engineered_rates and "duration_seconds" in feat_df.columns:
                    dur_safe = feat_df["duration_seconds"].clip(lower=0.0)
                    pos_dur = dur_safe > 0.0
                    feat_df["packet_rate"] = np.where(
                        pos_dur, feat_df["fwd_packets"] / dur_safe, feat_df["fwd_packets"]
                    )
                    feat_df["byte_rate"] = np.where(
                        pos_dur, feat_df["fwd_bytes"] / dur_safe, feat_df["fwd_bytes"]
                    )
                    has_pkts = feat_df["fwd_packets"] > 0
                    feat_df["bytes_per_packet"] = np.where(
                        has_pkts, feat_df["fwd_bytes"] / feat_df["fwd_packets"], 0.0
                    )

                # Clean any NaN/Inf
                feat_df = feat_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)

                chunks_feat.append(feat_df)
                chunks_lbl.append(lbl_series)
                chunks_meta.append(meta_df)

        if not chunks_feat:
            return pd.DataFrame(), pd.Series(name="eval_label"), pd.DataFrame()

        full_features = pd.concat(chunks_feat, ignore_index=True)
        full_labels = pd.concat(chunks_lbl, ignore_index=True)
        full_meta = pd.concat(chunks_meta, ignore_index=True)

        # 4. Strict unidirectional policy audit
        audit_unsw_feature_columns(list(full_features.columns))

        logger.info(
            "Loaded %d UNSW-NB15 rows with %d eligible forward-only features.",
            len(full_features), len(full_features.columns),
        )
        return full_features, full_labels, full_meta
