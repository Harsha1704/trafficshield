"""
UGR'16 Dataset Adapter
========================
Milestone 2 — TrafficShield

Converts UGR'16 CSV flow records into CanonicalFlow objects.

Verified UGR'16 CSV schema (13 columns, nfdump export):
    te, td, sa, da, sp, dp, pr, flg, fwd, stos, pkt, byt, class

Sources:
    - Maciá-Fernández et al., "UGR'16: A New Dataset for the Evaluation of
      Cyclostationarity-Based Network IDSs", Computer Networks, Elsevier, 2018
    - https://nesg.ugr.es/nesg-ugr16/index.php
    - Confirmed column order from dataset documentation and prior literature

Key design decisions
--------------------
1. Chunked reading: never loads the entire file into memory.
2. Malformed rows: logged and counted, never silently discarded.
3. Labels: the 'class' column maps to eval_label ONLY — never to features.
4. Missing values: explicit None, never sentinel zeros.
5. Protocol: stored as string ('TCP', 'UDP', ...) and optional IANA number.
6. TCP flags: preserved as-is from nfdump output.
7. Provenance: source_file and source_row_index tracked per record.
8. IP validation: ipaddress module used on every record.

Limitations
-----------
- UGR'16 timestamps include only 'te' (flow end); there is no 'ts' (start)
  in the standard nfdump export. Duration td allows inferring start, but
  this is not stored to avoid implicit assumptions about clock accuracy.
- IPs are anonymized with CryptoPan. The adapter does not attempt to reverse
  the anonymization.
- The 'fwd' (forwarding status) field is router-internal metadata.
  It is eligible as a feature but may be uninformative.
"""
from __future__ import annotations

import csv
import gzip
import io
import logging
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ingestion.schema.canonical_flow import (
    UGR16_ATTACK_LABELS,
    UGR16_BENIGN_LABEL,
    CanonicalFlow,
    IngestionResult,
    SourceDataset,
)

logger = logging.getLogger(__name__)


# ─── Verified UGR'16 column contract ─────────────────────────────────────────

# Exact column names as produced by the UGR'16 nfdump CSV export.
# Source: verified from dataset documentation and literature.
UGR16_COLUMNS: tuple[str, ...] = (
    "te", "td", "sa", "da", "sp", "dp", "pr", "flg", "fwd", "stos",
    "pkt", "byt", "class",
)

# Minimum required columns for a usable record
UGR16_REQUIRED_COLUMNS: frozenset[str] = frozenset({
    "te", "sa", "da", "pr", "pkt", "byt",
})

# UGR'16 timestamp format: '2016-04-01 00:00:02.123'
UGR16_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
UGR16_TIMESTAMP_FORMAT_NOSUB = "%Y-%m-%d %H:%M:%S"


def _parse_ugr16_timestamp(raw: str) -> datetime | None:
    """
    Parse a UGR'16 timestamp string to a timezone-aware UTC datetime.

    Handles both sub-second and whole-second formats.
    Returns None on parse failure.
    """
    raw = raw.strip()
    for fmt in (UGR16_TIMESTAMP_FORMAT, UGR16_TIMESTAMP_FORMAT_NOSUB):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_optional_int(raw: str | None, field: str, row_idx: int) -> int | None:
    """Parse an integer field; return None on blank or invalid input."""
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        logger.debug("Row %d: cannot parse %r as int for field %s", row_idx, raw, field)
        return None


def _parse_optional_float(raw: str | None, field: str, row_idx: int) -> float | None:
    """Parse a float field; return None on blank or invalid input."""
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        logger.debug("Row %d: cannot parse %r as float for field %s", row_idx, raw, field)
        return None


def _normalise_label(raw_class: str) -> tuple[str, bool]:
    """
    Normalise the UGR'16 'class' field.

    Returns (normalised_label, is_attack).
    """
    raw = raw_class.strip().lower()
    if not raw or raw == UGR16_BENIGN_LABEL:
        return UGR16_BENIGN_LABEL, False
    if raw in UGR16_ATTACK_LABELS:
        return raw, True
    # Unknown label — log it but preserve
    logger.debug("Unknown UGR'16 class label: %r", raw_class)
    return raw, True   # treat unknown as potential attack


def _open_file(filepath: Path) -> io.TextIOWrapper:
    """Open a plain or gzip-compressed CSV file for reading."""
    suffix = filepath.suffix.lower()
    if suffix == ".gz":
        return gzip.open(filepath, "rt", encoding="utf-8", errors="replace")
    return open(filepath, encoding="utf-8", errors="replace")


class UGR16ValidationError(Exception):
    """Raised when a file fails schema validation before record processing."""


class UGR16Adapter:
    """
    Adapter that reads UGR'16 CSV files and yields CanonicalFlow records.

    Parameters
    ----------
    chunk_size : int
        Number of source rows processed per chunk (controls memory usage).
        Default: 10_000 rows ≈ a few MB of intermediate objects.
    strict_columns : bool
        If True, raise UGR16ValidationError when the header does not exactly
        match UGR16_COLUMNS. If False, only required columns are checked.
    skip_invalid_rows : bool
        If True (default), malformed rows are counted and skipped.
        If False, raise on first malformed row.
    """

    def __init__(
        self,
        chunk_size: int = 10_000,
        strict_columns: bool = False,
        skip_invalid_rows: bool = True,
    ) -> None:
        self.chunk_size = max(1, chunk_size)
        self.strict_columns = strict_columns
        self.skip_invalid_rows = skip_invalid_rows

    # ─── Public API ───────────────────────────────────────────────────────────

    def validate_header(self, columns: list[str]) -> None:
        """
        Validate CSV header columns against the known UGR'16 schema.

        Raises UGR16ValidationError if required columns are missing.
        Logs a warning (not an error) for unexpected extra columns.
        """
        col_set = {c.strip().lower() for c in columns}

        # Strict mode: exact match
        if self.strict_columns:
            expected = set(UGR16_COLUMNS)
            if col_set != expected:
                missing = expected - col_set
                extra = col_set - expected
                raise UGR16ValidationError(
                    f"Strict mode: column mismatch. "
                    f"Missing={missing!r}, Extra={extra!r}"
                )
            return

        # Relaxed mode: only required columns must be present
        missing_required = UGR16_REQUIRED_COLUMNS - col_set
        if missing_required:
            raise UGR16ValidationError(
                f"Missing required UGR'16 columns: {missing_required!r}. "
                f"Got: {col_set!r}"
            )

        extra = col_set - set(UGR16_COLUMNS)
        if extra:
            logger.warning(
                "UGR'16 file contains unexpected extra columns: %r. "
                "They will be ignored.",
                extra,
            )

        missing_optional = set(UGR16_COLUMNS) - col_set - UGR16_REQUIRED_COLUMNS
        if missing_optional:
            logger.info(
                "UGR'16 file is missing optional columns: %r. "
                "Affected fields will be set to None.",
                missing_optional,
            )

    def iter_records(
        self,
        filepath: Path,
    ) -> Generator[tuple[CanonicalFlow | None, str | None], None, None]:
        """
        Yield (CanonicalFlow | None, rejection_reason | None) for every data row.

        A yielded (flow, None) is an accepted record.
        A yielded (None, reason) is a rejected record.

        Never loads the full file into memory; reads row by row.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"UGR'16 file not found: {filepath}")

        row_index = 0
        with _open_file(filepath) as fh:
            reader = csv.DictReader(fh)

            if reader.fieldnames is None:
                raise UGR16ValidationError("File appears to have no header row")

            # Strip whitespace from column names (nfdump sometimes adds spaces)
            stripped_fieldnames = [f.strip() for f in reader.fieldnames]
            reader.fieldnames = stripped_fieldnames

            self.validate_header(stripped_fieldnames)

            for raw_row in reader:
                row_index += 1
                try:
                    # Check if entire row is empty/whitespace (including trailing None columns from blank lines)
                    has_any_content = any(
                        str(v).strip() for v in raw_row.values() if v is not None and str(v).strip()
                    )
                    if not has_any_content:
                        yield None, "empty_row"
                        continue

                    # Check for short rows where columns were missing in CSV
                    if None in raw_row.values():
                        yield None, "short_row:missing_columns"
                        continue

                    # Safely extract and strip keys and string values
                    row: dict[str, str] = {}
                    for k, v in raw_row.items():
                        if k is None:
                            continue
                        clean_k = str(k).strip()
                        if not clean_k:
                            continue
                        if v is None:
                            clean_v = ""
                        elif isinstance(v, str):
                            clean_v = v.strip()
                        else:
                            clean_v = str(v).strip()
                        row[clean_k] = clean_v

                    result = self._parse_row(row, row_index, str(filepath))
                    if isinstance(result, CanonicalFlow):
                        yield result, None
                    else:
                        yield None, result
                except Exception as exc:
                    logger.debug("Row %d parsing failed: %s", row_index, exc, exc_info=True)
                    if not self.skip_invalid_rows:
                        raise
                    yield None, f"row_exception:{type(exc).__name__}"

    def process_file(
        self,
        filepath: Path,
    ) -> tuple[IngestionResult, Generator[list[CanonicalFlow], None, None]]:
        """
        Process a UGR'16 CSV file in chunks.

        Returns
        -------
        result : IngestionResult
            Updated in-place as processing proceeds. Call result.finish()
            when the generator is exhausted.
        chunks : Generator[list[CanonicalFlow]]
            Yields non-empty lists of accepted CanonicalFlow records.
        """
        filepath = Path(filepath)
        result = IngestionResult(
            source_file=str(filepath),
            source_dataset=SourceDataset.UGR16,
        )

        def _chunk_generator() -> Generator[list[CanonicalFlow], None, None]:
            chunk: list[CanonicalFlow] = []
            for flow, rejection_reason in self.iter_records(filepath):
                result.rows_read += 1
                if flow is not None:
                    result.rows_accepted += 1
                    chunk.append(flow)
                    if len(chunk) >= self.chunk_size:
                        yield chunk
                        chunk = []
                else:
                    result.record_rejection(rejection_reason or "unknown")

            if chunk:
                yield chunk
            result.finish()
            logger.info(
                "UGR'16 ingestion complete: %s — read=%d, accepted=%d, rejected=%d",
                filepath.name,
                result.rows_read,
                result.rows_accepted,
                result.rows_rejected,
            )
            if result.rejection_reasons:
                logger.warning("Rejection reasons: %s", result.rejection_reasons)

        return result, _chunk_generator()

    # ─── Internal: row parsing ─────────────────────────────────────────────────

    def _parse_row(
        self,
        row: dict[str, str],
        row_index: int,
        source_file: str,
    ) -> CanonicalFlow | str:
        """
        Convert a raw CSV row dict into a CanonicalFlow.

        Returns CanonicalFlow on success, or a rejection reason string on failure.
        """
        # ── Timestamp (required) ──────────────────────────────────────────────
        raw_te = (row.get("te") or "").strip()
        if not raw_te:
            return "missing_timestamp"

        flow_end_ts = _parse_ugr16_timestamp(raw_te)
        if flow_end_ts is None:
            return f"unparseable_timestamp:{raw_te[:40]}"

        # ── Source / destination IP (required) ────────────────────────────────
        src_ip = (row.get("sa") or "").strip()
        dst_ip = (row.get("da") or "").strip()
        if not src_ip:
            return "missing_src_ip"
        if not dst_ip:
            return "missing_dst_ip"

        # ── Protocol (required) ───────────────────────────────────────────────
        protocol_name = (row.get("pr") or "").strip()
        if not protocol_name:
            return "missing_protocol"

        # ── Traffic counts (required) ─────────────────────────────────────────
        raw_pkt = (row.get("pkt") or "").strip()
        raw_byt = (row.get("byt") or "").strip()
        if not raw_pkt:
            return "missing_pkt"
        if not raw_byt:
            return "missing_byt"

        fwd_packets = _parse_optional_int(raw_pkt, "pkt", row_index)
        fwd_bytes = _parse_optional_int(raw_byt, "byt", row_index)

        if fwd_packets is None:
            return "invalid_pkt"
        if fwd_bytes is None:
            return "invalid_byt"
        if fwd_packets < 0:
            return "negative_pkt"
        if fwd_bytes < 0:
            return "negative_byt"

        # ── Optional fields ───────────────────────────────────────────────────
        td_val = _parse_optional_float(row.get("td"), "td", row_index)
        if td_val is not None and td_val < 0:
            logger.debug("Row %d: negative duration %r — setting to None", row_index, td_val)
            td_val = None

        sp_val = _parse_optional_int(row.get("sp"), "sp", row_index)
        dp_val = _parse_optional_int(row.get("dp"), "dp", row_index)
        fwd_status = _parse_optional_int(row.get("fwd"), "fwd", row_index)
        ip_tos = _parse_optional_int(row.get("stos"), "stos", row_index)

        # Validate port ranges
        if sp_val is not None and not (0 <= sp_val <= 65535):
            logger.debug("Row %d: src port %d out of range — setting to None", row_index, sp_val)
            sp_val = None
        if dp_val is not None and not (0 <= dp_val <= 65535):
            logger.debug("Row %d: dst port %d out of range — setting to None", row_index, dp_val)
            dp_val = None

        # ── TCP flags ─────────────────────────────────────────────────────────
        raw_flg = (row.get("flg") or "").strip() or None
        # Skip if it's just '0' or empty
        if raw_flg in ("0", ""):
            raw_flg = None

        # ── Evaluation label (EVAL_ONLY — not a feature) ──────────────────────
        raw_class = (row.get("class") or "").strip()
        eval_label_raw: str | None = raw_class if raw_class else None
        eval_label: str | None = None
        is_attack: bool | None = None
        if eval_label_raw:
            eval_label, is_attack = _normalise_label(eval_label_raw)

        # ── Construct CanonicalFlow ───────────────────────────────────────────
        try:
            flow = CanonicalFlow(
                source_dataset=SourceDataset.UGR16,
                source_file=source_file,
                source_row_index=row_index - 1,  # 0-based
                flow_end_ts=flow_end_ts,
                duration_seconds=td_val,
                src_ip=src_ip,
                dst_ip=dst_ip,
                src_port=sp_val,
                dst_port=dp_val,
                protocol_name=protocol_name,
                fwd_packets=fwd_packets,
                fwd_bytes=fwd_bytes,
                tcp_flags_raw=raw_flg,
                fwd_status=fwd_status,
                ip_tos=ip_tos,
                eval_label=eval_label,
                eval_label_raw=eval_label_raw,
                is_attack=is_attack,
            )
        except ValidationError as exc:
            reason = _pydantic_error_summary(exc)
            logger.debug("Row %d: validation failed — %s", row_index, reason)
            if not self.skip_invalid_rows:
                raise
            return f"validation_error:{reason}"
        except Exception as exc:
            logger.debug("Row %d: unexpected error — %s", row_index, exc)
            if not self.skip_invalid_rows:
                raise
            return f"unexpected_error:{type(exc).__name__}"

        return flow


def _pydantic_error_summary(exc: ValidationError) -> str:
    """Extract a compact reason string from a pydantic ValidationError."""
    try:
        errors = exc.errors(include_url=False)
        parts = []
        for e in errors[:3]:  # limit to first 3 errors
            loc = ".".join(str(x) for x in e.get("loc", []))
            msg = e.get("msg", "")
            parts.append(f"{loc}:{msg}")
        return ";".join(parts)
    except Exception:
        return str(exc)[:80]
