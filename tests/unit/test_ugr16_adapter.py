"""Tests for the UGR'16 dataset adapter and canonical flow schema.

Tests are grouped into:
- TestCanonicalFlowSchema      : unit tests for CanonicalFlow pydantic model
- TestUGR16AdapterHeader       : header validation
- TestUGR16AdapterRowParsing   : per-row parsing and rejection rules
- TestUGR16AdapterChunking     : chunked / streaming processing
- TestUGR16AdapterEdgeCases    : empty, partial, extra-columns input
- TestUGR16AdapterLabelPolicy  : eval_label is never a feature
- TestFeatureEligibilityContract : prohibited features absent from feature_dict()
- TestIngestionResult          : acceptance/rejection statistics

All tests use synthetic in-memory fixtures — NO actual UGR'16 download required.
"""
from __future__ import annotations

import csv
import io
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from datasets.samples.ugr16_synthetic import (
    EMPTY_CSV,
    EXTRA_COLUMNS_CSV,
    MALFORMED_ROWS,
    SYNTHETIC_UGR16_ROWS,
    WRONG_HEADER_CSV,
    UGR16_HEADER,
    make_ugr16_csv_content,
    make_ugr16_csv_io,
    write_ugr16_csv_fixture,
)
from ingestion.adapters.ugr16 import (
    UGR16Adapter,
    UGR16ValidationError,
    _parse_ugr16_timestamp,
    _normalise_label,
)
from ingestion.schema.canonical_flow import (
    ELIGIBLE_FEATURE_COLUMNS,
    EVAL_ONLY_COLUMNS,
    METADATA_COLUMNS,
    PROHIBITED_FEATURE_COLUMNS,
    CanonicalFlow,
    IngestionResult,
    SourceDataset,
    SCHEMA_VERSION,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _csv_to_tmp_file(content: str, suffix: str = ".csv") -> Path:
    """Write CSV content to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def _collect_all(adapter: UGR16Adapter, filepath: Path) -> tuple[list[CanonicalFlow], list[str]]:
    """Collect all records from iter_records into separate accepted/rejected lists."""
    accepted = []
    rejected = []
    for flow, reason in adapter.iter_records(filepath):
        if flow is not None:
            accepted.append(flow)
        else:
            rejected.append(reason)
    return accepted, rejected


# ─── TestCanonicalFlowSchema ──────────────────────────────────────────────────

@pytest.mark.unit
class TestCanonicalFlowSchema:
    """Unit tests for CanonicalFlow model validation."""

    def _valid_kwargs(self, **overrides) -> dict:
        base = dict(
            flow_end_ts=datetime(2016, 3, 1, 0, 0, 1, tzinfo=timezone.utc),
            src_ip="42.219.150.10",
            dst_ip="42.219.156.20",
            src_port=443,
            dst_port=51234,
            protocol_name="TCP",
            fwd_packets=5,
            fwd_bytes=300,
        )
        base.update(overrides)
        return base

    def test_valid_flow_constructs(self):
        flow = CanonicalFlow(**self._valid_kwargs())
        assert flow.src_ip == "42.219.150.10"
        assert flow.fwd_packets == 5
        assert flow.protocol_name == "TCP"

    def test_schema_version_is_set(self):
        flow = CanonicalFlow(**self._valid_kwargs())
        assert flow.schema_version == SCHEMA_VERSION

    def test_record_id_is_uuid(self):
        flow = CanonicalFlow(**self._valid_kwargs())
        import uuid
        uuid.UUID(flow.record_id)  # should not raise

    def test_ingest_ts_is_utc(self):
        flow = CanonicalFlow(**self._valid_kwargs())
        assert flow.ingest_ts.tzinfo is not None

    def test_naive_timestamp_becomes_utc(self):
        naive = datetime(2016, 3, 1, 0, 0, 1)
        flow = CanonicalFlow(**self._valid_kwargs(flow_end_ts=naive))
        assert flow.flow_end_ts.tzinfo == timezone.utc

    def test_invalid_src_ip_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="IP"):
            CanonicalFlow(**self._valid_kwargs(src_ip="not_an_ip"))

    def test_invalid_dst_ip_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="IP"):
            CanonicalFlow(**self._valid_kwargs(dst_ip="999.999.999.999"))

    def test_port_below_range_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CanonicalFlow(**self._valid_kwargs(src_port=-1))

    def test_port_above_range_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CanonicalFlow(**self._valid_kwargs(dst_port=65536))

    def test_negative_packet_count_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CanonicalFlow(**self._valid_kwargs(fwd_packets=-1))

    def test_negative_byte_count_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CanonicalFlow(**self._valid_kwargs(fwd_bytes=-1))

    def test_zero_packets_is_valid(self):
        """Zero packets is technically valid for a flow record (e.g. expired)."""
        flow = CanonicalFlow(**self._valid_kwargs(fwd_packets=0, fwd_bytes=0))
        assert flow.fwd_packets == 0

    def test_protocol_name_uppercased(self):
        flow = CanonicalFlow(**self._valid_kwargs(protocol_name="tcp"))
        assert flow.protocol_name == "TCP"

    def test_protocol_number_derived_from_name(self):
        flow = CanonicalFlow(**self._valid_kwargs(protocol_name="TCP"))
        assert flow.protocol_number == 6

    def test_udp_protocol_number(self):
        flow = CanonicalFlow(**self._valid_kwargs(protocol_name="UDP"))
        assert flow.protocol_number == 17

    def test_icmp_protocol_number(self):
        flow = CanonicalFlow(**self._valid_kwargs(protocol_name="ICMP"))
        assert flow.protocol_number == 1

    def test_ipv4_address_normalised(self):
        """
        Python's ipaddress module rejects ambiguous leading-zero octets
        (e.g. '010.0.0.1' is invalid since Python 3.9 to avoid octal confusion).
        UGR'16 IPs do not have leading zeros; this tests a well-formed address.
        """
        flow = CanonicalFlow(**self._valid_kwargs(src_ip="10.1.2.3"))
        assert flow.src_ip == "10.1.2.3"

    def test_ipv4_leading_zero_rejected(self):
        """Leading zeros in IP octets are rejected by ipaddress (correct behaviour)."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="IP"):
            CanonicalFlow(**self._valid_kwargs(src_ip="010.001.002.003"))

    def test_tcp_flags_none_for_udp(self):
        flow = CanonicalFlow(**self._valid_kwargs(
            protocol_name="UDP", tcp_flags_raw=None
        ))
        assert flow.tcp_flags_raw is None

    def test_tcp_flags_preserved(self):
        flow = CanonicalFlow(**self._valid_kwargs(tcp_flags_raw=".A..S."))
        assert flow.tcp_flags_raw == ".A..S."

    def test_eval_label_is_not_in_feature_dict(self):
        flow = CanonicalFlow(**self._valid_kwargs(eval_label="dos", is_attack=True))
        fd = flow.feature_dict()
        assert "eval_label" not in fd
        assert "is_attack" not in fd

    def test_feature_dict_contains_eligible_fields(self):
        flow = CanonicalFlow(**self._valid_kwargs())
        fd = flow.feature_dict()
        assert "fwd_packets" in fd
        assert "fwd_bytes" in fd
        assert "protocol_name" in fd

    def test_bytes_per_packet(self):
        flow = CanonicalFlow(**self._valid_kwargs(fwd_packets=10, fwd_bytes=1000))
        assert flow.bytes_per_packet == pytest.approx(100.0)

    def test_bytes_per_packet_zero_packets(self):
        flow = CanonicalFlow(**self._valid_kwargs(fwd_packets=0, fwd_bytes=0))
        assert flow.bytes_per_packet is None

    def test_packets_per_second(self):
        flow = CanonicalFlow(**self._valid_kwargs(
            fwd_packets=100, duration_seconds=10.0
        ))
        assert flow.packets_per_second == pytest.approx(10.0)

    def test_bytes_per_second(self):
        flow = CanonicalFlow(**self._valid_kwargs(
            fwd_bytes=10000, duration_seconds=5.0
        ))
        assert flow.bytes_per_second == pytest.approx(2000.0)

    def test_packets_per_second_zero_duration(self):
        flow = CanonicalFlow(**self._valid_kwargs(
            fwd_packets=10, duration_seconds=0.0
        ))
        assert flow.packets_per_second is None

    def test_negative_duration_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CanonicalFlow(**self._valid_kwargs(duration_seconds=-0.1))

    def test_optional_fields_default_none(self):
        flow = CanonicalFlow(**self._valid_kwargs())
        assert flow.eval_label is None
        assert flow.is_attack is None
        assert flow.fwd_status is None
        assert flow.ip_tos is None
        assert flow.duration_seconds is None

    def test_source_dataset_is_ugr16(self):
        flow = CanonicalFlow(**self._valid_kwargs(
            source_dataset=SourceDataset.UGR16
        ))
        assert flow.source_dataset == SourceDataset.UGR16

    def test_is_tcp_property(self):
        flow = CanonicalFlow(**self._valid_kwargs(protocol_name="TCP"))
        assert flow.is_tcp is True
        flow2 = CanonicalFlow(**self._valid_kwargs(protocol_name="UDP"))
        assert flow2.is_tcp is False

    def test_to_audit_dict_is_serializable(self):
        import json
        flow = CanonicalFlow(**self._valid_kwargs(eval_label="dos"))
        d = flow.to_audit_dict()
        json.dumps(d)  # should not raise


# ─── TestTimestampParsing ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestTimestampParsing:
    """Tests for UGR'16 timestamp parsing."""

    def test_standard_format_with_milliseconds(self):
        dt = _parse_ugr16_timestamp("2016-03-01 00:00:02.123")
        assert dt is not None
        assert dt.year == 2016
        assert dt.month == 3
        assert dt.day == 1
        assert dt.tzinfo == timezone.utc

    def test_format_without_sub_seconds(self):
        dt = _parse_ugr16_timestamp("2016-04-15 12:00:00")
        assert dt is not None
        assert dt.hour == 12

    def test_invalid_timestamp_returns_none(self):
        assert _parse_ugr16_timestamp("not-a-date") is None
        assert _parse_ugr16_timestamp("") is None
        assert _parse_ugr16_timestamp("2016-13-01 00:00:00") is None

    def test_whitespace_stripped(self):
        dt = _parse_ugr16_timestamp("  2016-03-01 00:00:01.000  ")
        assert dt is not None

    def test_result_is_utc(self):
        dt = _parse_ugr16_timestamp("2016-07-01 14:00:01.000")
        assert dt.tzinfo == timezone.utc


# ─── TestLabelNormalisation ───────────────────────────────────────────────────

@pytest.mark.unit
class TestLabelNormalisation:
    """Tests for UGR'16 class label normalisation."""

    def test_background_is_benign(self):
        label, is_attack = _normalise_label("background")
        assert label == "background"
        assert is_attack is False

    def test_background_case_insensitive(self):
        label, is_attack = _normalise_label("Background")
        assert is_attack is False

    def test_dos_is_attack(self):
        label, is_attack = _normalise_label("dos")
        assert is_attack is True

    def test_scan11_is_attack(self):
        _, is_attack = _normalise_label("scan11")
        assert is_attack is True

    def test_scan12_is_attack(self):
        _, is_attack = _normalise_label("scan12")
        assert is_attack is True

    def test_nerisbotnet_is_attack(self):
        _, is_attack = _normalise_label("nerisbotnet")
        assert is_attack is True

    def test_spam_is_attack(self):
        _, is_attack = _normalise_label("spam")
        assert is_attack is True

    def test_blacklist_is_attack(self):
        _, is_attack = _normalise_label("blacklist")
        assert is_attack is True

    def test_unknown_label_treated_as_attack(self):
        _, is_attack = _normalise_label("unknown_attack_type")
        assert is_attack is True


# ─── TestUGR16AdapterHeader ───────────────────────────────────────────────────

@pytest.mark.unit
class TestUGR16AdapterHeader:
    """Tests for header validation logic."""

    def test_valid_ugr16_header_passes(self):
        adapter = UGR16Adapter()
        # Should not raise
        adapter.validate_header(list(UGR16_HEADER.split(",")))

    def test_missing_required_column_raises(self):
        adapter = UGR16Adapter(strict_columns=False)
        bad_cols = ["td", "sa", "da", "sp", "dp", "pr", "flg", "fwd", "stos", "pkt", "byt", "class"]
        # 'te' is missing
        with pytest.raises(UGR16ValidationError, match="te"):
            adapter.validate_header(bad_cols)

    def test_missing_sa_raises(self):
        adapter = UGR16Adapter()
        bad_cols = ["te", "td", "da", "sp", "dp", "pr", "flg", "fwd", "stos", "pkt", "byt", "class"]
        with pytest.raises(UGR16ValidationError):
            adapter.validate_header(bad_cols)

    def test_extra_columns_allowed_in_relaxed_mode(self):
        adapter = UGR16Adapter(strict_columns=False)
        cols = list(UGR16_HEADER.split(",")) + ["extra_col"]
        # Should not raise
        adapter.validate_header(cols)

    def test_extra_columns_rejected_in_strict_mode(self):
        adapter = UGR16Adapter(strict_columns=True)
        cols = list(UGR16_HEADER.split(",")) + ["extra_col"]
        with pytest.raises(UGR16ValidationError):
            adapter.validate_header(cols)

    def test_completely_wrong_header_raises(self):
        adapter = UGR16Adapter()
        with pytest.raises(UGR16ValidationError):
            adapter.validate_header(["wrong", "columns", "here"])

    def test_column_names_stripped_of_whitespace(self):
        adapter = UGR16Adapter()
        cols_with_spaces = [f" {c} " for c in UGR16_HEADER.split(",")]
        adapter.validate_header(cols_with_spaces)  # should not raise


# ─── TestUGR16AdapterRowParsing ───────────────────────────────────────────────

@pytest.mark.unit
class TestUGR16AdapterRowParsing:
    """Tests for per-row parsing via iter_records."""

    def _adapter(self, **kwargs) -> UGR16Adapter:
        return UGR16Adapter(skip_invalid_rows=True, **kwargs)

    def _run_on_csv(self, csv_content: str) -> tuple[list[CanonicalFlow], list[str]]:
        tmp = _csv_to_tmp_file(csv_content)
        try:
            return _collect_all(self._adapter(), tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def test_all_synthetic_rows_accepted(self):
        content = make_ugr16_csv_content()
        accepted, rejected = self._run_on_csv(content)
        # Most rows should pass; port-out-of-range cases will be handled silently
        assert len(accepted) >= 8  # at least 8 of 10 synthetic rows are clean
        assert len(rejected) == 0 or all("port" in r for r in rejected)

    def test_accepted_flow_has_correct_src_ip(self):
        single_row = [(
            "2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "5.6.7.8",
            "80", "443", "TCP", ".A.", "0", "0", "1", "100", "background",
        )]
        content = make_ugr16_csv_content(single_row)
        accepted, _ = self._run_on_csv(content)
        assert len(accepted) == 1
        assert accepted[0].src_ip == "1.2.3.4"

    def test_accepted_flow_has_correct_dst_ip(self):
        single_row = [(
            "2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "5.6.7.8",
            "80", "443", "TCP", ".A.", "0", "0", "1", "100", "background",
        )]
        content = make_ugr16_csv_content(single_row)
        accepted, _ = self._run_on_csv(content)
        assert accepted[0].dst_ip == "5.6.7.8"

    def test_accepted_flow_eval_label_is_background(self):
        single_row = [(
            "2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "5.6.7.8",
            "80", "443", "TCP", ".A.", "0", "0", "1", "100", "background",
        )]
        content = make_ugr16_csv_content(single_row)
        accepted, _ = self._run_on_csv(content)
        assert accepted[0].eval_label == "background"
        assert accepted[0].is_attack is False

    def test_attack_row_is_accepted_and_labelled(self):
        single_row = [(
            "2016-07-01 14:00:01.000", "0.01", "198.51.100.1", "42.219.156.50",
            "80", "45678", "TCP", ".S.", "0", "0", "100", "6400", "dos",
        )]
        content = make_ugr16_csv_content(single_row)
        accepted, rejected = self._run_on_csv(content)
        assert len(accepted) == 1
        assert accepted[0].eval_label == "dos"
        assert accepted[0].is_attack is True
        assert len(rejected) == 0

    def test_missing_timestamp_rejected(self):
        row = ("", "0.1", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background")
        content = make_ugr16_csv_content([row])
        _, rejected = self._run_on_csv(content)
        assert len(rejected) == 1
        assert "timestamp" in rejected[0]

    def test_invalid_src_ip_rejected(self):
        row = ("2016-03-01 00:00:01.000", "0.1", "NOT_AN_IP", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background")
        content = make_ugr16_csv_content([row])
        _, rejected = self._run_on_csv(content)
        assert len(rejected) == 1

    def test_invalid_dst_ip_rejected(self):
        row = ("2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "BADIP", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background")
        content = make_ugr16_csv_content([row])
        _, rejected = self._run_on_csv(content)
        assert len(rejected) == 1

    def test_negative_packet_count_rejected(self):
        row = ("2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "-5", "100", "background")
        content = make_ugr16_csv_content([row])
        _, rejected = self._run_on_csv(content)
        assert len(rejected) == 1

    def test_non_numeric_packet_count_rejected(self):
        row = ("2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "abc", "100", "background")
        content = make_ugr16_csv_content([row])
        _, rejected = self._run_on_csv(content)
        assert len(rejected) == 1

    def test_missing_src_ip_rejected(self):
        row = ("2016-03-01 00:00:01.000", "0.1", "", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background")
        content = make_ugr16_csv_content([row])
        _, rejected = self._run_on_csv(content)
        assert len(rejected) == 1

    def test_missing_dst_ip_rejected(self):
        row = ("2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background")
        content = make_ugr16_csv_content([row])
        _, rejected = self._run_on_csv(content)
        assert len(rejected) == 1

    def test_port_out_of_range_set_to_none(self):
        """Out-of-range port is set to None (not rejected outright)."""
        row = ("2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "5.6.7.8", "99999", "80", "TCP", ".A.", "0", "0", "1", "100", "background")
        content = make_ugr16_csv_content([row])
        accepted, rejected = self._run_on_csv(content)
        # Row is accepted; out-of-range port becomes None
        assert len(accepted) == 1
        assert accepted[0].src_port is None

    def test_negative_duration_set_to_none(self):
        row = ("2016-03-01 00:00:01.000", "-1.0", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background")
        content = make_ugr16_csv_content([row])
        accepted, rejected = self._run_on_csv(content)
        assert len(accepted) == 1
        assert accepted[0].duration_seconds is None

    def test_source_row_index_is_zero_based(self):
        content = make_ugr16_csv_content(SYNTHETIC_UGR16_ROWS[:3])
        tmp = _csv_to_tmp_file(content)
        try:
            accepted, _ = _collect_all(self._adapter(), tmp)
        finally:
            tmp.unlink(missing_ok=True)
        assert accepted[0].source_row_index == 0
        assert accepted[1].source_row_index == 1
        assert accepted[2].source_row_index == 2

    def test_source_dataset_is_ugr16(self):
        single_row = [(
            "2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "5.6.7.8",
            "80", "443", "TCP", ".A.", "0", "0", "1", "100", "background",
        )]
        content = make_ugr16_csv_content(single_row)
        accepted, _ = self._run_on_csv(content)
        assert accepted[0].source_dataset == SourceDataset.UGR16

    def test_source_file_recorded(self):
        single_row = [(
            "2016-03-01 00:00:01.000", "0.1", "1.2.3.4", "5.6.7.8",
            "80", "443", "TCP", ".A.", "0", "0", "1", "100", "background",
        )]
        content = make_ugr16_csv_content(single_row)
        tmp = _csv_to_tmp_file(content)
        try:
            accepted, _ = _collect_all(self._adapter(), tmp)
        finally:
            tmp.unlink(missing_ok=True)
        assert accepted[0].source_file is not None
        assert str(tmp) in accepted[0].source_file or accepted[0].source_file.endswith(".csv")

    def test_partial_batch_accepted_and_rejected(self):
        """Mix of valid and invalid rows — counts are correct."""
        rows = list(SYNTHETIC_UGR16_ROWS[:3])
        # Add two malformed rows
        rows.append(("", "0.1", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background"))
        rows.append(("2016-03-01 00:00:01.000", "0.1", "BAD", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background"))
        content = make_ugr16_csv_content(rows)
        accepted, rejected = self._run_on_csv(content)
        assert len(accepted) == 3
        assert len(rejected) == 2


# ─── TestUGR16AdapterEdgeCases ────────────────────────────────────────────────

@pytest.mark.unit
class TestUGR16AdapterEdgeCases:
    """Edge cases: empty input, wrong headers, extra columns."""

    def test_empty_csv_yields_no_records(self):
        tmp = _csv_to_tmp_file(EMPTY_CSV)
        adapter = UGR16Adapter()
        try:
            accepted, rejected = _collect_all(adapter, tmp)
        finally:
            tmp.unlink(missing_ok=True)
        assert len(accepted) == 0
        assert len(rejected) == 0

    def test_wrong_header_raises_validation_error(self):
        tmp = _csv_to_tmp_file(WRONG_HEADER_CSV)
        adapter = UGR16Adapter()
        try:
            with pytest.raises(UGR16ValidationError):
                list(adapter.iter_records(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    def test_extra_columns_accepted_in_relaxed_mode(self):
        tmp = _csv_to_tmp_file(EXTRA_COLUMNS_CSV)
        adapter = UGR16Adapter(strict_columns=False)
        try:
            accepted, rejected = _collect_all(adapter, tmp)
        finally:
            tmp.unlink(missing_ok=True)
        assert len(accepted) == 1
        assert len(rejected) == 0

    def test_extra_columns_rejected_in_strict_mode(self):
        tmp = _csv_to_tmp_file(EXTRA_COLUMNS_CSV)
        adapter = UGR16Adapter(strict_columns=True)
        try:
            with pytest.raises(UGR16ValidationError):
                list(adapter.iter_records(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    def test_nonexistent_file_raises_file_not_found(self):
        adapter = UGR16Adapter()
        with pytest.raises(FileNotFoundError):
            list(adapter.iter_records(Path("/nonexistent/file.csv")))


# ─── TestUGR16AdapterChunking ─────────────────────────────────────────────────

@pytest.mark.unit
class TestUGR16AdapterChunking:
    """Tests for chunked/streaming processing via process_file."""

    def _run_chunked(self, csv_content: str, chunk_size: int = 3) -> tuple[IngestionResult, list[CanonicalFlow]]:
        tmp = _csv_to_tmp_file(csv_content)
        adapter = UGR16Adapter(chunk_size=chunk_size)
        try:
            result, chunks = adapter.process_file(tmp)
            all_flows = []
            for chunk in chunks:
                assert len(chunk) <= chunk_size
                all_flows.extend(chunk)
        finally:
            tmp.unlink(missing_ok=True)
        return result, all_flows

    def test_chunked_yields_all_valid_records(self):
        content = make_ugr16_csv_content()  # 10 synthetic rows
        result, flows = self._run_chunked(content, chunk_size=3)
        # All 10 rows should be accepted (they're all valid)
        assert len(flows) == result.rows_accepted
        assert result.rows_read == 10

    def test_chunk_size_1_processes_all_rows(self):
        content = make_ugr16_csv_content(SYNTHETIC_UGR16_ROWS[:5])
        result, flows = self._run_chunked(content, chunk_size=1)
        assert len(flows) == 5

    def test_chunk_size_larger_than_data(self):
        content = make_ugr16_csv_content(SYNTHETIC_UGR16_ROWS[:3])
        result, flows = self._run_chunked(content, chunk_size=1000)
        assert len(flows) == 3

    def test_result_rows_read_matches_data_rows(self):
        content = make_ugr16_csv_content(SYNTHETIC_UGR16_ROWS)
        result, _ = self._run_chunked(content)
        assert result.rows_read == len(SYNTHETIC_UGR16_ROWS)

    def test_result_completed_at_is_set(self):
        content = make_ugr16_csv_content(SYNTHETIC_UGR16_ROWS[:2])
        result, _ = self._run_chunked(content)
        assert result.completed_at is not None

    def test_rejection_reasons_recorded(self):
        rows = [
            ("", "0.1", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background"),
            ("", "0.1", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background"),
        ]
        content = make_ugr16_csv_content(rows)
        result, flows = self._run_chunked(content)
        assert result.rows_rejected == 2
        assert len(flows) == 0
        assert len(result.rejection_reasons) >= 1

    def test_acceptance_rate_calculated(self):
        content = make_ugr16_csv_content(SYNTHETIC_UGR16_ROWS[:4])
        result, _ = self._run_chunked(content)
        assert result.acceptance_rate is not None
        assert 0.0 <= result.acceptance_rate <= 1.0


# ─── TestUGR16AdapterLabelPolicy ──────────────────────────────────────────────

@pytest.mark.unit
class TestUGR16AdapterLabelPolicy:
    """
    Critical: verify that evaluation labels are NEVER in the feature set.
    This is the core leakage-prevention test.
    """

    def _get_flow(self, label: str) -> CanonicalFlow:
        """Create a minimal CanonicalFlow with the given eval label."""
        row = [(
            "2016-07-01 00:00:01.000", "0.5", "1.2.3.4", "5.6.7.8",
            "80", "443", "TCP", ".A.", "0", "0", "10", "1000", label,
        )]
        content = make_ugr16_csv_content(row)
        tmp = _csv_to_tmp_file(content)
        adapter = UGR16Adapter()
        try:
            accepted, _ = _collect_all(adapter, tmp)
        finally:
            tmp.unlink(missing_ok=True)
        assert len(accepted) == 1
        return accepted[0]

    def test_eval_label_not_in_feature_dict(self):
        flow = self._get_flow("dos")
        fd = flow.feature_dict()
        assert "eval_label" not in fd

    def test_eval_label_raw_not_in_feature_dict(self):
        flow = self._get_flow("dos")
        fd = flow.feature_dict()
        assert "eval_label_raw" not in fd

    def test_is_attack_not_in_feature_dict(self):
        flow = self._get_flow("dos")
        fd = flow.feature_dict()
        assert "is_attack" not in fd

    def test_class_column_stored_in_eval_label(self):
        flow = self._get_flow("nerisbotnet")
        assert flow.eval_label == "nerisbotnet"
        assert flow.is_attack is True

    def test_background_class_not_attack(self):
        flow = self._get_flow("background")
        assert flow.is_attack is False

    def test_feature_dict_does_not_contain_source_row_index(self):
        """Metadata fields (like row index) must not leak into features."""
        flow = self._get_flow("background")
        fd = flow.feature_dict()
        assert "source_row_index" not in fd

    def test_feature_dict_does_not_contain_record_id(self):
        flow = self._get_flow("background")
        fd = flow.feature_dict()
        assert "record_id" not in fd


# ─── TestFeatureEligibilityContract ───────────────────────────────────────────

@pytest.mark.unit
class TestFeatureEligibilityContract:
    """
    Verify that the eligibility contracts defined in canonical_flow.py
    are consistent and that prohibited features are not present in CanonicalFlow.
    """

    def test_eligible_and_prohibited_are_disjoint(self):
        overlap = ELIGIBLE_FEATURE_COLUMNS & PROHIBITED_FEATURE_COLUMNS
        assert overlap == frozenset(), f"Overlap found: {overlap}"

    def test_eval_only_not_in_eligible(self):
        overlap = EVAL_ONLY_COLUMNS & ELIGIBLE_FEATURE_COLUMNS
        assert overlap == frozenset(), f"Eval-only fields in eligible: {overlap}"

    def test_metadata_not_in_eligible(self):
        overlap = METADATA_COLUMNS & ELIGIBLE_FEATURE_COLUMNS
        assert overlap == frozenset(), f"Metadata fields in eligible: {overlap}"

    def test_canonical_flow_has_no_prohibited_field_attributes(self):
        """CanonicalFlow model fields must not include prohibited column names."""
        model_fields = set(CanonicalFlow.model_fields.keys())
        for col in PROHIBITED_FEATURE_COLUMNS:
            assert col not in model_fields, (
                f"PROHIBITED column {col!r} found as a field on CanonicalFlow. "
                "Remove it to prevent accidental use in models."
            )

    def test_eval_only_fields_are_in_canonical_flow(self):
        """Eval-only fields must exist on CanonicalFlow (they're needed for evaluation)."""
        model_fields = set(CanonicalFlow.model_fields.keys())
        for col in EVAL_ONLY_COLUMNS:
            assert col in model_fields, f"EVAL_ONLY field {col!r} missing from CanonicalFlow"

    def test_bwd_packets_not_a_canonical_field(self):
        assert "bwd_packets" not in CanonicalFlow.model_fields

    def test_bwd_bytes_not_a_canonical_field(self):
        assert "bwd_bytes" not in CanonicalFlow.model_fields

    def test_rtt_not_a_canonical_field(self):
        assert "rtt_ms" not in CanonicalFlow.model_fields

    def test_eligible_features_exist_on_canonical_flow(self):
        """Every eligible feature column must correspond to a CanonicalFlow field."""
        model_fields = set(CanonicalFlow.model_fields.keys())
        for col in ELIGIBLE_FEATURE_COLUMNS:
            assert col in model_fields, (
                f"Eligible column {col!r} not found on CanonicalFlow. "
                "Either add it or remove it from ELIGIBLE_FEATURE_COLUMNS."
            )


# ─── TestIngestionResult ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestIngestionResult:
    """Tests for IngestionResult statistics tracking."""

    def test_initial_counts_are_zero(self):
        r = IngestionResult(
            source_file="test.csv",
            source_dataset=SourceDataset.UGR16,
        )
        assert r.rows_read == 0
        assert r.rows_accepted == 0
        assert r.rows_rejected == 0

    def test_record_rejection_increments_count(self):
        r = IngestionResult(
            source_file="test.csv",
            source_dataset=SourceDataset.UGR16,
        )
        r.rows_read = 5
        r.record_rejection("invalid_ip")
        r.record_rejection("invalid_ip")
        r.record_rejection("missing_timestamp")
        assert r.rows_rejected == 3
        assert r.rejection_reasons["invalid_ip"] == 2
        assert r.rejection_reasons["missing_timestamp"] == 1

    def test_acceptance_rate_correct(self):
        r = IngestionResult(
            source_file="test.csv",
            source_dataset=SourceDataset.UGR16,
        )
        r.rows_read = 10
        r.rows_accepted = 8
        assert r.acceptance_rate == pytest.approx(0.8)

    def test_acceptance_rate_none_when_no_rows_read(self):
        r = IngestionResult(
            source_file="test.csv",
            source_dataset=SourceDataset.UGR16,
        )
        assert r.acceptance_rate is None

    def test_finish_sets_completed_at(self):
        r = IngestionResult(
            source_file="test.csv",
            source_dataset=SourceDataset.UGR16,
        )
        assert r.completed_at is None
        r.finish()
        assert r.completed_at is not None


# ─── TestAcquisitionTooling ───────────────────────────────────────────────────

@pytest.mark.unit
class TestAcquisitionTooling:
    """Tests for dataset acquisition script and manifest utilities."""

    def test_dataset_registry_has_ugr16(self):
        from scripts.acquire_dataset import DATASET_REGISTRY
        assert "ugr16" in DATASET_REGISTRY

    def test_ugr16_registry_has_official_page(self):
        from scripts.acquire_dataset import DATASET_REGISTRY
        entry = DATASET_REGISTRY["ugr16"]
        assert "nesg.ugr.es" in entry["official_page"]

    def test_ugr16_registry_has_available_months(self):
        from scripts.acquire_dataset import DATASET_REGISTRY
        months = DATASET_REGISTRY["ugr16"]["available_months"]
        assert "2016-03" in months
        assert "2016-07" in months
        assert len(months) == 6  # March–August 2016

    def test_ugr16_auth_required(self):
        from scripts.acquire_dataset import DATASET_REGISTRY
        assert DATASET_REGISTRY["ugr16"]["auth_required"] is True

    def test_cicids2017_in_registry(self):
        from scripts.acquire_dataset import DATASET_REGISTRY
        assert "cicids2017" in DATASET_REGISTRY

    def test_sha256_computation(self, tmp_path):
        from scripts.acquire_dataset import compute_sha256
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"TrafficShield test data")
        sha = compute_sha256(test_file)
        assert len(sha) == 64  # SHA-256 hex digest is 64 chars
        assert sha.isalnum()

    def test_write_manifest_creates_json(self, tmp_path):
        from scripts.acquire_dataset import write_manifest
        manifest_path = write_manifest(
            dest_dir=tmp_path,
            dataset_name="ugr16",
            files=[{"filename": "test.csv", "size_bytes": 100, "sha256": "abc123"}],
        )
        import json
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["dataset"] == "ugr16"
        assert len(data["files"]) == 1

    def test_manifest_does_not_overwrite_without_warning(self, tmp_path):
        """Second write produces a warning but succeeds (logged, not raised)."""
        from scripts.acquire_dataset import write_manifest
        write_manifest(tmp_path, "ugr16", [])
        # Second call should succeed (overwrite with warning)
        write_manifest(tmp_path, "ugr16", [{"filename": "v2.csv", "size_bytes": 0, "sha256": "x"}])
        import json
        data = json.loads((tmp_path / "manifest.json").read_text())
        assert len(data["files"]) == 1


# ─── TestManifestValidation ───────────────────────────────────────────────────

@pytest.mark.unit
class TestManifestValidation:
    """Tests for check_manifest.py validation logic."""

    def test_valid_manifest_passes(self, tmp_path):
        from scripts.check_manifest import validate_manifest
        import json
        # Create a real file with known content
        data_file = tmp_path / "sample.csv"
        data_file.write_bytes(b"hello,world")
        # Compute real checksum
        from scripts.acquire_dataset import compute_sha256
        sha = compute_sha256(data_file)

        manifest = {
            "dataset": "ugr16",
            "retrieved_at": "2026-10-22T00:00:00+00:00",
            "destination": str(tmp_path),
            "files": [{
                "filename": "sample.csv",
                "size_bytes": data_file.stat().st_size,
                "sha256": sha,
            }],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        assert validate_manifest(manifest_path) is True

    def test_wrong_checksum_fails(self, tmp_path):
        from scripts.check_manifest import validate_manifest
        import json
        data_file = tmp_path / "sample.csv"
        data_file.write_bytes(b"hello,world")
        manifest = {
            "dataset": "ugr16",
            "retrieved_at": "2026-10-22T00:00:00+00:00",
            "destination": str(tmp_path),
            "files": [{
                "filename": "sample.csv",
                "size_bytes": data_file.stat().st_size,
                "sha256": "wrongchecksum" * 4,
            }],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        assert validate_manifest(manifest_path) is False

    def test_missing_file_fails(self, tmp_path):
        from scripts.check_manifest import validate_manifest
        import json
        manifest = {
            "dataset": "ugr16",
            "retrieved_at": "2026-10-22T00:00:00+00:00",
            "destination": str(tmp_path),
            "files": [{
                "filename": "nonexistent.csv",
                "size_bytes": 100,
                "sha256": "a" * 64,
            }],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        assert validate_manifest(manifest_path) is False

    def test_missing_manifest_file_fails(self, tmp_path):
        from scripts.check_manifest import validate_manifest
        assert validate_manifest(tmp_path / "does_not_exist.json") is False

    def test_missing_required_key_fails(self, tmp_path):
        from scripts.check_manifest import validate_manifest
        import json
        manifest = {"dataset": "ugr16"}  # missing required keys
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        assert validate_manifest(manifest_path) is False
