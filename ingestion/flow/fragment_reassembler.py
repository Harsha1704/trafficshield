"""
Bounded IPv4 Fragment Reassembler
=================================
Milestone 14.2 — Feature Fidelity and Malformed-Packet Safety Gate

Statefully collects and reassembles fragmented IPv4 datagrams with:
- Strict resource bounds (max active datagrams, max datagram size).
- Configurable expiration timeout.
- Out-of-order and duplicate slice handling.
- Zero fabrication: incomplete/expired fragments are cleanly dropped from inference.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("fragment_reassembler")


@dataclass
class FragmentedDatagramState:
    """Accumulates fragmented slices for a single IPv4 datagram."""
    key: tuple[str, str, int, int]  # (src_ip, dst_ip, ip_id, protocol)
    header_bytes: bytes            # Initial IPv4 header from offset 0
    first_seen: float
    last_seen: float
    total_payload_expected: int | None = None  # Determined when MF=0 is received
    received_slices: list[tuple[int, bytes]] = field(default_factory=list)  # (offset, payload)

    def add_slice(self, offset: int, payload: bytes, is_last: bool) -> None:
        """Incorporate a fragment payload slice."""
        self.last_seen = time.time()
        if is_last:
            self.total_payload_expected = offset + len(payload)

        # Insert slice while ignoring exact duplicate offsets
        if not any(o == offset and len(p) == len(payload) for o, p in self.received_slices):
            self.received_slices.append((offset, payload))
            self.received_slices.sort(key=lambda x: x[0])

    def is_complete(self) -> bool:
        """Check if all contiguous byte ranges from 0 to total_payload_expected exist."""
        if self.total_payload_expected is None or not self.received_slices:
            return False

        current_offset = 0
        for off, payload in self.received_slices:
            if off > current_offset:
                # Hole in byte range
                return False
            slice_end = off + len(payload)
            if slice_end > current_offset:
                current_offset = slice_end

        return current_offset >= self.total_payload_expected

    def build_reassembled_bytes(self) -> bytes:
        """Construct the complete IPv4 datagram bytes with contiguous payload."""
        if not self.is_complete() or self.total_payload_expected is None:
            raise ValueError("Cannot build reassembled bytes from incomplete fragment state")

        full_payload = bytearray(self.total_payload_expected)
        for off, payload in self.received_slices:
            end = off + len(payload)
            if end <= self.total_payload_expected:
                full_payload[off:end] = payload

        # Update header total length and clear MF/offset flags
        hdr = bytearray(self.header_bytes)
        hdr_len = len(hdr)
        total_len = hdr_len + len(full_payload)
        hdr[2] = (total_len >> 8) & 0xFF
        hdr[3] = total_len & 0xFF
        # Clear Flags (MF=0) and Fragment Offset (0)
        hdr[6] = hdr[6] & 0x40  # Preserve DF (bit 1), clear MF (bit 2) and high 5 bits of offset
        hdr[7] = 0x00           # Clear low 8 bits of offset

        return bytes(hdr + full_payload)


class BoundedFragmentReassembler:
    """
    LRU-bounded in-memory fragment reassembler.
    Prevents memory exhaustion attacks (e.g. fragment buffer flooding) while safely
    reconstructing legitimate fragmented flows.
    """

    def __init__(
        self,
        max_in_flight: int = 500,
        timeout_seconds: float = 3.0,
        max_reassembled_bytes: int = 65535,
    ) -> None:
        self.max_in_flight = max_in_flight
        self.timeout_seconds = timeout_seconds
        self.max_reassembled_bytes = max_reassembled_bytes

        self.in_flight: dict[tuple[str, str, int, int], FragmentedDatagramState] = {}
        self.metrics = {
            "fragments_received": 0,
            "datagrams_reassembled": 0,
            "dropped_incomplete": 0,
            "dropped_timeout": 0,
            "dropped_capacity": 0,
            "dropped_oversize": 0,
        }

    def process_fragment(
        self,
        src_ip: str,
        dst_ip: str,
        ip_id: int,
        protocol: int,
        frag_offset: int,
        more_fragments: bool,
        header_bytes: bytes,
        payload_bytes: bytes,
    ) -> bytes | None:
        """
        Process a fragmented IPv4 packet.
        Returns complete reassembled IPv4 bytes if this fragment completes a datagram;
        otherwise returns None.
        """
        self.metrics["fragments_received"] += 1
        now = time.time()
        self._purge_stale(now)

        key = (src_ip, dst_ip, ip_id, protocol)

        # Enforce maximum datagram size bounds
        if frag_offset + len(payload_bytes) > self.max_reassembled_bytes:
            logger.warning("Fragment exceeded maximum allowed datagram size (%d > %d)", frag_offset + len(payload_bytes), self.max_reassembled_bytes)
            self.metrics["dropped_oversize"] += 1
            if key in self.in_flight:
                del self.in_flight[key]
            return None

        # Check in-flight capacity
        if key not in self.in_flight:
            if len(self.in_flight) >= self.max_in_flight:
                # Evict oldest in-flight datagram
                oldest_key = min(self.in_flight.keys(), key=lambda k: self.in_flight[k].first_seen)
                del self.in_flight[oldest_key]
                self.metrics["dropped_capacity"] += 1
                self.metrics["dropped_incomplete"] += 1

            # Only initialize if we have the header (frag_offset == 0) or create placeholder
            state = FragmentedDatagramState(
                key=key,
                header_bytes=header_bytes if frag_offset == 0 else b"",
                first_seen=now,
                last_seen=now,
            )
            self.in_flight[key] = state

        state = self.in_flight[key]
        if frag_offset == 0 and not state.header_bytes:
            state.header_bytes = header_bytes

        state.add_slice(offset=frag_offset, payload=payload_bytes, is_last=not more_fragments)

        # Check if complete
        if state.header_bytes and state.is_complete():
            reassembled = state.build_reassembled_bytes()
            del self.in_flight[key]
            self.metrics["datagrams_reassembled"] += 1
            return reassembled

        return None

    def _purge_stale(self, now: float) -> None:
        """Drop fragment buffers that have exceeded timeout_seconds."""
        stale_keys = [
            k for k, state in self.in_flight.items()
            if (now - state.first_seen) > self.timeout_seconds
        ]
        for k in stale_keys:
            del self.in_flight[k]
            self.metrics["dropped_timeout"] += 1
            self.metrics["dropped_incomplete"] += 1

    def get_metrics(self) -> dict[str, int]:
        """Return diagnostic fragment handling metrics."""
        return dict(self.metrics)
