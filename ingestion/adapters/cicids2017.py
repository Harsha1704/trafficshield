"""
CICIDS2017 Ingestion Adapter
============================
Milestone 10 — TrafficShield

Memory-conscious, chunked ingestion adapter for CICIDS2017 dataset CSV files.
Enforces the unidirectional feature eligibility policy, strips column whitespace,
sanitizes non-finite values (Infinity/NaN), and extracts canonical forward-observable
features and evaluation targets.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ingestion.adapters.cicids2017_policy import (
    CICIDS_2017_SPECS,
    get_eligible_cicids_model_features,
)

logger = logging.getLogger("cicids2017_adapter")


class CICIDSValidationError(ValueError):
    """Raised when CICIDS2017 input data violates schema or policy rules."""


class CICIDS2017Adapter:
    """Ingestion adapter for CICIDS2017 flow captures."""

    def __init__(self, chunk_size: int = 50_000) -> None:
        self.chunk_size = chunk_size

    def clean_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """Strip leading/trailing whitespace from column names."""
        df.columns = [str(c).strip() for c in df.columns]
        return df

    def sanitize_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean infinities and invalid floating-point representations."""
        # Replace string 'Infinity', 'inf', '-inf' with NaN
        df = df.replace(["Infinity", "inf", "-inf", "Infinity ", " inf"], np.nan)
        # Coerce numeric infinities
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].replace([np.inf, -np.inf], np.nan)
        return df

    def normalize_label(self, label_raw: str) -> tuple[str, int]:
        """
        Normalize raw CICIDS2017 label to standard (category_string, is_attack).
        E.g., 'BENIGN' -> ('normal', 0); 'DoS Hulk' -> ('dos_hulk', 1).
        """
        raw_clean = str(label_raw).strip()
        if raw_clean.upper() == "BENIGN" or raw_clean == "0":
            return "normal", 0
        norm_cat = raw_clean.lower().replace(" ", "_").replace("-", "_")
        return norm_cat, 1

    def load_unidirectional_dataframe(
        self,
        filepaths: list[Path] | list[str],
        max_rows: int | None = None,
        include_rates: bool = True,
    ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        """
        Load CICIDS2017 CSV file(s) into a unidirectional feature DataFrame,
        evaluation label series, and metadata DataFrame.

        Returns:
            feat_df: forward-only numeric features
            lbl_series: normalized category strings (e.g. 'normal', 'portscan')
            meta_df: metadata including is_attack (binary 0/1) and dst_port
        """
        eligible_features = get_eligible_cicids_model_features()
        records_loaded = 0

        feat_chunks: list[pd.DataFrame] = []
        lbl_chunks: list[pd.Series] = []
        meta_chunks: list[pd.DataFrame] = []

        for fp in filepaths:
            p = Path(fp)
            if not p.exists():
                raise FileNotFoundError(f"CICIDS2017 file not found: {p}")

            logger.info("Streaming CICIDS2017 from %s...", p.name)

            chunk_iter = pd.read_csv(
                p,
                chunksize=self.chunk_size,
                encoding="utf-8-sig",
                low_memory=False,
            )

            for chunk in chunk_iter:
                chunk = self.clean_column_names(chunk)
                chunk = self.sanitize_values(chunk)

                if max_rows is not None:
                    remaining = max_rows - records_loaded
                    if remaining <= 0:
                        break
                    if len(chunk) > remaining:
                        chunk = chunk.iloc[:remaining]

                n_chunk = len(chunk)
                records_loaded += n_chunk

                # 1. Labels
                if "Label" in chunk.columns:
                    labels_raw = chunk["Label"].astype(str)
                else:
                    labels_raw = pd.Series(["BENIGN"] * n_chunk, index=chunk.index)

                norm_labels = []
                is_attack_list = []
                for l_str in labels_raw:
                    cat, is_att = self.normalize_label(l_str)
                    norm_labels.append(cat)
                    is_attack_list.append(is_att)

                lbl_s = pd.Series(norm_labels, index=chunk.index, name="eval_label")
                is_attack_s = pd.Series(is_attack_list, index=chunk.index, name="is_attack")

                # 2. Metadata
                dst_port = (
                    pd.to_numeric(chunk["Destination Port"], errors="coerce").fillna(0).astype(int)
                    if "Destination Port" in chunk.columns
                    else pd.Series(0, index=chunk.index)
                )
                meta_chunk = pd.DataFrame({
                    "dst_port": dst_port,
                    "is_attack": is_attack_s,
                }, index=chunk.index)

                # 3. Eligible forward features
                feat_chunk = pd.DataFrame(index=chunk.index)
                for fcol in eligible_features:
                    if fcol in chunk.columns:
                        canonical_name = CICIDS_2017_SPECS[fcol].normalized_name
                        feat_chunk[canonical_name] = pd.to_numeric(chunk[fcol], errors="coerce").fillna(0.0)

                # Optional rate calculations
                if include_rates and "duration_microseconds" in feat_chunk.columns:
                    dur_sec = (feat_chunk["duration_microseconds"] / 1_000_000.0).clip(lower=0.0)
                    feat_chunk["duration_seconds"] = dur_sec
                    pos_dur = dur_sec > 0.0
                    if "fwd_packets" in feat_chunk.columns:
                        feat_chunk["packet_rate"] = np.where(
                            pos_dur, feat_chunk["fwd_packets"] / dur_sec, 0.0
                        )
                    if "fwd_bytes" in feat_chunk.columns:
                        feat_chunk["byte_rate"] = np.where(
                            pos_dur, feat_chunk["fwd_bytes"] / dur_sec, 0.0
                        )
                    if "fwd_bytes" in feat_chunk.columns and "fwd_packets" in feat_chunk.columns:
                        pos_pkts = feat_chunk["fwd_packets"] > 0
                        feat_chunk["bytes_per_packet"] = np.where(
                            pos_pkts, feat_chunk["fwd_bytes"] / feat_chunk["fwd_packets"], 0.0
                        )

                feat_chunks.append(feat_chunk)
                lbl_chunks.append(lbl_s)
                meta_chunks.append(meta_chunk)

                if max_rows is not None and records_loaded >= max_rows:
                    break

            if max_rows is not None and records_loaded >= max_rows:
                break

        if not feat_chunks:
            return pd.DataFrame(), pd.Series(dtype=str), pd.DataFrame()

        all_feats = pd.concat(feat_chunks, ignore_index=True)
        all_lbls = pd.concat(lbl_chunks, ignore_index=True)
        all_meta = pd.concat(meta_chunks, ignore_index=True)

        logger.info(
            "Loaded %d CICIDS2017 records with %d forward features (attacks: %d = %.2f%%).",
            len(all_feats),
            len(all_feats.columns),
            int(all_meta["is_attack"].sum()),
            (all_meta["is_attack"].sum() / len(all_feats)) * 100.0 if len(all_feats) > 0 else 0.0,
        )
        return all_feats, all_lbls, all_meta

    @staticmethod
    def generate_synthetic_cicids_dataframe(
        n_samples: int = 1000,
        anomaly_ratio: float = 0.1,
        random_seed: int = 42,
    ) -> pd.DataFrame:
        """
        Generate a synthetic DataFrame matching the exact schema and statistics of CICIDS2017.
        Enables reproducible offline testing without requiring 3+ GB raw files.
        """
        rng = np.random.default_rng(random_seed)
        n_anom = int(n_samples * anomaly_ratio)
        n_norm = n_samples - n_anom

        # Normal distributions
        dur_norm = rng.exponential(scale=500_000, size=n_norm)
        pkts_norm = rng.poisson(lam=8, size=n_norm) + 1
        bytes_norm = pkts_norm * rng.integers(40, 1460, size=n_norm)

        # Anomaly distributions (volumetric flood / scan)
        dur_anom = rng.exponential(scale=50_000, size=n_anom)
        pkts_anom = rng.poisson(lam=120, size=n_anom) + 10
        bytes_anom = pkts_anom * rng.integers(200, 1500, size=n_anom)

        durations = np.concatenate([dur_norm, dur_anom])
        fwd_pkts = np.concatenate([pkts_norm, pkts_anom])
        fwd_bytes = np.concatenate([bytes_norm, bytes_anom])

        labels = ["BENIGN"] * n_norm + ["DoS Hulk"] * (n_anom // 2) + ["PortScan"] * (n_anom - (n_anom // 2))

        data: dict[str, Any] = {
            " Destination Port": rng.choice([80, 443, 22, 53, 8080], size=n_samples),
            " Flow Duration": durations,
            " Total Fwd Packets": fwd_pkts,
            " Total Backward Packets": np.concatenate([rng.poisson(6, n_norm), rng.poisson(1, n_anom)]),
            "Total Length of Fwd Packets": fwd_bytes,
            " Total Length of Bwd Packets": fwd_bytes * 0.8,
            " Fwd Packet Length Max": np.clip(fwd_bytes / fwd_pkts * 1.5, 40, 1500),
            " Fwd Packet Length Min": np.clip(fwd_bytes / fwd_pkts * 0.5, 40, 1500),
            " Fwd Packet Length Mean": fwd_bytes / fwd_pkts,
            " Fwd Packet Length Std": rng.uniform(0, 100, size=n_samples),
            "Bwd Packet Length Max": rng.uniform(40, 1500, size=n_samples),
            " Bwd Packet Length Min": rng.uniform(0, 100, size=n_samples),
            " Bwd Packet Length Mean": rng.uniform(40, 1000, size=n_samples),
            " Bwd Packet Length Std": rng.uniform(0, 100, size=n_samples),
            "Flow Bytes/s": np.where(durations > 0, (fwd_bytes * 1.8) / (durations / 1e6), np.nan),
            " Flow Packets/s": np.where(durations > 0, (fwd_pkts * 2.0) / (durations / 1e6), np.nan),
            " Flow IAT Mean": rng.exponential(10000, size=n_samples),
            " Flow IAT Std": rng.exponential(5000, size=n_samples),
            " Flow IAT Max": rng.exponential(50000, size=n_samples),
            " Flow IAT Min": rng.exponential(100, size=n_samples),
            "Fwd IAT Total": durations,
            " Fwd IAT Mean": durations / fwd_pkts,
            " Fwd IAT Std": rng.uniform(0, 5000, size=n_samples),
            " Fwd IAT Max": durations * 0.6,
            " Fwd IAT Min": rng.uniform(10, 1000, size=n_samples),
            "Bwd IAT Total": durations * 0.8,
            " Bwd IAT Mean": rng.uniform(100, 10000, size=n_samples),
            " Bwd IAT Std": rng.uniform(0, 5000, size=n_samples),
            " Bwd IAT Max": rng.uniform(1000, 50000, size=n_samples),
            " Bwd IAT Min": rng.uniform(10, 100, size=n_samples),
            "Fwd PSH Flags": rng.choice([0, 1], p=[0.8, 0.2], size=n_samples),
            " Bwd PSH Flags": rng.choice([0, 1], p=[0.9, 0.1], size=n_samples),
            " Fwd URG Flags": [0] * n_samples,
            " Bwd URG Flags": [0] * n_samples,
            " Fwd Header Length": fwd_pkts * 20,
            " Bwd Header Length": fwd_pkts * 20,
            "Fwd Packets/s": np.where(durations > 0, fwd_pkts / (durations / 1e6), 0.0),
            " Bwd Packets/s": np.where(durations > 0, fwd_pkts / (durations / 1e6), 0.0),
            " Min Packet Length": [40] * n_samples,
            " Max Packet Length": [1500] * n_samples,
            " Packet Length Mean": fwd_bytes / fwd_pkts,
            " Packet Length Std": rng.uniform(10, 150, size=n_samples),
            " Packet Length Variance": rng.uniform(100, 22500, size=n_samples),
            "FIN Flag Count": rng.choice([0, 1], p=[0.7, 0.3], size=n_samples),
            " SYN Flag Count": rng.choice([0, 1], p=[0.8, 0.2], size=n_samples),
            " RST Flag Count": rng.choice([0, 1], p=[0.95, 0.05], size=n_samples),
            " PSH Flag Count": rng.choice([0, 1], p=[0.8, 0.2], size=n_samples),
            " ACK Flag Count": rng.choice([0, 1], p=[0.3, 0.7], size=n_samples),
            " URG Flag Count": [0] * n_samples,
            " CWE Flag Count": [0] * n_samples,
            " ECE Flag Count": [0] * n_samples,
            " Down/Up Ratio": rng.choice([0, 1, 2], p=[0.1, 0.8, 0.1], size=n_samples),
            " Average Packet Size": fwd_bytes / fwd_pkts,
            " Avg Fwd Segment Size": fwd_bytes / fwd_pkts,
            " Avg Bwd Segment Size": fwd_bytes / fwd_pkts * 0.9,
            " Fwd Header Length.1": fwd_pkts * 20,
            "Fwd Avg Bytes/Bulk": [0.0] * n_samples,
            " Fwd Avg Packets/Bulk": [0.0] * n_samples,
            " Fwd Avg Bulk Rate": [0.0] * n_samples,
            " Bwd Avg Bytes/Bulk": [0.0] * n_samples,
            " Bwd Avg Packets/Bulk": [0.0] * n_samples,
            "Bwd Avg Bulk Rate": [0.0] * n_samples,
            "Subflow Fwd Packets": fwd_pkts,
            " Subflow Fwd Bytes": fwd_bytes,
            " Subflow Bwd Packets": fwd_pkts * 0.8,
            " Subflow Bwd Bytes": fwd_bytes * 0.8,
            "Init_Win_bytes_forward": rng.choice([255, 65535, 29200, -1], size=n_samples),
            " Init_Win_bytes_backward": rng.choice([255, 65535, 29200, -1], size=n_samples),
            " act_data_pkt_fwd": np.maximum(1, fwd_pkts - 2),
            " min_seg_size_forward": [20] * n_samples,
            "Active Mean": [0.0] * n_samples,
            " Active Std": [0.0] * n_samples,
            " Active Max": [0.0] * n_samples,
            " Active Min": [0.0] * n_samples,
            "Idle Mean": [0.0] * n_samples,
            " Idle Std": [0.0] * n_samples,
            " Idle Max": [0.0] * n_samples,
            " Idle Min": [0.0] * n_samples,
            " Label": labels,
        }
        df = pd.DataFrame(data)
        # Inject realistic non-finite artifact (some rows with string 'Infinity')
        df["Flow Bytes/s"] = df["Flow Bytes/s"].astype(object)
        df.loc[rng.choice(n_samples, size=max(1, n_samples // 100), replace=False), "Flow Bytes/s"] = "Infinity"
        return df
