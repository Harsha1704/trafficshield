"""
Unit Tests for UNSW-NB15 Dataset Adapter
========================================
Milestone 7 — TrafficShield
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from evaluation.partitioning import chronological_three_way_split
from ingestion.adapters.unsw_nb15 import (
    UNSW15Adapter,
)
from ingestion.schema.canonical_flow import SourceDataset


def make_synthetic_unsw_row(
    row_idx: int = 1,
    stime: float = 1421927414.0,
    ltime: float = 1421927415.0,
    is_attack: int = 0,
    cat: str = "",
    sbytes: int = 1200,
    spkts: int = 10,
    dbytes: int = 500,
    dpkts: int = 5,
) -> list[str]:
    """Create a 49-element list matching the exact UNSW-NB15 schema."""
    row = [
        f"10.0.0.{(row_idx % 250) + 1}",   # 1. srcip
        str(30000 + (row_idx % 20000)),    # 2. sport
        "192.168.1.10",                    # 3. dstip
        "80" if row_idx % 2 == 0 else "443", # 4. dsport
        "tcp",                             # 5. proto
        "FIN",                             # 6. state
        f"{(ltime - stime):.3f}",          # 7. dur
        str(sbytes),                       # 8. sbytes
        str(dbytes),                       # 9. dbytes (reverse)
        "64",                              # 10. sttl
        "64",                              # 11. dttl (reverse)
        "0",                               # 12. sloss
        "0",                               # 13. dloss (reverse)
        "http" if row_idx % 2 == 0 else "-", # 14. service
        f"{(sbytes * 8 / max(0.001, ltime - stime)):.2f}", # 15. Sload
        f"{(dbytes * 8 / max(0.001, ltime - stime)):.2f}", # 16. Dload (reverse)
        str(spkts),                        # 17. Spkts
        str(dpkts),                        # 18. Dpkts (reverse)
        "255",                             # 19. swin
        "255",                             # 20. dwin (reverse)
        "1000000",                         # 21. stcpb
        "2000000",                         # 22. dtcpb (reverse)
        str(sbytes // max(1, spkts)),      # 23. smeansz
        str(dbytes // max(1, dpkts)),      # 24. dmeansz (reverse)
        "0",                               # 25. trans_depth
        "0",                               # 26. res_bdy_len (reverse)
        "1.5",                             # 27. Sjit
        "1.2",                             # 28. Djit (reverse)
        str(stime),                        # 29. Stime
        str(ltime),                        # 30. Ltime
        "0.1",                             # 31. Sintpkt
        "0.2",                             # 32. Dintpkt (reverse)
        "0.05",                            # 33. tcprtt (reverse)
        "0.02",                            # 34. synack (reverse)
        "0.03",                            # 35. ackdat (reverse)
        "0",                               # 36. is_sm_ips_ports
        "1",                               # 37. ct_state_ttl
        "1",                               # 38. ct_flw_http_mthd
        "0",                               # 39. is_ftp_login
        "0",                               # 40. ct_ftp_cmd
        "2",                               # 41. ct_srv_src
        "2",                               # 42. ct_srv_dst
        "3",                               # 43. ct_dst_ltm
        "4",                               # 44. ct_src_ ltm
        "1",                               # 45. ct_src_dport_ltm
        "1",                               # 46. ct_dst_sport_ltm
        "2",                               # 47. ct_dst_src_ltm
        cat,                               # 48. attack_cat
        str(is_attack),                    # 49. Label
    ]
    assert len(row) == 49
    return row


def create_synthetic_unsw_csv(filepath: Path, n_rows: int = 50, start_time: float = 1421927414.0) -> Path:
    """Create a synthetic headerless UNSW-NB15 CSV file."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for i in range(n_rows):
            t_s = start_time + (i * 5.0)
            t_l = t_s + 0.5
            is_atk = 1 if (i >= 40 and i % 2 == 0) else 0
            cat_str = "exploits" if is_atk else ""
            pkts = 200 if is_atk else 10
            bts = 50000 if is_atk else 1200
            row = make_synthetic_unsw_row(
                row_idx=i + 1,
                stime=t_s,
                ltime=t_l,
                is_attack=is_atk,
                cat=cat_str,
                sbytes=bts,
                spkts=pkts,
            )
            writer.writerow(row)
    return filepath


def test_synthetic_headerless_ingestion(tmp_path: Path):
    """Verify UNSW15Adapter reads headerless CSV records into CanonicalFlow objects."""
    csv_file = tmp_path / "synthetic_unsw.csv"
    create_synthetic_unsw_csv(csv_file, n_rows=25)

    adapter = UNSW15Adapter(chunk_size=10)
    flows, result = adapter.ingest_file(csv_file)

    assert result.rows_read == 25
    assert result.rows_accepted == 25
    assert result.rows_rejected == 0
    assert len(flows) == 25

    flow = flows[0]
    assert flow.source_dataset == SourceDataset.UNSWNB15
    assert flow.fwd_packets == 10
    assert flow.fwd_bytes == 1200
    assert flow.eval_label == "normal"
    assert flow.is_attack is False
    assert flow.flow_end_ts.year == 2015


def test_column_count_mismatch_and_malformed_handling(tmp_path: Path):
    """Verify malformed rows (48 cols, 50 cols, bad timestamps) are rejected and counted."""
    csv_file = tmp_path / "malformed_unsw.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # 1. Valid row
        writer.writerow(make_synthetic_unsw_row(1))
        # 2. Short row (48 cols)
        short_row = make_synthetic_unsw_row(2)[:-1]
        writer.writerow(short_row)
        # 3. Long row (50 cols)
        long_row = make_synthetic_unsw_row(3) + ["extra"]
        writer.writerow(long_row)
        # 4. Bad timestamp
        bad_ts_row = make_synthetic_unsw_row(4)
        bad_ts_row[29] = "not-a-timestamp"
        writer.writerow(bad_ts_row)
        # 5. Negative bytes
        neg_bytes_row = make_synthetic_unsw_row(5)
        neg_bytes_row[7] = "-500"
        writer.writerow(neg_bytes_row)

    adapter = UNSW15Adapter()
    flows, result = adapter.ingest_file(csv_file)

    assert result.rows_read == 5
    assert result.rows_accepted == 1
    assert result.rows_rejected == 4
    assert "column_count_mismatch_expected_49_got_48" in result.rejection_reasons
    assert "column_count_mismatch_expected_49_got_50" in result.rejection_reasons
    assert "invalid_end_timestamp_Ltime" in result.rejection_reasons
    assert "negative_sbytes" in result.rejection_reasons


def test_unidirectional_dataframe_loader_excludes_reverse_features(tmp_path: Path):
    """Verify load_unidirectional_dataframe strips reverse direction and separates labels."""
    csv_file = tmp_path / "test_unsw.csv"
    create_synthetic_unsw_csv(csv_file, n_rows=30)

    adapter = UNSW15Adapter()
    feat_df, lbl_series, meta_df = adapter.load_unidirectional_dataframe(csv_file)

    assert len(feat_df) == 30
    assert len(lbl_series) == 30
    assert len(meta_df) == 30

    # Model features MUST NOT contain reverse features
    assert "dbytes" not in feat_df.columns
    assert "dttl" not in feat_df.columns
    assert "dloss" not in feat_df.columns
    assert "dload" not in feat_df.columns
    assert "dpkts" not in feat_df.columns
    assert "tcprtt" not in feat_df.columns
    assert "eval_label" not in feat_df.columns
    assert "is_attack" not in feat_df.columns
    assert "src_ip" not in feat_df.columns

    # Model features MUST contain forward-observable fields
    assert "fwd_bytes" in feat_df.columns
    assert "fwd_packets" in feat_df.columns
    assert "duration_seconds" in feat_df.columns
    assert "sttl" in feat_df.columns
    assert "swin" in feat_df.columns

    # Labels and meta are preserved separately
    assert "eval_label" in lbl_series.name
    assert "src_ip" in meta_df.columns
    assert "flow_end_ts" in meta_df.columns


def test_chronological_splitting_on_unsw_dataset(tmp_path: Path):
    """Verify chronological split guarantees zero temporal lookahead leakage."""
    csv_file = tmp_path / "chrono_unsw.csv"
    create_synthetic_unsw_csv(csv_file, n_rows=100, start_time=1421927414.0)

    adapter = UNSW15Adapter()
    feat_df, lbl_series, meta_df = adapter.load_unidirectional_dataframe(csv_file)

    full_df = pd.concat([feat_df, lbl_series, meta_df[["flow_end_ts"]]], axis=1)
    partition = chronological_three_way_split(
        full_df,
        train_ratio=0.6,
        cal_ratio=0.2,
        test_ratio=0.2,
        timestamp_col="flow_end_ts",
    )

    assert partition.train_count == 60
    assert partition.calibration_count == 20
    assert partition.test_count == 20

    train_max = partition.train_df["flow_end_ts"].max()
    cal_min = partition.calibration_df["flow_end_ts"].min()
    cal_max = partition.calibration_df["flow_end_ts"].max()
    test_min = partition.test_df["flow_end_ts"].min()

    assert train_max <= cal_min
    assert cal_max <= test_min


def test_missing_file_raises_filenotfound(tmp_path: Path):
    """Verify non-existent input files raise clear FileNotFoundError."""
    adapter = UNSW15Adapter()
    missing_path = tmp_path / "does_not_exist.csv"
    with pytest.raises(FileNotFoundError):
        list(adapter.iter_records(missing_path))


def test_boundary_deduplication(tmp_path: Path):
    """Verify boundary de-duplication drops the overlapping row across consecutive files."""
    f1 = tmp_path / "file1.csv"
    f2 = tmp_path / "file2.csv"

    # File 1 has 5 rows
    rows1 = [make_synthetic_unsw_row(i, stime=100.0 + i, ltime=101.0 + i) for i in range(5)]
    with open(f1, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows(rows1)

    # File 2 starts with identical duplicate of File 1's last row (rows1[-1]), plus 4 new rows
    dup_row = list(rows1[-1])
    rows2 = [dup_row] + [make_synthetic_unsw_row(10 + i, stime=110.0 + i, ltime=111.0 + i) for i in range(4)]
    with open(f2, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows(rows2)

    adapter = UNSW15Adapter()

    # Without deduplication: 5 + 5 = 10 rows
    feat_raw, _, _ = adapter.load_unidirectional_dataframe([f1, f2], deduplicate_boundaries=False)
    assert len(feat_raw) == 10

    # With deduplication: 5 + 5 - 1 = 9 rows
    feat_dedup, _, _ = adapter.load_unidirectional_dataframe([f1, f2], deduplicate_boundaries=True)
    assert len(feat_dedup) == 9


def test_causal_only_loading(tmp_path: Path):
    """Verify causal_only=True excludes all precomputed ct_* features."""
    csv_file = tmp_path / "test_causal.csv"
    create_synthetic_unsw_csv(csv_file, n_rows=20)

    adapter = UNSW15Adapter()
    feat_all, _, _ = adapter.load_unidirectional_dataframe(csv_file, causal_only=False, include_engineered_rates=False)
    assert len(feat_all.columns) == 19
    assert "ct_srv_src" in feat_all.columns

    feat_causal, _, _ = adapter.load_unidirectional_dataframe(csv_file, causal_only=True, include_engineered_rates=False)
    assert len(feat_causal.columns) == 10
    assert "ct_srv_src" not in feat_causal.columns
    assert "ct_dst_ltm" not in feat_causal.columns
    assert "fwd_bytes" in feat_causal.columns
    assert "duration_seconds" in feat_causal.columns


def test_identical_timestamps_kept_together_in_split():
    """Verify split keeps identical timestamps together without straddling boundaries."""
    records = []
    # 10 records at T=10, 10 records at T=20, 10 records at T=30
    for i in range(30):
        if i < 10:
            ts = "2026-01-01T10:00:00Z"
        elif i < 20:
            ts = "2026-01-01T11:00:00Z"
        else:
            ts = "2026-01-01T12:00:00Z"
        records.append({
            "flow_end_ts": ts,
            "fwd_packets": 10,
            "fwd_bytes": 100,
            "duration_seconds": 1.0,
            "eval_label": "normal",
        })

    df = pd.DataFrame(records)
    part = chronological_three_way_split(
        df,
        train_ratio=0.35, # 10.5 rows -> would straddle T=11:00:00 without grouping
        cal_ratio=0.35,
        test_ratio=0.30,
        timestamp_col="flow_end_ts",
    )

    # Identical timestamps must not be split across train and cal
    train_max = part.train_df["flow_end_ts"].max()
    cal_min = part.calibration_df["flow_end_ts"].min()
    assert train_max < cal_min

