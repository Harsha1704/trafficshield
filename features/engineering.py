"""
Deterministic One-Way Feature Engineering
==========================================
Version: 1.0 (Milestone 3)

Transforms canonical unidirectional IP flow records into engineered
features suitable for unsupervised anomaly detection.

Guarantees
----------
1. All derived features use strictly forward-direction or sensor-local data.
2. IP addresses and unique IDs are never transformed into numeric magnitudes.
3. Zero durations, zero packet counts, negative values, and infinite rates
   are safely guarded and never produce unhandled exceptions or Inf values.
4. Timestamps are transformed into bounded cyclic/diurnal indicators without
   incorporating any future-looking window information.
"""
from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

from features.policy import FieldRole, get_field_spec, is_eligible_feature
from ingestion.schema.canonical_flow import CanonicalFlow


def parse_tcp_flags(flag_str: str | None) -> dict[str, int]:
    """
    Extract binary indicators for standard TCP flags from raw flag strings.

    Supports standard nfdump formats (e.g. '.A..S.', 'FSRPAU', 'SYN', 'ACK').
    """
    if not flag_str or not isinstance(flag_str, str):
        return {
            "has_syn": 0,
            "has_ack": 0,
            "has_fin": 0,
            "has_rst": 0,
            "has_psh": 0,
            "has_urg": 0,
        }

    upper = flag_str.upper()
    return {
        "has_syn": 1 if "S" in upper else 0,
        "has_ack": 1 if "A" in upper else 0,
        "has_fin": 1 if "F" in upper else 0,
        "has_rst": 1 if "R" in upper else 0,
        "has_psh": 1 if "P" in upper else 0,
        "has_urg": 1 if "U" in upper else 0,
    }


def categorize_port(port: float | int | None) -> str:
    """Categorize port number into standard IANA service port bands."""
    if port is None or pd.isna(port) or port < 0:
        return "unknown"
    p = int(port)
    if 0 <= p <= 1023:
        return "well_known"
    elif 1024 <= p <= 49151:
        return "registered"
    elif 49152 <= p <= 65535:
        return "ephemeral"
    return "unknown"


def categorize_protocol(proto: str | None) -> str:
    """Normalize transport protocol to coarse categorical group."""
    if not proto or not isinstance(proto, str):
        return "OTHER"
    p = proto.strip().upper()
    if p in ("TCP", "6"):
        return "TCP"
    elif p in ("UDP", "17"):
        return "UDP"
    elif p in ("ICMP", "1"):
        return "ICMP"
    return "OTHER"


class FeatureEngineer:
    """
    Transforms canonical flow data into engineered feature DataFrames.

    Accepts CanonicalFlow objects, lists of dicts, or pandas DataFrames.
    """

    def __init__(self, include_log_transforms: bool = True) -> None:
        self.include_log_transforms = include_log_transforms

    def transform_flows(self, flows: Iterable[CanonicalFlow]) -> pd.DataFrame:
        """Engineer features from an iterable of CanonicalFlow objects."""
        records = [f.model_dump() for f in flows]
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame.from_records(records)
        return self.transform_dataframe(df)

    def transform_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform a DataFrame of canonical flow records into engineered features.

        Guards against missing columns, Inf, NaN, and zero division.
        """
        if df.empty:
            return pd.DataFrame()

        out = pd.DataFrame(index=df.index)

        # ── 1. Base numerical features ────────────────────────────────────────
        pkts = df["fwd_packets"] if "fwd_packets" in df.columns else pd.Series(0, index=df.index)
        out["fwd_packets"] = pd.to_numeric(pkts, errors="coerce").fillna(0.0).clip(lower=0.0)

        bts = df["fwd_bytes"] if "fwd_bytes" in df.columns else pd.Series(0, index=df.index)
        out["fwd_bytes"] = pd.to_numeric(bts, errors="coerce").fillna(0.0).clip(lower=0.0)

        # Duration in seconds (None or negative is safely clamped)
        if "duration_seconds" in df.columns:
            dur = pd.to_numeric(df["duration_seconds"], errors="coerce")
            out["duration_seconds"] = dur.clip(lower=0.0).fillna(0.0)
        else:
            out["duration_seconds"] = 0.0

        # Router metadata (optional)
        if "fwd_status" in df.columns:
            out["fwd_status"] = pd.to_numeric(df["fwd_status"], errors="coerce").fillna(0).astype(int)
        else:
            out["fwd_status"] = 0

        if "ip_tos" in df.columns:
            out["ip_tos"] = pd.to_numeric(df["ip_tos"], errors="coerce").fillna(0).astype(int)
        else:
            out["ip_tos"] = 0

        # ── 2. Derived rates and ratios ───────────────────────────────────────
        dur_safe = out["duration_seconds"].copy()
        # For rates, avoid divide by zero: if duration == 0, rate is based on instantaneous flow
        has_positive_dur = dur_safe > 0.0

        out["packet_rate"] = np.where(has_positive_dur, out["fwd_packets"] / dur_safe, out["fwd_packets"].astype(float))
        out["byte_rate"] = np.where(has_positive_dur, out["fwd_bytes"] / dur_safe, out["fwd_bytes"].astype(float))

        pkt_safe = out["fwd_packets"].copy()
        out["bytes_per_packet"] = np.where(pkt_safe > 0, out["fwd_bytes"] / pkt_safe, 0.0)

        # Clean infs or NaNs resulting from any extreme inputs
        for col in ("packet_rate", "byte_rate", "bytes_per_packet"):
            out[col] = out[col].replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)

        # ── 3. Log transforms (optional, stabilization) ────────────────────────
        if self.include_log_transforms:
            out["log_fwd_packets"] = np.log1p(out["fwd_packets"])
            out["log_fwd_bytes"] = np.log1p(out["fwd_bytes"])
            out["log_duration"] = np.log1p(out["duration_seconds"])
            out["log_packet_rate"] = np.log1p(out["packet_rate"])
            out["log_byte_rate"] = np.log1p(out["byte_rate"])
            out["log_bytes_per_packet"] = np.log1p(out["bytes_per_packet"])

        # ── 4. Protocol features ──────────────────────────────────────────────
        raw_proto = df["protocol_name"].astype(str) if "protocol_name" in df.columns else pd.Series("OTHER", index=df.index)
        proto_cat = raw_proto.apply(categorize_protocol)
        out["protocol_category"] = proto_cat
        out["is_tcp"] = (proto_cat == "TCP").astype(int)
        out["is_udp"] = (proto_cat == "UDP").astype(int)
        out["is_icmp"] = (proto_cat == "ICMP").astype(int)

        # ── 5. Port features ──────────────────────────────────────────────────
        dst_p = pd.to_numeric(df["dst_port"], errors="coerce") if "dst_port" in df.columns else pd.Series(np.nan, index=df.index)
        src_p = pd.to_numeric(df["src_port"], errors="coerce") if "src_port" in df.columns else pd.Series(np.nan, index=df.index)

        out["dst_port_category"] = dst_p.apply(categorize_port)
        out["src_port_category"] = src_p.apply(categorize_port)
        out["is_well_known_dst_port"] = ((dst_p >= 0) & (dst_p <= 1023)).astype(int)

        # ── 6. Observed TCP flags ─────────────────────────────────────────────
        raw_flags = df["tcp_flags_raw"] if "tcp_flags_raw" in df.columns else pd.Series("", index=df.index)
        flag_dicts = [parse_tcp_flags(f) for f in raw_flags]
        flags_df = pd.DataFrame(flag_dicts, index=df.index)
        for col in ("has_syn", "has_ack", "has_fin", "has_rst", "has_psh", "has_urg"):
            out[col] = flags_df[col].astype(int)

        # ── 7. Temporal features ──────────────────────────────────────────────
        if "flow_end_ts" in df.columns:
            ts_series = pd.to_datetime(df["flow_end_ts"], utc=True, errors="coerce")
            valid_ts = ts_series.notna()

            hours = np.where(valid_ts, ts_series.dt.hour, 0)
            dows = np.where(valid_ts, ts_series.dt.dayofweek, 0)

            out["hour_of_day"] = hours
            out["day_of_week"] = dows
            out["is_weekend"] = (dows >= 5).astype(int)

            # Continuous cyclic sine/cosine representations
            two_pi = 2.0 * math.pi
            out["sin_hour"] = np.sin(two_pi * hours / 24.0)
            out["cos_hour"] = np.cos(two_pi * hours / 24.0)
            out["sin_day_of_week"] = np.sin(two_pi * dows / 7.0)
            out["cos_day_of_week"] = np.cos(two_pi * dows / 7.0)
        else:
            out["hour_of_day"] = 0
            out["day_of_week"] = 0
            out["is_weekend"] = 0
            out["sin_hour"] = 0.0
            out["cos_hour"] = 1.0
            out["sin_day_of_week"] = 0.0
            out["cos_day_of_week"] = 1.0

        # Pass through any pre-existing eligible feature columns (e.g. temporal behavioural features)
        for col in df.columns:
            if col not in out.columns and is_eligible_feature(col):
                out[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        # Replace any remaining NaNs or Infs
        out = out.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return out


def extract_features_and_labels(
    df: pd.DataFrame,
    engineer: FeatureEngineer | None = None,
) -> tuple[pd.DataFrame, pd.Series | None, pd.DataFrame]:
    """
    Separate input data into:
    1. Engineered feature matrix (model eligible only)
    2. Ground-truth evaluation labels (evaluation only, None if absent)
    3. Provenance/metadata DataFrame (identifiers, IPs, timestamps)
    """
    eng = engineer or FeatureEngineer()
    features = eng.transform_dataframe(df)

    # Extract label if present
    labels = None
    for label_col in ("eval_label", "class", "label", "is_attack"):
        if label_col in df.columns:
            labels = df[label_col].copy()
            break

    # Extract metadata / identifiers
    meta_cols: list[str] = []
    for c in df.columns:
        spec = get_field_spec(c)
        if spec is not None and spec.role in (
            FieldRole.IDENTIFIER, FieldRole.TIMESTAMP, FieldRole.METADATA
        ):
            meta_cols.append(c)
    metadata = df[meta_cols].copy() if meta_cols else pd.DataFrame(index=df.index)

    return features, labels, metadata
