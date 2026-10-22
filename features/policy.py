"""
Centralized Feature Eligibility Policy
=======================================
Version: 1.0 (Milestone 3)

Defines the explicit, auditable allowlist and blocklist of features for
TrafficShield's unidirectional anomaly detection models.

Guiding Principles
------------------
1. EXPLICIT ALLOWLIST: Only columns explicitly designated with FieldRole.FEATURE
   are allowed into the model feature matrix.
2. ZERO REVERSE LEAKAGE: Any feature that requires observing the reverse
   direction of traffic across the link (backward packets/bytes, RTT,
   bidirectional flags, request-response timing) is strictly FORBIDDEN.
3. ZERO EVALUATION LEAKAGE: Ground-truth attack labels and class annotations
   are designated FieldRole.LABEL and are structurally prohibited from model input.
4. ZERO IDENTIFIER LEAKAGE: High-cardinality raw identifiers (IP addresses,
   record UUIDs, database keys) are designated FieldRole.IDENTIFIER and are
   kept for auditing/provenance only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

FEATURE_POLICY_VERSION: str = "1.0"


class FieldRole(StrEnum):
    """Categorical role of a data field in TrafficShield."""
    FEATURE = "feature"          # Eligible for model training and inference
    LABEL = "label"              # Ground-truth evaluation outcome only (NEVER model input)
    IDENTIFIER = "identifier"    # Provenance / entity identifier (not a model feature)
    TIMESTAMP = "timestamp"      # Ordering, windowing, and chronological splitting
    METADATA = "metadata"        # Operational / audit information
    FORBIDDEN = "forbidden"      # Prohibited (violates unidirectional or leakage constraints)


class DataType(StrEnum):
    """Data types for canonical and engineered fields."""
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    STRING = "string"


@dataclass(frozen=True)
class FieldSpec:
    """Specification and eligibility contract for a single field."""
    name: str
    role: FieldRole
    data_type: DataType
    description: str
    rationale: str
    source: str = "canonical"


# ── Centralized Field Specifications ──────────────────────────────────────────

_POLICY_SPECS: dict[str, FieldSpec] = {
    # ── Canonical numerical features (Eligible) ───────────────────────────────
    "fwd_packets": FieldSpec(
        name="fwd_packets",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Forward-direction packet count",
        rationale="Observable from monitored direction link counters.",
    ),
    "fwd_bytes": FieldSpec(
        name="fwd_bytes",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Forward-direction byte count",
        rationale="Observable from monitored direction packet headers.",
    ),
    "duration_seconds": FieldSpec(
        name="duration_seconds",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Observed flow duration in seconds",
        rationale="Measured at the observation sensor from first to last seen packet.",
    ),
    "fwd_status": FieldSpec(
        name="fwd_status",
        role=FieldRole.FEATURE,
        data_type=DataType.CATEGORICAL,
        description="NetFlow forwarding status byte",
        rationale="Router-level observation; no reverse-direction dependency.",
    ),
    "ip_tos": FieldSpec(
        name="ip_tos",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="IP Type of Service / DSCP byte",
        rationale="Present in observed IP header.",
    ),

    # ── Engineered rate and volume features (Eligible) ────────────────────────
    "packet_rate": FieldSpec(
        name="packet_rate",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Packets per second (fwd_packets / duration)",
        rationale="Derived solely from forward packet count and duration.",
        source="engineered",
    ),
    "byte_rate": FieldSpec(
        name="byte_rate",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Bytes per second (fwd_bytes / duration)",
        rationale="Derived solely from forward byte count and duration.",
        source="engineered",
    ),
    "bytes_per_packet": FieldSpec(
        name="bytes_per_packet",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Average bytes per packet (fwd_bytes / fwd_packets)",
        rationale="Reflects packet payload size in observed direction.",
        source="engineered",
    ),

    # ── Log-transformed numerical features (Eligible) ─────────────────────────
    "log_fwd_packets": FieldSpec(
        name="log_fwd_packets",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="log1p(fwd_packets)",
        rationale="Compresses heavy-tailed flow packet distributions.",
        source="engineered",
    ),
    "log_fwd_bytes": FieldSpec(
        name="log_fwd_bytes",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="log1p(fwd_bytes)",
        rationale="Compresses heavy-tailed byte volume distributions.",
        source="engineered",
    ),
    "log_duration": FieldSpec(
        name="log_duration",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="log1p(duration_seconds)",
        rationale="Normalizes flow duration spread.",
        source="engineered",
    ),
    "log_packet_rate": FieldSpec(
        name="log_packet_rate",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="log1p(packet_rate)",
        rationale="Stabilizes packet rate variance.",
        source="engineered",
    ),
    "log_byte_rate": FieldSpec(
        name="log_byte_rate",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="log1p(byte_rate)",
        rationale="Stabilizes byte rate variance.",
        source="engineered",
    ),
    "log_bytes_per_packet": FieldSpec(
        name="log_bytes_per_packet",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="log1p(bytes_per_packet)",
        rationale="Stabilizes payload size variance.",
        source="engineered",
    ),

    # ── Protocol and port categories (Eligible) ───────────────────────────────
    "protocol_category": FieldSpec(
        name="protocol_category",
        role=FieldRole.FEATURE,
        data_type=DataType.CATEGORICAL,
        description="Transport protocol group (TCP, UDP, ICMP, OTHER)",
        rationale="Coarse protocol abstraction with bounded cardinality.",
        source="engineered",
    ),
    "dst_port_category": FieldSpec(
        name="dst_port_category",
        role=FieldRole.FEATURE,
        data_type=DataType.CATEGORICAL,
        description="Destination port group (well_known, registered, ephemeral)",
        rationale="Prevents treating port numbers as continuous magnitudes.",
        source="engineered",
    ),
    "src_port_category": FieldSpec(
        name="src_port_category",
        role=FieldRole.FEATURE,
        data_type=DataType.CATEGORICAL,
        description="Source port group (well_known, registered, ephemeral)",
        rationale="Captures client vs service port behavior safely.",
        source="engineered",
    ),
    "is_well_known_dst_port": FieldSpec(
        name="is_well_known_dst_port",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="True if destination port is < 1024",
        rationale="Binary indicator for standard server service targets.",
        source="engineered",
    ),
    "is_tcp": FieldSpec(
        name="is_tcp",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="True if protocol is TCP",
        rationale="Direct protocol indicator.",
        source="engineered",
    ),
    "is_udp": FieldSpec(
        name="is_udp",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="True if protocol is UDP",
        rationale="Direct protocol indicator.",
        source="engineered",
    ),
    "is_icmp": FieldSpec(
        name="is_icmp",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="True if protocol is ICMP",
        rationale="Direct protocol indicator.",
        source="engineered",
    ),

    # ── Observed TCP flag indicators (Eligible) ───────────────────────────────
    "has_syn": FieldSpec(
        name="has_syn",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="SYN flag observed in forward packets",
        rationale="Indicates connection initiation in monitored direction.",
        source="engineered",
    ),
    "has_ack": FieldSpec(
        name="has_ack",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="ACK flag observed in forward packets",
        rationale="Indicates acknowledged sequence in monitored direction.",
        source="engineered",
    ),
    "has_fin": FieldSpec(
        name="has_fin",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="FIN flag observed in forward packets",
        rationale="Indicates connection termination in monitored direction.",
        source="engineered",
    ),
    "has_rst": FieldSpec(
        name="has_rst",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="RST flag observed in forward packets",
        rationale="Indicates connection reset initiated in monitored direction.",
        source="engineered",
    ),
    "has_psh": FieldSpec(
        name="has_psh",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="PSH flag observed in forward packets",
        rationale="Indicates push data in monitored direction.",
        source="engineered",
    ),
    "has_urg": FieldSpec(
        name="has_urg",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="URG flag observed in forward packets",
        rationale="Indicates urgent pointer in monitored direction.",
        source="engineered",
    ),

    # ── Temporal features (Eligible) ──────────────────────────────────────────
    "hour_of_day": FieldSpec(
        name="hour_of_day",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Hour of day (0-23 UTC)",
        rationale="Diurnal network activity baseline.",
        source="engineered",
    ),
    "day_of_week": FieldSpec(
        name="day_of_week",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Day of week (0=Mon, 6=Sun)",
        rationale="Weekly periodicity baseline.",
        source="engineered",
    ),
    "is_weekend": FieldSpec(
        name="is_weekend",
        role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="True for Saturday or Sunday",
        rationale="Captures weekend operational profile shift.",
        source="engineered",
    ),
    "sin_hour": FieldSpec(
        name="sin_hour",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="sin(2 * pi * hour / 24)",
        rationale="Cyclic continuous representation of hour of day.",
        source="engineered",
    ),
    "cos_hour": FieldSpec(
        name="cos_hour",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="cos(2 * pi * hour / 24)",
        rationale="Cyclic continuous representation of hour of day.",
        source="engineered",
    ),
    "sin_day_of_week": FieldSpec(
        name="sin_day_of_week",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="sin(2 * pi * day / 7)",
        rationale="Cyclic continuous representation of day of week.",
        source="engineered",
    ),
    "cos_day_of_week": FieldSpec(
        name="cos_day_of_week",
        role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="cos(2 * pi * day / 7)",
        rationale="Cyclic continuous representation of day of week.",
        source="engineered",
    ),

    # ── Timestamps (Non-Feature: Ordering / Splitting Only) ───────────────────
    "flow_end_ts": FieldSpec(
        name="flow_end_ts",
        role=FieldRole.TIMESTAMP,
        data_type=DataType.DATETIME,
        description="Flow end UTC timestamp",
        rationale="Used for chronological ordering and dataset splitting only.",
    ),
    "ingest_ts": FieldSpec(
        name="ingest_ts",
        role=FieldRole.TIMESTAMP,
        data_type=DataType.DATETIME,
        description="System ingestion UTC timestamp",
        rationale="Operational audit timestamp.",
    ),

    # ── Identifiers (Non-Feature: Provenance Only) ─────────────────────────────
    "record_id": FieldSpec(
        name="record_id",
        role=FieldRole.IDENTIFIER,
        data_type=DataType.STRING,
        description="Unique UUID assigned at ingest",
        rationale="Unique identifier; has no generalizable feature distribution.",
    ),
    "src_ip": FieldSpec(
        name="src_ip",
        role=FieldRole.IDENTIFIER,
        data_type=DataType.STRING,
        description="Source IP address",
        rationale="Raw IP address must not be treated as a numeric magnitude.",
    ),
    "dst_ip": FieldSpec(
        name="dst_ip",
        role=FieldRole.IDENTIFIER,
        data_type=DataType.STRING,
        description="Destination IP address",
        rationale="Raw IP address must not be treated as a numeric magnitude.",
    ),
    "src_port": FieldSpec(
        name="src_port",
        role=FieldRole.METADATA,
        data_type=DataType.NUMERIC,
        description="Raw source port number",
        rationale="Raw port is converted into port categories to prevent cardinality blowup.",
    ),
    "dst_port": FieldSpec(
        name="dst_port",
        role=FieldRole.METADATA,
        data_type=DataType.NUMERIC,
        description="Raw destination port number",
        rationale="Raw port is converted into port categories to prevent cardinality blowup.",
    ),
    "protocol_name": FieldSpec(
        name="protocol_name",
        role=FieldRole.METADATA,
        data_type=DataType.STRING,
        description="Protocol name string",
        rationale="Normalized into protocol_category.",
    ),
    "protocol_number": FieldSpec(
        name="protocol_number",
        role=FieldRole.METADATA,
        data_type=DataType.NUMERIC,
        description="IANA protocol number",
        rationale="Normalized into protocol_category.",
    ),
    "tcp_flags_raw": FieldSpec(
        name="tcp_flags_raw",
        role=FieldRole.METADATA,
        data_type=DataType.STRING,
        description="Raw TCP flags string",
        rationale="Parsed into individual binary flag indicators.",
    ),

    # ── Evaluation Labels (Strictly Evaluation Only) ──────────────────────────
    "eval_label": FieldSpec(
        name="eval_label",
        role=FieldRole.LABEL,
        data_type=DataType.STRING,
        description="Normalized evaluation label",
        rationale="Ground-truth attack classification; prohibited from training.",
    ),
    "eval_label_raw": FieldSpec(
        name="eval_label_raw",
        role=FieldRole.LABEL,
        data_type=DataType.STRING,
        description="Source dataset raw label string",
        rationale="Ground-truth attack label; prohibited from training.",
    ),
    "is_attack": FieldSpec(
        name="is_attack",
        role=FieldRole.LABEL,
        data_type=DataType.BOOLEAN,
        description="Ground-truth binary attack indicator",
        rationale="Direct attack label; prohibited from unsupervised training.",
    ),
    "class": FieldSpec(
        name="class",
        role=FieldRole.LABEL,
        data_type=DataType.STRING,
        description="UGR'16 class column",
        rationale="Attack label; prohibited from model features.",
    ),
    "label": FieldSpec(
        name="label",
        role=FieldRole.LABEL,
        data_type=DataType.STRING,
        description="Generic label column",
        rationale="Attack label; prohibited from model features.",
    ),
    "attack_cat": FieldSpec(
        name="attack_cat",
        role=FieldRole.LABEL,
        data_type=DataType.STRING,
        description="UNSW-NB15 attack category",
        rationale="Attack label; prohibited from model features.",
    ),

    # ── Strictly Forbidden (Reverse-Direction or Leakage) ─────────────────────
    "bwd_packets": FieldSpec(
        name="bwd_packets",
        role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Backward packet count",
        rationale="Requires unobserved reverse direction of traffic.",
    ),
    "bwd_bytes": FieldSpec(
        name="bwd_bytes",
        role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Backward byte count",
        rationale="Requires unobserved reverse direction of traffic.",
    ),
    "bwd_header_length": FieldSpec(
        name="bwd_header_length",
        role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Backward header length",
        rationale="Requires unobserved reverse direction of traffic.",
    ),
    "rtt_ms": FieldSpec(
        name="rtt_ms",
        role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Round-trip time / response latency",
        rationale="Requires observing return packet timestamp.",
    ),
    "response_latency_ms": FieldSpec(
        name="response_latency_ms",
        role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Request-response latency",
        rationale="Requires observing reverse-direction response packet.",
    ),
    "session_complete": FieldSpec(
        name="session_complete",
        role=FieldRole.FORBIDDEN,
        data_type=DataType.BOOLEAN,
        description="Bidirectional session completion state",
        rationale="Requires observing bidirectional handshake/teardown.",
    ),
    "fwd_bwd_packet_ratio": FieldSpec(
        name="fwd_bwd_packet_ratio",
        role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Ratio of forward to backward packets",
        rationale="Requires both traffic directions.",
    ),
    "fwd_bwd_byte_ratio": FieldSpec(
        name="fwd_bwd_byte_ratio",
        role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Ratio of forward to backward bytes",
        rationale="Requires both traffic directions.",
    ),
}


class PolicyViolationError(ValueError):
    """Raised when an attempt is made to use an ineligible or forbidden field as a feature."""


@dataclass
class FeatureAuditResult:
    """Report detailing column classification and eligibility audit."""
    eligible_features: list[str] = field(default_factory=list)
    excluded_columns: dict[str, str] = field(default_factory=dict)
    forbidden_violations: list[str] = field(default_factory=list)
    label_violations: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True if no forbidden or label violations were detected."""
        return len(self.forbidden_violations) == 0 and len(self.label_violations) == 0


def get_field_spec(name: str) -> FieldSpec | None:
    """Retrieve the field specification for a column name."""
    return _POLICY_SPECS.get(name.strip().lower())


def is_eligible_feature(name: str) -> bool:
    """Return True if and only if the field is explicitly allowed as a model feature."""
    spec = get_field_spec(name)
    return spec is not None and spec.role == FieldRole.FEATURE


def get_eligible_features() -> list[str]:
    """Return the ordered list of all eligible model feature names."""
    return [name for name, spec in _POLICY_SPECS.items() if spec.role == FieldRole.FEATURE]


def get_forbidden_features() -> list[str]:
    """Return the list of all known prohibited reverse-direction features."""
    return [name for name, spec in _POLICY_SPECS.items() if spec.role == FieldRole.FORBIDDEN]


def get_evaluation_labels() -> list[str]:
    """Return the list of all known ground-truth evaluation label columns."""
    return [name for name, spec in _POLICY_SPECS.items() if spec.role == FieldRole.LABEL]


def audit_columns(columns: list[str]) -> FeatureAuditResult:
    """
    Audit an input column list against the feature eligibility policy.

    Returns a detailed FeatureAuditResult categorizing each column.
    """
    result = FeatureAuditResult()

    for col in columns:
        cleaned = col.strip().lower()
        spec = get_field_spec(cleaned)

        if spec is None:
            # Unregistered column — default safe stance is to exclude
            result.excluded_columns[col] = "Unregistered column (safe exclusion by allowlist)"
        elif spec.role == FieldRole.FEATURE:
            result.eligible_features.append(col)
        elif spec.role == FieldRole.FORBIDDEN:
            result.forbidden_violations.append(col)
            result.excluded_columns[col] = f"Forbidden: {spec.rationale}"
        elif spec.role == FieldRole.LABEL:
            result.label_violations.append(col)
            result.excluded_columns[col] = f"Label column: {spec.rationale}"
        elif spec.role == FieldRole.IDENTIFIER:
            result.excluded_columns[col] = f"Identifier: {spec.rationale}"
        elif spec.role == FieldRole.TIMESTAMP:
            result.excluded_columns[col] = f"Timestamp: {spec.rationale}"
        elif spec.role == FieldRole.METADATA:
            result.excluded_columns[col] = f"Metadata: {spec.rationale}"

    return result


def validate_feature_columns(columns: list[str], strict: bool = True) -> list[str]:
    """
    Validate that a proposed list of model feature columns contains ONLY eligible features.

    Parameters
    ----------
    columns : list of proposed feature column names
    strict : if True, raise PolicyViolationError on any non-feature or unregistered column.
             if False, filter non-features out and return only eligible features.

    Returns
    -------
    list of validated eligible feature names.
    """
    audit = audit_columns(columns)

    if strict:
        if not audit.is_clean:
            errors = []
            if audit.forbidden_violations:
                errors.append(f"Forbidden reverse-dependent columns: {audit.forbidden_violations}")
            if audit.label_violations:
                errors.append(f"Evaluation label columns cannot be features: {audit.label_violations}")
            raise PolicyViolationError("; ".join(errors))

        if audit.excluded_columns:
            non_features = list(audit.excluded_columns.keys())
            raise PolicyViolationError(
                f"Proposed feature list contains non-feature columns: {non_features}. "
                "Only columns with FieldRole.FEATURE are permitted."
            )

    return audit.eligible_features
