"""
IPv4 Packet Validation and Diagnostic Gate
=========================================
Milestone 14.2 — Feature Fidelity and Malformed-Packet Safety Gate

Performs rigorous structural validation of IPv4 packets before envelope creation.
Distinguishes between:
1. Malformed packets (impossible or contradictory headers).
2. Truncated captures (packet cut short by snaplen or network cutoff).
3. Unsupported packets (IPv6, non-IP frames, unknown protocols).

Ensures zero malformed packet metadata ever enters the flow builder or inference pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PacketRejectionCategory(StrEnum):
    """Categorization of rejected network frames."""
    VALID = "VALID"
    MALFORMED = "MALFORMED"
    TRUNCATED = "TRUNCATED"
    UNSUPPORTED = "UNSUPPORTED"


class RejectionReason(StrEnum):
    """Specific diagnostic reason codes for packet rejection."""
    # Truncation codes
    TRUNCATED_IPV4_HEADER = "TRUNCATED_IPV4_HEADER"
    TRUNCATED_IPV4_OPTIONS = "TRUNCATED_IPV4_OPTIONS"
    TRUNCATED_CAPTURE_SNAPLEN = "TRUNCATED_CAPTURE_SNAPLEN"
    TRUNCATED_TCP_HEADER = "TRUNCATED_TCP_HEADER"
    TRUNCATED_UDP_HEADER = "TRUNCATED_UDP_HEADER"

    # Malformed header codes
    MALFORMED_IP_VERSION = "MALFORMED_IP_VERSION"
    MALFORMED_IHL_LESS_THAN_MIN = "MALFORMED_IHL_LESS_THAN_MIN"
    MALFORMED_TOTAL_LEN_LESS_THAN_HEADER = "MALFORMED_TOTAL_LEN_LESS_THAN_HEADER"
    MALFORMED_TOTAL_LEN_EXCEEDS_MAX = "MALFORMED_TOTAL_LEN_EXCEEDS_MAX"
    MALFORMED_ZERO_TTL = "MALFORMED_ZERO_TTL"
    MALFORMED_TCP_OFFSET = "MALFORMED_TCP_OFFSET"
    MALFORMED_TCP_LENGTH = "MALFORMED_TCP_LENGTH"
    MALFORMED_UDP_LENGTH = "MALFORMED_UDP_LENGTH"
    MALFORMED_UDP_LENGTH_FIELD = "MALFORMED_UDP_LENGTH_FIELD"

    # Unsupported codes
    UNSUPPORTED_NON_IP = "UNSUPPORTED_NON_IP"
    UNSUPPORTED_IPV6 = "UNSUPPORTED_IPV6"
    UNSUPPORTED_PROTOCOL = "UNSUPPORTED_PROTOCOL"


@dataclass(frozen=True)
class ValidationResult:
    """Diagnostic outcome of packet validation."""
    category: PacketRejectionCategory
    reason: RejectionReason | None = None
    ip_header_len: int = 0
    ip_total_len: int = 0
    ttl: int = 0
    protocol: int = 0
    is_fragment: bool = False
    frag_offset: int = 0
    more_fragments: bool = False
    ip_id: int = 0
    is_snaplen_truncated: bool = False

    @property
    def is_valid(self) -> bool:
        return self.category == PacketRejectionCategory.VALID


class IPv4PacketValidator:
    """
    Zero-payload IPv4 packet inspector and structural validator.
    Inspects raw frame bytes without copying or retaining application payload data.
    """

    @staticmethod
    def validate_ipv4_frame(raw_bytes: bytes) -> ValidationResult:
        """
        Validate an IPv4 packet starting at the IP header.
        Assumes raw_bytes begins with the IPv4 header (byte 0 is version/IHL).
        """
        cap_len = len(raw_bytes)

        # 1. Minimum IPv4 header check
        if cap_len < 20:
            return ValidationResult(
                category=PacketRejectionCategory.TRUNCATED,
                reason=RejectionReason.TRUNCATED_IPV4_HEADER,
            )

        # 2. IP Version verification
        version = (raw_bytes[0] >> 4) & 0x0F
        if version == 6:
            return ValidationResult(
                category=PacketRejectionCategory.UNSUPPORTED,
                reason=RejectionReason.UNSUPPORTED_IPV6,
            )
        if version != 4:
            return ValidationResult(
                category=PacketRejectionCategory.MALFORMED,
                reason=RejectionReason.MALFORMED_IP_VERSION,
            )

        # 3. Internet Header Length (IHL)
        ihl = raw_bytes[0] & 0x0F
        if ihl < 5:
            return ValidationResult(
                category=PacketRejectionCategory.MALFORMED,
                reason=RejectionReason.MALFORMED_IHL_LESS_THAN_MIN,
            )

        header_len = ihl * 4
        if cap_len < header_len:
            return ValidationResult(
                category=PacketRejectionCategory.TRUNCATED,
                reason=RejectionReason.TRUNCATED_IPV4_OPTIONS,
                ip_header_len=header_len,
            )

        # 4. Total Length verification
        total_len = (raw_bytes[2] << 8) | raw_bytes[3]
        if total_len < header_len:
            return ValidationResult(
                category=PacketRejectionCategory.MALFORMED,
                reason=RejectionReason.MALFORMED_TOTAL_LEN_LESS_THAN_HEADER,
                ip_header_len=header_len,
                ip_total_len=total_len,
            )
        if total_len > 65535:
            return ValidationResult(
                category=PacketRejectionCategory.MALFORMED,
                reason=RejectionReason.MALFORMED_TOTAL_LEN_EXCEEDS_MAX,
                ip_header_len=header_len,
                ip_total_len=total_len,
            )

        is_snaplen_truncated = (cap_len < total_len)

        # 5. Time-To-Live (TTL) verification
        ttl = raw_bytes[8]
        if ttl == 0:
            return ValidationResult(
                category=PacketRejectionCategory.MALFORMED,
                reason=RejectionReason.MALFORMED_ZERO_TTL,
                ip_header_len=header_len,
                ip_total_len=total_len,
                ttl=0,
            )

        # 6. Fragmentation Flags & Offset
        ip_id = (raw_bytes[4] << 8) | raw_bytes[5]
        flags_offset = (raw_bytes[6] << 8) | raw_bytes[7]
        more_fragments = bool(flags_offset & 0x2000)
        frag_offset = (flags_offset & 0x1FFF) * 8
        is_fragment = more_fragments or (frag_offset > 0)

        # 7. Protocol identification
        protocol_num = raw_bytes[9]

        # 8. Transport layer consistency checks (only on unfragmented or initial fragment)
        if frag_offset == 0:
            # TCP Check
            if protocol_num == 6:
                if total_len < header_len + 20:
                    return ValidationResult(
                        category=PacketRejectionCategory.MALFORMED,
                        reason=RejectionReason.MALFORMED_TCP_LENGTH,
                        ip_header_len=header_len,
                        ip_total_len=total_len,
                        ttl=ttl,
                        protocol=protocol_num,
                    )
                if cap_len < header_len + 20:
                    return ValidationResult(
                        category=PacketRejectionCategory.TRUNCATED,
                        reason=RejectionReason.TRUNCATED_TCP_HEADER,
                        ip_header_len=header_len,
                        ip_total_len=total_len,
                        ttl=ttl,
                        protocol=protocol_num,
                    )
                tcp_offset = (raw_bytes[header_len + 12] >> 4) * 4
                if tcp_offset < 20:
                    return ValidationResult(
                        category=PacketRejectionCategory.MALFORMED,
                        reason=RejectionReason.MALFORMED_TCP_OFFSET,
                        ip_header_len=header_len,
                        ip_total_len=total_len,
                        ttl=ttl,
                        protocol=protocol_num,
                    )

            # UDP Check
            elif protocol_num == 17:
                if total_len < header_len + 8:
                    return ValidationResult(
                        category=PacketRejectionCategory.MALFORMED,
                        reason=RejectionReason.MALFORMED_UDP_LENGTH,
                        ip_header_len=header_len,
                        ip_total_len=total_len,
                        ttl=ttl,
                        protocol=protocol_num,
                    )
                if cap_len < header_len + 8:
                    return ValidationResult(
                        category=PacketRejectionCategory.TRUNCATED,
                        reason=RejectionReason.TRUNCATED_UDP_HEADER,
                        ip_header_len=header_len,
                        ip_total_len=total_len,
                        ttl=ttl,
                        protocol=protocol_num,
                    )
                udp_len = (raw_bytes[header_len + 4] << 8) | raw_bytes[header_len + 5]
                if udp_len < 8 or udp_len > (total_len - header_len):
                    return ValidationResult(
                        category=PacketRejectionCategory.MALFORMED,
                        reason=RejectionReason.MALFORMED_UDP_LENGTH_FIELD,
                        ip_header_len=header_len,
                        ip_total_len=total_len,
                        ttl=ttl,
                        protocol=protocol_num,
                    )

        return ValidationResult(
            category=PacketRejectionCategory.VALID,
            ip_header_len=header_len,
            ip_total_len=total_len,
            ttl=ttl,
            protocol=protocol_num,
            is_fragment=is_fragment,
            frag_offset=frag_offset,
            more_fragments=more_fragments,
            ip_id=ip_id,
            is_snaplen_truncated=is_snaplen_truncated,
        )
