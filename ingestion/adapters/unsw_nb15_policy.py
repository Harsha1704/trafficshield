"""
UNSW-NB15 Unidirectional Feature Policy
========================================
Milestone 7 — TrafficShield

Explicit, reviewable directional classification for all 49 fields of the
UNSW-NB15 dataset.

Premise:
TrafficShield operates on unidirectional monitoring links where return (reverse)
traffic is unobservable. Any candidate feature that depends on reverse-direction
packets, bidirectional handshake state, request-response timing, or future
lookahead is strictly classified and excluded from the model feature matrix.

Categories:
1. forward_observable:
   Measurable strictly from the forward (source-to-destination) stream at a
   unidirectional sensor.
2. reverse_direction:
   Requires observing return packets transmitted from destination to source.
   STRICTLY PROHIBITED.
3. bidirectional_or_future_dependent:
   Requires observing both directions (e.g. handshake completion, response body
   length) or future lookahead. STRICTLY PROHIBITED.
4. identifier_or_grouping_only:
   Network identifiers (IPs, record IDs) or timestamps used for ordering,
   windowing, and provenance. EXCLUDED from numeric feature matrices.
5. unknown:
   Uncertain or undocumented fields. Excluded fail-safe until verified.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from features.policy import (
    DataType,
    FeatureAuditResult,
    FieldRole,
    PolicyViolationError,
    get_field_spec,
)


class UNSWFeatureDirectionality(StrEnum):
    """Directionality classification of UNSW-NB15 candidate features."""
    FORWARD_OBSERVABLE = "forward_observable"
    REVERSE_DIRECTION = "reverse_direction"
    BIDIRECTIONAL_OR_FUTURE_DEPENDENT = "bidirectional_or_future_dependent"
    IDENTIFIER_OR_GROUPING_ONLY = "identifier_or_grouping_only"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class UNSWFieldSpec:
    """Detailed contract for a UNSW-NB15 dataset column."""
    index: int
    raw_name: str
    normalized_name: str
    directionality: UNSWFeatureDirectionality
    field_role: FieldRole
    data_type: DataType
    description: str
    rationale: str

    @property
    def is_model_feature(self) -> bool:
        """True only if forward-observable and designated as a model feature."""
        return (
            self.directionality == UNSWFeatureDirectionality.FORWARD_OBSERVABLE
            and self.field_role == FieldRole.FEATURE
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "raw_name": self.raw_name,
            "normalized_name": self.normalized_name,
            "directionality": str(self.directionality),
            "field_role": str(self.field_role),
            "data_type": str(self.data_type),
            "is_model_feature": self.is_model_feature,
            "description": self.description,
            "rationale": self.rationale,
        }


# ─── Complete 49-Field Registry ───────────────────────────────────────────────

UNSW_NB15_SPECS: list[UNSWFieldSpec] = [
    # 1. srcip
    UNSWFieldSpec(
        index=1,
        raw_name="srcip",
        normalized_name="src_ip",
        directionality=UNSWFeatureDirectionality.IDENTIFIER_OR_GROUPING_ONLY,
        field_role=FieldRole.IDENTIFIER,
        data_type=DataType.STRING,
        description="Source IP address",
        rationale="Network entity identifier. Used for entity tracking / state grouping; never a continuous numeric feature.",
    ),
    # 2. sport
    UNSWFieldSpec(
        index=2,
        raw_name="sport",
        normalized_name="src_port",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.METADATA,
        data_type=DataType.NUMERIC,
        description="Source port number",
        rationale="Observed directly in forward transport header. Encoded into well-known / ephemeral categories, not raw scalar magnitude.",
    ),
    # 3. dstip
    UNSWFieldSpec(
        index=3,
        raw_name="dstip",
        normalized_name="dst_ip",
        directionality=UNSWFeatureDirectionality.IDENTIFIER_OR_GROUPING_ONLY,
        field_role=FieldRole.IDENTIFIER,
        data_type=DataType.STRING,
        description="Destination IP address",
        rationale="Network entity identifier. Prohibited from numeric feature matrix.",
    ),
    # 4. dsport
    UNSWFieldSpec(
        index=4,
        raw_name="dsport",
        normalized_name="dst_port",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.METADATA,
        data_type=DataType.NUMERIC,
        description="Destination port number",
        rationale="Observed directly in forward transport header. Encoded into service port categories / well-known indicators.",
    ),
    # 5. proto
    UNSWFieldSpec(
        index=5,
        raw_name="proto",
        normalized_name="protocol_name",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.METADATA,
        data_type=DataType.CATEGORICAL,
        description="Transaction protocol",
        rationale="Observed in forward IP header protocol field. Categorical indicator.",
    ),
    # 6. state
    UNSWFieldSpec(
        index=6,
        raw_name="state",
        normalized_name="state",
        directionality=UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.CATEGORICAL,
        description="Indicates to the state and its dependent protocol (ACC, CLO, CON, FIN, etc.)",
        rationale="ARGUS derives connection states (FIN, CON, CLO) by observing bidirectional TCP handshakes and teardowns across both link directions.",
    ),
    # 7. dur
    UNSWFieldSpec(
        index=7,
        raw_name="dur",
        normalized_name="duration_seconds",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Record total duration",
        rationale="Elapsed time from first observed forward packet to last observed forward packet at the monitoring link.",
    ),
    # 8. sbytes
    UNSWFieldSpec(
        index=8,
        raw_name="sbytes",
        normalized_name="fwd_bytes",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Source to destination transaction bytes",
        rationale="Cumulative forward byte volume observable from packet length headers.",
    ),
    # 9. dbytes
    UNSWFieldSpec(
        index=9,
        raw_name="dbytes",
        normalized_name="bwd_bytes",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Destination to source transaction bytes",
        rationale="Reverse-direction byte count. Requires observing return traffic. Strictly prohibited.",
    ),
    # 10. sttl
    UNSWFieldSpec(
        index=10,
        raw_name="sttl",
        normalized_name="sttl",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Source to destination time to live value",
        rationale="Observed directly in forward IP header TTL field.",
    ),
    # 11. dttl
    UNSWFieldSpec(
        index=11,
        raw_name="dttl",
        normalized_name="dttl",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Destination to source time to live value",
        rationale="Reverse IP header TTL. Requires observing return packets. Strictly prohibited.",
    ),
    # 12. sloss
    UNSWFieldSpec(
        index=12,
        raw_name="sloss",
        normalized_name="sloss",
        directionality=UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Source packets retransmitted or dropped",
        rationale="In ARGUS flow monitors, drop estimation often relies on reverse SACK or response acknowledgment gaps. Excluded fail-safe.",
    ),
    # 13. dloss
    UNSWFieldSpec(
        index=13,
        raw_name="dloss",
        normalized_name="dloss",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Destination packets retransmitted or dropped",
        rationale="Reverse-direction packet loss. Requires observing return traffic. Strictly prohibited.",
    ),
    # 14. service
    UNSWFieldSpec(
        index=14,
        raw_name="service",
        normalized_name="service",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.METADATA,
        data_type=DataType.CATEGORICAL,
        description="Application service (http, ftp, smtp, ssh, dns, etc.)",
        rationale="Derived from destination port and forward packet payload signature.",
    ),
    # 15. Sload
    UNSWFieldSpec(
        index=15,
        raw_name="Sload",
        normalized_name="sload",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Source bits per second",
        rationale="Forward transmission rate (8 * sbytes / dur). Fully observable from forward stream.",
    ),
    # 16. Dload
    UNSWFieldSpec(
        index=16,
        raw_name="Dload",
        normalized_name="dload",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Destination bits per second",
        rationale="Reverse-direction transmission rate. Requires return bytes. Strictly prohibited.",
    ),
    # 17. Spkts
    UNSWFieldSpec(
        index=17,
        raw_name="Spkts",
        normalized_name="fwd_packets",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Source to destination packet count",
        rationale="Cumulative forward packet count observable at sensor interface.",
    ),
    # 18. Dpkts
    UNSWFieldSpec(
        index=18,
        raw_name="Dpkts",
        normalized_name="bwd_packets",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Destination to source packet count",
        rationale="Reverse packet count. Requires observing return traffic. Strictly prohibited.",
    ),
    # 19. swin
    UNSWFieldSpec(
        index=19,
        raw_name="swin",
        normalized_name="swin",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Source TCP window advertisement value",
        rationale="Observed in forward TCP header window field.",
    ),
    # 20. dwin
    UNSWFieldSpec(
        index=20,
        raw_name="dwin",
        normalized_name="dwin",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Destination TCP window advertisement value",
        rationale="Observed in reverse TCP header window field. Strictly prohibited.",
    ),
    # 21. stcpb
    UNSWFieldSpec(
        index=21,
        raw_name="stcpb",
        normalized_name="stcpb",
        directionality=UNSWFeatureDirectionality.IDENTIFIER_OR_GROUPING_ONLY,
        field_role=FieldRole.IDENTIFIER,
        data_type=DataType.NUMERIC,
        description="Source TCP base sequence number",
        rationale="Random 32-bit transaction identifier without physical continuous magnitude.",
    ),
    # 22. dtcpb
    UNSWFieldSpec(
        index=22,
        raw_name="dtcpb",
        normalized_name="dtcpb",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Destination TCP base sequence number",
        rationale="Destination sequence number from reverse TCP header. Strictly prohibited.",
    ),
    # 23. smeansz
    UNSWFieldSpec(
        index=23,
        raw_name="smeansz",
        normalized_name="smeansz",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Mean of the flow packet size transmitted by the src",
        rationale="Mean forward packet size (sbytes / Spkts). Observable in forward direction.",
    ),
    # 24. dmeansz
    UNSWFieldSpec(
        index=24,
        raw_name="dmeansz",
        normalized_name="dmeansz",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Mean of the flow packet size transmitted by the dst",
        rationale="Mean reverse packet size. Requires return packets. Strictly prohibited.",
    ),
    # 25. trans_depth
    UNSWFieldSpec(
        index=25,
        raw_name="trans_depth",
        normalized_name="trans_depth",
        directionality=UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Pipelined depth into HTTP request/response transaction",
        rationale="Requires tracking request-response pairs across both link directions.",
    ),
    # 26. res_bdy_len
    UNSWFieldSpec(
        index=26,
        raw_name="res_bdy_len",
        normalized_name="res_bdy_len",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Actual uncompressed content size of server HTTP response body",
        rationale="Server response body transferred from destination back to source. Strictly prohibited.",
    ),
    # 27. Sjit
    UNSWFieldSpec(
        index=27,
        raw_name="Sjit",
        normalized_name="sjit",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Source jitter (mSec)",
        rationale="Variation in inter-packet arrival times of forward packets.",
    ),
    # 28. Djit
    UNSWFieldSpec(
        index=28,
        raw_name="Djit",
        normalized_name="djit",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Destination jitter (mSec)",
        rationale="Variation in inter-packet arrival times of return packets. Strictly prohibited.",
    ),
    # 29. Stime
    UNSWFieldSpec(
        index=29,
        raw_name="Stime",
        normalized_name="flow_start_ts",
        directionality=UNSWFeatureDirectionality.IDENTIFIER_OR_GROUPING_ONLY,
        field_role=FieldRole.TIMESTAMP,
        data_type=DataType.DATETIME,
        description="Record start time (epoch seconds)",
        rationale="Timestamp used for ordering and windowing; excluded from numeric feature matrix.",
    ),
    # 30. Ltime
    UNSWFieldSpec(
        index=30,
        raw_name="Ltime",
        normalized_name="flow_end_ts",
        directionality=UNSWFeatureDirectionality.IDENTIFIER_OR_GROUPING_ONLY,
        field_role=FieldRole.TIMESTAMP,
        data_type=DataType.DATETIME,
        description="Record last time (epoch seconds)",
        rationale="Primary chronological ordering key for flow completion. Excluded from numeric features.",
    ),
    # 31. Sintpkt
    UNSWFieldSpec(
        index=31,
        raw_name="Sintpkt",
        normalized_name="sintpkt",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Source interpacket arrival time (mSec)",
        rationale="Time elapsed between consecutive forward packets. Fully forward observable.",
    ),
    # 32. Dintpkt
    UNSWFieldSpec(
        index=32,
        raw_name="Dintpkt",
        normalized_name="dintpkt",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Destination interpacket arrival time (mSec)",
        rationale="Time elapsed between return packets. Requires reverse observation. Strictly prohibited.",
    ),
    # 33. tcprtt
    UNSWFieldSpec(
        index=33,
        raw_name="tcprtt",
        normalized_name="tcprtt",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="TCP connection setup round-trip time (synack + ackdat)",
        rationale="Explicit round-trip measurement requiring reverse SYN-ACK packet. Strictly prohibited.",
    ),
    # 34. synack
    UNSWFieldSpec(
        index=34,
        raw_name="synack",
        normalized_name="synack",
        directionality=UNSWFeatureDirectionality.REVERSE_DIRECTION,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="TCP connection setup time between SYN and SYN-ACK",
        rationale="SYN-ACK travels in return direction. Strictly prohibited.",
    ),
    # 35. ackdat
    UNSWFieldSpec(
        index=35,
        raw_name="ackdat",
        normalized_name="ackdat",
        directionality=UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="TCP connection setup time between SYN-ACK and ACK",
        rationale="Requires knowing reverse SYN-ACK arrival time. Strictly prohibited.",
    ),
    # 36. is_sm_ips_ports
    UNSWFieldSpec(
        index=36,
        raw_name="is_sm_ips_ports",
        normalized_name="is_sm_ips_ports",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.BOOLEAN,
        description="Binary indicator: 1 if srcip==dstip and sport==dsport, else 0",
        rationale="Land attack indicator observable directly from forward packet IP/port headers.",
    ),
    # 37. ct_state_ttl
    UNSWFieldSpec(
        index=37,
        raw_name="ct_state_ttl",
        normalized_name="ct_state_ttl",
        directionality=UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.NUMERIC,
        description="Count of connections for state according to TTL range",
        rationale="Directly incorporates connection state which requires bidirectional tracking.",
    ),
    # 38. ct_flw_http_mthd
    UNSWFieldSpec(
        index=38,
        raw_name="ct_flw_http_mthd",
        normalized_name="ct_flw_http_mthd",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Number of flows with HTTP methods (GET/POST)",
        rationale="Client HTTP request methods are transmitted in the forward direction.",
    ),
    # 39. is_ftp_login
    UNSWFieldSpec(
        index=39,
        raw_name="is_ftp_login",
        normalized_name="is_ftp_login",
        directionality=UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT,
        field_role=FieldRole.FORBIDDEN,
        data_type=DataType.BOOLEAN,
        description="Binary: 1 if FTP session accessed by user and password",
        rationale="Verifying authenticated session status requires observing server reply code (230 vs 530).",
    ),
    # 40. ct_ftp_cmd
    UNSWFieldSpec(
        index=40,
        raw_name="ct_ftp_cmd",
        normalized_name="ct_ftp_cmd",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Count of flows with command in FTP session",
        rationale="Client FTP command invocations travel in the forward request stream.",
    ),
    # 41. ct_srv_src
    UNSWFieldSpec(
        index=41,
        raw_name="ct_srv_src",
        normalized_name="ct_srv_src",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Connections with same service and source address in recent 100 connections",
        rationale="Local sensor window aggregate over forward stream source addresses and requested services.",
    ),
    # 42. ct_srv_dst
    UNSWFieldSpec(
        index=42,
        raw_name="ct_srv_dst",
        normalized_name="ct_srv_dst",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Connections with same service and destination address in recent 100 connections",
        rationale="Local sensor window aggregate over forward destination addresses and requested services.",
    ),
    # 43. ct_dst_ltm
    UNSWFieldSpec(
        index=43,
        raw_name="ct_dst_ltm",
        normalized_name="ct_dst_ltm",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Connections of same destination address in recent 100 connections",
        rationale="Local forward stream fan-in indicator.",
    ),
    # 44. ct_src_ ltm
    UNSWFieldSpec(
        index=44,
        raw_name="ct_src_ ltm",
        normalized_name="ct_src_ltm",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Connections of same source address in recent 100 connections",
        rationale="Local forward stream fan-out indicator.",
    ),
    # 45. ct_src_dport_ltm
    UNSWFieldSpec(
        index=45,
        raw_name="ct_src_dport_ltm",
        normalized_name="ct_src_dport_ltm",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Connections of same source address and destination port in recent 100 connections",
        rationale="Forward stream port-scanning / horizontal reconnaissance indicator.",
    ),
    # 46. ct_dst_sport_ltm
    UNSWFieldSpec(
        index=46,
        raw_name="ct_dst_sport_ltm",
        normalized_name="ct_dst_sport_ltm",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Connections of same destination address and source port in recent 100 connections",
        rationale="Forward stream vertical reconnaissance indicator.",
    ),
    # 47. ct_dst_src_ltm
    UNSWFieldSpec(
        index=47,
        raw_name="ct_dst_src_ltm",
        normalized_name="ct_dst_src_ltm",
        directionality=UNSWFeatureDirectionality.FORWARD_OBSERVABLE,
        field_role=FieldRole.FEATURE,
        data_type=DataType.NUMERIC,
        description="Connections of same source and destination address in recent 100 connections",
        rationale="Forward stream host-pair connection density indicator.",
    ),
    # 48. attack_cat
    UNSWFieldSpec(
        index=48,
        raw_name="attack_cat",
        normalized_name="eval_label",
        directionality=UNSWFeatureDirectionality.IDENTIFIER_OR_GROUPING_ONLY,
        field_role=FieldRole.LABEL,
        data_type=DataType.STRING,
        description="Name of attack category",
        rationale="Ground-truth attack annotation. Exclusively for post-prediction evaluation. Prohibited from training/inference.",
    ),
    # 49. Label
    UNSWFieldSpec(
        index=49,
        raw_name="Label",
        normalized_name="is_attack",
        directionality=UNSWFeatureDirectionality.IDENTIFIER_OR_GROUPING_ONLY,
        field_role=FieldRole.LABEL,
        data_type=DataType.BOOLEAN,
        description="Binary attack indicator (0 for normal, 1 for attack)",
        rationale="Ground-truth binary label. Exclusively for post-prediction evaluation. Prohibited from model input.",
    ),
]

# Lookup tables
_BY_RAW_NAME: dict[str, UNSWFieldSpec] = {s.raw_name: s for s in UNSW_NB15_SPECS}
_BY_NORMALIZED_NAME: dict[str, UNSWFieldSpec] = {s.normalized_name: s for s in UNSW_NB15_SPECS}
_BY_INDEX: dict[int, UNSWFieldSpec] = {s.index: s for s in UNSW_NB15_SPECS}


def get_unsw_spec_by_raw(name: str) -> UNSWFieldSpec | None:
    """Look up specification by exact raw CSV column name."""
    clean = name.strip()
    if clean in _BY_RAW_NAME:
        return _BY_RAW_NAME[clean]
    # Check lowercase / normalized fallback
    for s in UNSW_NB15_SPECS:
        if s.raw_name.lower() == clean.lower() or s.normalized_name.lower() == clean.lower():
            return s
    return None


def get_unsw_spec_by_normalized(name: str) -> UNSWFieldSpec | None:
    """Look up specification by normalized column name."""
    clean = name.strip().lower()
    return _BY_NORMALIZED_NAME.get(clean)


def get_eligible_unsw_model_features() -> list[str]:
    """Return the list of normalized feature names eligible for model inputs."""
    return [s.normalized_name for s in UNSW_NB15_SPECS if s.is_model_feature]


def get_prohibited_unsw_features() -> list[str]:
    """Return all raw and normalized column names that are strictly prohibited."""
    prohibited = set()
    for s in UNSW_NB15_SPECS:
        if s.directionality in (
            UNSWFeatureDirectionality.REVERSE_DIRECTION,
            UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT,
            UNSWFeatureDirectionality.UNKNOWN,
        ):
            prohibited.add(s.raw_name)
            prohibited.add(s.normalized_name)
    return sorted(prohibited)


def audit_unsw_feature_columns(columns: list[str]) -> FeatureAuditResult:
    """
    Audit an incoming column list against the UNSW-NB15 unidirectional policy.

    Raises PolicyViolationError if reverse, bidirectional, unknown, or label
    columns are included.
    """
    eligible: list[str] = []
    excluded: dict[str, str] = {}
    forbidden: list[str] = []
    labels: list[str] = []

    for col in columns:
        spec = get_unsw_spec_by_normalized(col) or get_unsw_spec_by_raw(col)
        if spec is None:
            # Check if it is a registered canonical TrafficShield feature (e.g. packet_rate)
            canon_spec = get_field_spec(col)
            if canon_spec is not None:
                if canon_spec.role == FieldRole.FEATURE:
                    eligible.append(col)
                    continue
                elif canon_spec.role == FieldRole.FORBIDDEN:
                    forbidden.append(f"{col} (forbidden: {canon_spec.rationale})")
                    continue
                elif canon_spec.role == FieldRole.LABEL:
                    labels.append(f"{col} (ground-truth evaluation target)")
                    continue

            excluded[col] = f"Unknown column '{col}' not in verified UNSW-NB15 schema"
            forbidden.append(f"{col} (unknown candidate)")
            continue

        if spec.directionality == UNSWFeatureDirectionality.REVERSE_DIRECTION:
            forbidden.append(f"{col} (reverse_direction: {spec.rationale})")
        elif spec.directionality == UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT:
            forbidden.append(f"{col} (bidirectional_or_future_dependent: {spec.rationale})")
        elif spec.field_role == FieldRole.LABEL:
            labels.append(f"{col} (ground-truth evaluation target)")
        elif spec.is_model_feature:
            eligible.append(col)
        else:
            excluded[col] = f"{spec.directionality}: {spec.rationale}"

    if forbidden or labels:
        err_parts = []
        if forbidden:
            err_parts.append(f"Forbidden directional columns: {forbidden}")
        if labels:
            err_parts.append(f"Evaluation target labels in features: {labels}")
        raise PolicyViolationError("; ".join(err_parts))

    return FeatureAuditResult(
        eligible_features=eligible,
        excluded_columns=excluded,
        forbidden_violations=[],
        label_violations=[],
    )


def export_unsw_policy_json(out_path: Path) -> Path:
    """Export the complete policy as a structured machine-readable JSON artifact."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0",
        "dataset": "UNSW-NB15",
        "total_fields": len(UNSW_NB15_SPECS),
        "eligible_model_features": get_eligible_unsw_model_features(),
        "prohibited_features": get_prohibited_unsw_features(),
        "specs": [s.to_dict() for s in UNSW_NB15_SPECS],
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def export_unsw_policy_markdown(out_path: Path) -> Path:
    """Export the feature policy as a human-readable Markdown documentation table."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# TrafficShield — UNSW-NB15 Unidirectional Feature Eligibility Policy",
        "",
        "Version: 1.0  ",
        "Dataset: UNSW-NB15 Network Intrusion Dataset  ",
        "Premise: Unidirectional Link Monitoring (Zero Reverse / Bidirectional Leakage)",
        "",
        "## Summary of Classification",
        "",
        "| Category | Count | Status | Description |",
        "|---|---|---|---|",
        f"| `forward_observable` (numeric) | {sum(1 for s in UNSW_NB15_SPECS if s.is_model_feature)} | ✅ Eligible | Observable exclusively in forward packet stream |",
        f"| `forward_observable` (metadata) | {sum(1 for s in UNSW_NB15_SPECS if s.directionality == UNSWFeatureDirectionality.FORWARD_OBSERVABLE and not s.is_model_feature)} | ℹ️ Encoded | Ports/Protocol headers (categorical encoding only) |",
        f"| `reverse_direction` | {sum(1 for s in UNSW_NB15_SPECS if s.directionality == UNSWFeatureDirectionality.REVERSE_DIRECTION)} | ❌ Prohibited | Requires unobserved return traffic |",
        f"| `bidirectional_or_future_dependent` | {sum(1 for s in UNSW_NB15_SPECS if s.directionality == UNSWFeatureDirectionality.BIDIRECTIONAL_OR_FUTURE_DEPENDENT)} | ❌ Prohibited | Handshake state, RTT, or response pairing |",
        f"| `identifier_or_grouping_only` | {sum(1 for s in UNSW_NB15_SPECS if s.directionality == UNSWFeatureDirectionality.IDENTIFIER_OR_GROUPING_ONLY)} | ⛔ Excluded | IPs, timestamps, and ground-truth evaluation labels |",
        "",
        "---",
        "",
        "## Detailed Column-by-Column Policy",
        "",
        "| # | Raw Name | Normalized | Category | Role | Model Feature? | Rationale |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in UNSW_NB15_SPECS:
        status = "✅ YES" if s.is_model_feature else "❌ NO"
        lines.append(
            f"| {s.index} | `{s.raw_name}` | `{s.normalized_name}` | `{s.directionality}` | `{s.field_role}` | {status} | {s.rationale} |"
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
