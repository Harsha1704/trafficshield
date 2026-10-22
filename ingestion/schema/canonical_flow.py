"""
Canonical Unidirectional Flow Schema
=====================================
Version: 1.0  (Milestone 2)

Defines the normalised representation of a single-direction network flow
record that TrafficShield uses internally, independent of source dataset.

Design principles
-----------------
1. Only fields observable from ONE direction of traffic are modelled here.
   Fields requiring the reverse direction are explicitly excluded from the
   model-feature view (see PROHIBITED_FEATURE_COLUMNS).
2. Evaluation labels (e.g. 'attack', 'class') are carried in ``eval_label``
   and ``eval_label_raw`` — they are NEVER part of the feature vector.
3. Every field has a documented provenance (where it comes from) and
   eligibility status.
4. Missing values are represented as ``None`` (Python) / ``null`` (JSON),
   never as sentinel zeros or negative numbers.
5. Source-record provenance is preserved to allow auditing.

Field eligibility codes
-----------------------
ELIGIBLE   — may be used as a model feature
PROHIBITED — requires reverse-direction data; must not be a model feature
METADATA   — provenance / bookkeeping field; not a model feature
EVAL_ONLY  — evaluation label; NEVER used for training or inference
"""
from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Constants ────────────────────────────────────────────────────────────────

SCHEMA_VERSION: str = "1.0"

# Known protocol name normalisations (UGR'16 uses uppercase strings)
_PROTOCOL_MAP: dict[str, int] = {
    "HOPOPT": 0, "ICMP": 1, "IGMP": 2, "GGP": 3, "IPV4": 4,
    "TCP": 6, "UDP": 17, "IPV6": 41, "GRE": 47, "ESP": 50,
    "AH": 51, "ICMPV6": 58, "OSPF": 89, "PIM": 103, "SCTP": 132,
    "OTHER": 255,
}

# UGR'16 known attack labels (lower-cased for comparison)
UGR16_ATTACK_LABELS: frozenset[str] = frozenset(
    {"dos", "scan11", "scan12", "nerisbotnet", "spam", "blacklist"}
)
UGR16_BENIGN_LABEL: str = "background"

# ── Eligibility metadata ───────────────────────────────────────────────────────
# Maps canonical field names to their eligibility status.
# Used by the feature engineering pipeline to filter columns.

ELIGIBLE_FEATURE_COLUMNS: frozenset[str] = frozenset({
    # Temporal
    "flow_end_ts",
    "duration_seconds",
    # Network identifiers (used as categorical / behavioural, not numeric)
    "src_ip",
    "dst_ip",
    "src_port",
    "dst_port",
    "protocol_name",
    "protocol_number",
    # Observed-direction traffic volume
    "fwd_packets",
    "fwd_bytes",
    # Observed-direction TCP flags (cumulative in observed direction)
    "tcp_flags_raw",
    # Router metadata (no reverse-direction dependency)
    "fwd_status",
    "ip_tos",
})

PROHIBITED_FEATURE_COLUMNS: frozenset[str] = frozenset({
    # These would require reverse-direction data
    "bwd_packets",
    "bwd_bytes",
    "bwd_header_length",
    "rtt_ms",
    "response_latency_ms",
    "session_complete",
    "fwd_bwd_packet_ratio",
    "fwd_bwd_byte_ratio",
})

EVAL_ONLY_COLUMNS: frozenset[str] = frozenset({
    "eval_label",
    "eval_label_raw",
    "is_attack",
})

METADATA_COLUMNS: frozenset[str] = frozenset({
    "record_id",
    "source_dataset",
    "source_file",
    "source_row_index",
    "schema_version",
    "ingest_ts",
})


# ─── Enums ────────────────────────────────────────────────────────────────────

class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    PROHIBITED = "prohibited"
    METADATA = "metadata"
    EVAL_ONLY = "eval_only"


class SourceDataset(str, Enum):
    UGR16 = "ugr16"
    CICIDS2017 = "cicids2017"
    UNSWNB15 = "unswnb15"
    CSE_CIC_IDS2018 = "cse_cic_ids2018"
    SYNTHETIC = "synthetic"
    UNKNOWN = "unknown"


# ─── Core schema ──────────────────────────────────────────────────────────────

class CanonicalFlow(BaseModel):
    """
    A single normalised, unidirectional network flow record.

    This is the internal representation that all dataset adapters must produce.
    Downstream feature engineering, preprocessing, and detectors consume this type.
    """

    # ── Metadata / provenance (METADATA — not model features) ─────────────────
    record_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique record identifier (UUID4). Assigned at ingest time.",
    )
    source_dataset: SourceDataset = Field(
        default=SourceDataset.UNKNOWN,
        description="Source dataset identifier.",
    )
    source_file: Optional[str] = Field(
        default=None,
        description="Filename or path of the source file this record came from.",
    )
    source_row_index: Optional[int] = Field(
        default=None,
        ge=0,
        description="Zero-based row index in the source file (for traceability).",
    )
    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Canonical schema version.",
    )
    ingest_ts: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this record was ingested into TrafficShield.",
    )

    # ── Temporal (ELIGIBLE) ───────────────────────────────────────────────────
    flow_end_ts: datetime = Field(
        description=(
            "UTC timestamp of the end of the observed flow. "
            "For UGR'16 this maps from the 'te' (time-end) column. "
            "Always stored as timezone-aware UTC. "
            "ELIGIBILITY: ELIGIBLE."
        ),
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        ge=0.0,
        description=(
            "Duration of the observed flow in seconds. "
            "For UGR'16 this maps from the 'td' column. "
            "None when unavailable or unreliable. "
            "ELIGIBILITY: ELIGIBLE (measured at observation point)."
        ),
    )

    # ── Network addresses (ELIGIBLE — treated as categorical identifiers) ──────
    src_ip: str = Field(
        description=(
            "Source IP address as a canonical string (IPv4 or IPv6). "
            "For UGR'16, IPs are anonymized with CryptoPan — they retain "
            "topological structure but cannot be reverse-mapped. "
            "ELIGIBILITY: ELIGIBLE (used as identifier, not numeric value)."
        ),
    )
    dst_ip: str = Field(
        description=(
            "Destination IP address as a canonical string. "
            "ELIGIBILITY: ELIGIBLE."
        ),
    )
    src_port: Optional[int] = Field(
        default=None,
        ge=0,
        le=65535,
        description=(
            "Source port number (0–65535). None for protocols without ports (e.g. ICMP). "
            "ELIGIBILITY: ELIGIBLE."
        ),
    )
    dst_port: Optional[int] = Field(
        default=None,
        ge=0,
        le=65535,
        description=(
            "Destination port number (0–65535). None for protocols without ports. "
            "ELIGIBILITY: ELIGIBLE."
        ),
    )

    # ── Protocol (ELIGIBLE) ───────────────────────────────────────────────────
    protocol_name: str = Field(
        description=(
            "Transport/network protocol name, normalised to uppercase "
            "(e.g. 'TCP', 'UDP', 'ICMP'). "
            "ELIGIBILITY: ELIGIBLE."
        ),
    )
    protocol_number: Optional[int] = Field(
        default=None,
        ge=0,
        le=255,
        description="IANA protocol number. Derived from protocol_name if available.",
    )

    # ── Observed-direction traffic volume (ELIGIBLE) ──────────────────────────
    fwd_packets: int = Field(
        ge=0,
        description=(
            "Number of packets observed in the forward (monitored) direction. "
            "For UGR'16 this maps from 'pkt'. "
            "ELIGIBILITY: ELIGIBLE. "
            "NOTE: In UGR'16, NetFlow records aggregate one direction at the "
            "collection point; 'pkt' represents that direction's count."
        ),
    )
    fwd_bytes: int = Field(
        ge=0,
        description=(
            "Number of bytes observed in the forward direction. "
            "For UGR'16 this maps from 'byt'. "
            "ELIGIBILITY: ELIGIBLE."
        ),
    )

    # ── TCP flags (ELIGIBLE with documented caveat) ───────────────────────────
    tcp_flags_raw: Optional[str] = Field(
        default=None,
        description=(
            "Cumulative TCP flags observed in this direction, as a string "
            "(e.g. '.A.', '.S.', '.FSRPAU.'). None for non-TCP flows. "
            "For UGR'16 this maps from 'flg'. "
            "CAVEAT: ACK flags may indirectly indicate receipt of reverse data, "
            "but they are present in the observed direction headers. "
            "ELIGIBILITY: ELIGIBLE with caveat."
        ),
    )

    # ── Router/sensor metadata (ELIGIBLE) ─────────────────────────────────────
    fwd_status: Optional[int] = Field(
        default=None,
        ge=0,
        le=255,
        description=(
            "NetFlow forwarding status byte (router-level, no reverse dependency). "
            "For UGR'16 this maps from 'fwd'. "
            "ELIGIBILITY: ELIGIBLE."
        ),
    )
    ip_tos: Optional[int] = Field(
        default=None,
        ge=0,
        le=255,
        description=(
            "IP Type of Service / DSCP byte from the IP header. "
            "For UGR'16 this maps from 'stos'. "
            "ELIGIBILITY: ELIGIBLE."
        ),
    )

    # ── PROHIBITED fields (documented but NOT stored in CanonicalFlow) ─────────
    # bwd_packets, bwd_bytes, etc. are intentionally absent.
    # They would require reverse-direction observations.

    # ── Evaluation only (EVAL_ONLY — NEVER in feature matrix) ─────────────────
    eval_label: Optional[str] = Field(
        default=None,
        description=(
            "Normalised evaluation label (e.g. 'background', 'dos', 'scan11'). "
            "For UGR'16 this maps from 'class'. "
            "EVAL_ONLY: Must never enter the model training or inference pipeline."
        ),
    )
    eval_label_raw: Optional[str] = Field(
        default=None,
        description=(
            "Original, unnormalised label string from the source dataset. "
            "EVAL_ONLY: preserved for auditing."
        ),
    )
    is_attack: Optional[bool] = Field(
        default=None,
        description=(
            "True when eval_label indicates an attack; False for benign/background. "
            "None when label is absent. "
            "EVAL_ONLY."
        ),
    )

    # ─── Validators ───────────────────────────────────────────────────────────

    @field_validator("src_ip", "dst_ip")
    @classmethod
    def validate_ip_address(cls, v: str) -> str:
        """Validate and normalise IPv4/IPv6 address strings."""
        v = v.strip()
        try:
            return str(ipaddress.ip_address(v))
        except ValueError:
            raise ValueError(f"Invalid IP address: {v!r}")

    @field_validator("protocol_name")
    @classmethod
    def validate_protocol_name(cls, v: str) -> str:
        """Normalise protocol name to uppercase."""
        if not v:
            raise ValueError("protocol_name must not be empty")
        upper = v.strip().upper()
        # Allow known names and also numeric strings (e.g. '6' for TCP)
        if upper.isdigit():
            num = int(upper)
            if 0 <= num <= 255:
                # Reverse-lookup to get name; store as name if known
                rev_map = {vv: kk for kk, vv in _PROTOCOL_MAP.items()}
                return rev_map.get(num, upper)
        return upper

    @field_validator("flow_end_ts")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        """Ensure timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            # Treat naive datetimes as UTC (document this assumption)
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("tcp_flags_raw")
    @classmethod
    def validate_tcp_flags(cls, v: Optional[str]) -> Optional[str]:
        """Accept known flag string patterns or None."""
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned or cleaned in ("0", ""):
            return None
        # Allow nfdump flag strings like ".A.", "FSRPAUEW", "......", etc.
        # Anything printable is accepted; log unusual values elsewhere.
        return cleaned

    @model_validator(mode="after")
    def derive_protocol_number(self) -> "CanonicalFlow":
        """Auto-populate protocol_number from protocol_name if not set."""
        if self.protocol_number is None and self.protocol_name:
            self.protocol_number = _PROTOCOL_MAP.get(self.protocol_name.upper())
        return self

    @model_validator(mode="after")
    def validate_ports_for_protocol(self) -> "CanonicalFlow":
        """
        For ICMP and similar, src/dst ports are not meaningful.
        We allow None for any protocol; the validator does not force zeros.
        """
        return self

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def feature_dict(self) -> dict[str, Any]:
        """
        Return only the ELIGIBLE fields as a flat dictionary.

        This is the view that the feature engineering pipeline should use.
        Evaluation labels and metadata are excluded.
        """
        data = self.model_dump()
        return {k: v for k in ELIGIBLE_FEATURE_COLUMNS if (v := data.get(k)) is not None or k in data}

    def to_audit_dict(self) -> dict[str, Any]:
        """Full record including metadata (for DB storage and audit)."""
        return self.model_dump(mode="json")

    @property
    def is_tcp(self) -> bool:
        return self.protocol_name.upper() == "TCP"

    @property
    def bytes_per_packet(self) -> Optional[float]:
        """Mean bytes per packet; None if packet count is zero."""
        if self.fwd_packets > 0:
            return self.fwd_bytes / self.fwd_packets
        return None

    @property
    def packets_per_second(self) -> Optional[float]:
        """Packet rate; None if duration is zero or absent."""
        if self.duration_seconds and self.duration_seconds > 0:
            return self.fwd_packets / self.duration_seconds
        return None

    @property
    def bytes_per_second(self) -> Optional[float]:
        """Byte rate; None if duration is zero or absent."""
        if self.duration_seconds and self.duration_seconds > 0:
            return self.fwd_bytes / self.duration_seconds
        return None


# ─── Ingestion result container ───────────────────────────────────────────────

class IngestionResult(BaseModel):
    """
    Summary of a dataset ingestion run.
    Reports row counts, rejection reasons, and provenance.
    """
    source_file: str
    source_dataset: SourceDataset
    schema_version: str = SCHEMA_VERSION
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    rows_read: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    rows_skipped: int = 0          # e.g. header rows, comment lines

    rejection_reasons: dict[str, int] = Field(default_factory=dict)

    @property
    def acceptance_rate(self) -> Optional[float]:
        if self.rows_read > 0:
            return self.rows_accepted / self.rows_read
        return None

    def record_rejection(self, reason: str) -> None:
        self.rows_rejected += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1

    def finish(self) -> None:
        self.completed_at = datetime.now(timezone.utc)
