"""
Unit Tests for Evaluation CLI
==============================
"""
from pathlib import Path

from evaluation.cli import build_parser, run_evaluation


def test_cli_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["--demo"])
    assert args.demo is True
    assert args.detector == "statistical"
    assert args.quantile == 0.99
    assert args.train_ratio == 0.6
    assert args.cal_ratio == 0.2
    assert args.test_ratio == 0.2


def test_cli_run_demo_statistical(tmp_path: Path):
    parser = build_parser()
    args = parser.parse_args([
        "--demo",
        "--detector", "statistical",
        "--out-dir", str(tmp_path / "reports"),
    ])
    exit_code = run_evaluation(args)
    assert exit_code == 0

    json_report = tmp_path / "reports" / "evaluation_report_RobustStatisticalDetector.json"
    csv_report = tmp_path / "reports" / "evaluation_summary_RobustStatisticalDetector.csv"
    assert json_report.exists()
    assert csv_report.exists()


def test_cli_run_demo_iforest(tmp_path: Path):
    parser = build_parser()
    args = parser.parse_args([
        "--demo",
        "--detector", "iforest",
        "--if-estimators", "20",
        "--out-dir", str(tmp_path / "reports"),
    ])
    exit_code = run_evaluation(args)
    assert exit_code == 0

    json_report = tmp_path / "reports" / "evaluation_report_IsolationForestDetector.json"
    assert json_report.exists()
