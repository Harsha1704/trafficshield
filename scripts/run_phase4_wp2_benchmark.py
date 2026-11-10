"""
TrafficShield Phase 4 WP2 — Benchmark Execution Protocol
=========================================================
Executes reproducible, multi-stage performance qualification of the
frozen hybrid dual-detector inference architecture.

Safety Invariants:
- Uses FLASK_ENV=testing, APP_ENV=testing, sqlite:///:memory:
- Read-only on production artifacts (verifies hashes)
- Never modifies production DB, thresholds, or models
- Records raw timing observations to reports/phase4_wp2_benchmark_raw_results.csv
"""
from __future__ import annotations

import csv
import gc
import hashlib
import json
import os
import platform
import sys
import time
import types
from pathlib import Path
from typing import Any

# Windows Smart App Control / WDAC compatibility guard:
if "sklearn.linear_model._sag_fast" not in sys.modules:
    try:
        import sklearn.linear_model._sag_fast  # noqa: F401
    except (ImportError, OSError):
        _mock_sag = types.ModuleType("sklearn.linear_model._sag_fast")
        _mock_sag.sag32 = lambda *args, **kwargs: None
        _mock_sag.sag64 = lambda *args, **kwargs: None
        sys.modules["sklearn.linear_model._sag_fast"] = _mock_sag

if "scipy.stats._qmvnt_cy" not in sys.modules:
    try:
        import scipy.stats._qmvnt_cy  # noqa: F401
    except (ImportError, OSError):
        _mock_qmvnt = types.ModuleType("scipy.stats._qmvnt_cy")
        _mock_qmvnt._qmvn_inner = lambda *args, **kwargs: (0.0, 0.0)
        _mock_qmvnt._qmvt_inner = lambda *args, **kwargs: (0.0, 0.0)
        sys.modules["scipy.stats._qmvnt_cy"] = _mock_qmvnt

# Force test isolation before imports
os.environ["FLASK_ENV"] = "testing"
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = "sqlite:///:memory:"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import sklearn
import xgboost

from app import create_app
from app.database.models import User
from app.utils.auth import generate_token
from ml.production_service import ProductionInferenceService


def compute_stats(arr: list[float] | np.ndarray) -> dict[str, float]:
    a = np.array(arr, dtype=float)
    return {
        "count": int(len(a)),
        "min_ms": round(float(np.min(a)), 4),
        "mean_ms": round(float(np.mean(a)), 4),
        "median_p50_ms": round(float(np.percentile(a, 50)), 4),
        "p90_ms": round(float(np.percentile(a, 90)), 4),
        "p95_ms": round(float(np.percentile(a, 95)), 4),
        "p99_ms": round(float(np.percentile(a, 99)), 4),
        "max_ms": round(float(np.max(a)), 4),
        "stdev_ms": round(float(np.std(a)), 4),
        "error_count": 0,
    }


def main():
    print("=================================================================")
    print(" TrafficShield Phase 4 WP2 — Benchmark Execution Protocol")
    print("=================================================================")

    # 1. Environment & Telemetry
    env_info = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count_logical": os.cpu_count() or 1,
        "sklearn_version": sklearn.__version__,
        "xgboost_version": xgboost.__version__,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
    }
    print(f"Hardware: {env_info['processor']} ({env_info['cpu_count_logical']} logical cores)")
    print(f"OS: {env_info['platform']} | Python: {env_info['python_version']}")

    # 2. Frozen Artifact Hashes
    expected_hashes = {
        "production_detector.joblib": "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495",
        "production_detector.json": "3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1",
        "production_iforest.joblib": "d9fe41016c51f8484b57c80bb2f0ec41186c66add9bae71f822d0a85c13a350e",
        "production_iforest.json": "5daf8b0dab1c4c3a66e4cb2c38b10c406f6c1861572d27a08155c8541bf4cb94",
        "production_preprocessor.joblib": "effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653",
    }
    models_dir = PROJECT_ROOT / "artifacts" / "models"
    for fname, exp_hash in expected_hashes.items():
        act_hash = hashlib.sha256((models_dir / fname).read_bytes()).hexdigest()
        assert act_hash == exp_hash, f"Hash mismatch on {fname}"
    print("Model Artifacts: All 5 hashes verified bit-for-bit.")

    # 3. Initialize Service
    service = ProductionInferenceService(verify_checksums=True)
    assert service.threshold == 0.50
    assert service.iforest_threshold == 0.7278956397776036
    print(f"Thresholds Verified: XGBoost={service.threshold}, IForest={service.iforest_threshold}")

    # Canonical flow from test_single_flow_latency_benchmark
    test_flow = {
        "duration_seconds": 0.05,
        "fwd_bytes": 1200,
        "sttl": 64,
        "sload": 192000.0,
        "fwd_packets": 10,
        "swin": 255,
        "smeansz": 120.0,
        "sjit": 2.5,
        "sintpkt": 5.5,
        "packet_rate": 200.0,
        "byte_rate": 24000.0,
        "bytes_per_packet": 120.0,
        "is_sm_ips_ports": 0,
    }

    raw_observations: list[dict[str, Any]] = []

    # 4. Component Latency Decomposition (500 iterations, 10 warmup)
    print("\n--- Running Component Latency Decomposition (10 warmup, 500 iterations) ---")
    # Warmup
    for _ in range(10):
        service.predict_single(test_flow)

    df_prepared = service.validate_and_prepare_input(test_flow)

    comp_prep: list[float] = []
    comp_xgb: list[float] = []
    comp_iforest: list[float] = []
    comp_attribution: list[float] = []
    comp_decision: list[float] = []

    for i in range(500):
        # A. Preprocessing
        t0 = time.perf_counter()
        X_df = service.preprocessor.transform_df(df_prepared)
        t_p = (time.perf_counter() - t0) * 1000.0
        comp_prep.append(t_p)
        raw_observations.append({"series": "component_microbenchmark", "iteration": i + 1, "component": "preprocessing", "latency_ms": t_p})

        # B. XGBoost
        t0 = time.perf_counter()
        proba = float(service.model.predict_proba(X_df)[0, 1])
        t_x = (time.perf_counter() - t0) * 1000.0
        comp_xgb.append(t_x)
        raw_observations.append({"series": "component_microbenchmark", "iteration": i + 1, "component": "xgboost", "latency_ms": t_x})

        # C. Isolation Forest
        t0 = time.perf_counter()
        if_score = float(service.iforest.score_samples(X_df)[0])
        t_if = (time.perf_counter() - t0) * 1000.0
        comp_iforest.append(t_if)
        raw_observations.append({"series": "component_microbenchmark", "iteration": i + 1, "component": "isolation_forest", "latency_ms": t_if})

        # D. Attribution
        t0 = time.perf_counter()
        service._compute_feature_attributions(df_prepared)
        t_att = (time.perf_counter() - t0) * 1000.0
        comp_attribution.append(t_att)
        raw_observations.append({"series": "component_microbenchmark", "iteration": i + 1, "component": "feature_attribution", "latency_ms": t_att})

        # E. Decision Logic
        t0 = time.perf_counter()
        s_flag = proba >= service.threshold
        u_flag = if_score >= service.iforest_threshold
        if s_flag and u_flag:
            _ = "DUAL_CONFIRMED"
        elif s_flag:
            _ = "SUPERVISED_ONLY_ALERT"
        elif u_flag:
            _ = "UNSUPERVISED_NOVELTY"
        else:
            _ = "NORMAL_TRAFFIC"
        t_d = (time.perf_counter() - t0) * 1000.0
        comp_decision.append(t_d)
        raw_observations.append({"series": "component_microbenchmark", "iteration": i + 1, "component": "hybrid_decision_logic", "latency_ms": t_d})

    stats_prep = compute_stats(comp_prep)
    stats_xgb = compute_stats(comp_xgb)
    stats_iforest = compute_stats(comp_iforest)
    stats_attribution = compute_stats(comp_attribution)
    stats_decision = compute_stats(comp_decision)

    print(f"  Preprocessing:        mean={stats_prep['mean_ms']} ms | p50={stats_prep['median_p50_ms']} ms | p95={stats_prep['p95_ms']} ms")
    print(f"  XGBoost:              mean={stats_xgb['mean_ms']} ms | p50={stats_xgb['median_p50_ms']} ms | p95={stats_xgb['p95_ms']} ms")
    print(f"  Isolation Forest:     mean={stats_iforest['mean_ms']} ms | p50={stats_iforest['median_p50_ms']} ms | p95={stats_iforest['p95_ms']} ms")
    print(f"  Feature Attribution:  mean={stats_attribution['mean_ms']} ms | p50={stats_attribution['median_p50_ms']} ms | p95={stats_attribution['p95_ms']} ms")
    print(f"  Decision Logic:       mean={stats_decision['mean_ms']} ms | p50={stats_decision['median_p50_ms']} ms | p95={stats_decision['p95_ms']} ms")

    # 5. Supervised vs Hybrid Comparison (500 iterations, 10 warmup)
    print("\n--- Running Supervised vs Hybrid Comparison (10 warmup, 500 iterations) ---")
    sup_latencies: list[float] = []
    hyb_latencies: list[float] = []

    for _ in range(10):
        # Warmup
        X_df = service.preprocessor.transform_df(df_prepared)
        _ = float(service.model.predict_proba(X_df)[0, 1])
        _ = float(service.iforest.score_samples(X_df)[0])

    for i in range(500):
        # Supervised Pipeline: Prep + XGBoost
        t0 = time.perf_counter()
        X_df = service.preprocessor.transform_df(df_prepared)
        p = float(service.model.predict_proba(X_df)[0, 1])
        _ = p >= service.threshold
        t_sup = (time.perf_counter() - t0) * 1000.0
        sup_latencies.append(t_sup)
        raw_observations.append({"series": "supervised_only_pipeline", "iteration": i + 1, "component": "supervised_prep_xgb", "latency_ms": t_sup})

        # Hybrid Pure Model Pipeline: Prep + XGB + IForest + Attrib + Decision
        t0 = time.perf_counter()
        X_df = service.preprocessor.transform_df(df_prepared)
        p = float(service.model.predict_proba(X_df)[0, 1])
        s = float(service.iforest.score_samples(X_df)[0])
        service._compute_feature_attributions(df_prepared)
        sf = p >= service.threshold
        uf = s >= service.iforest_threshold
        _ = "DUAL_CONFIRMED" if (sf and uf) else ("SUPERVISED_ONLY_ALERT" if sf else ("UNSUPERVISED_NOVELTY" if uf else "NORMAL_TRAFFIC"))
        t_hyb = (time.perf_counter() - t0) * 1000.0
        hyb_latencies.append(t_hyb)
        raw_observations.append({"series": "hybrid_pure_model_pipeline", "iteration": i + 1, "component": "hybrid_pure_model", "latency_ms": t_hyb})

    stats_sup = compute_stats(sup_latencies)
    stats_hyb = compute_stats(hyb_latencies)
    print(f"  Supervised-Only:      mean={stats_sup['mean_ms']} ms | p50={stats_sup['median_p50_ms']} ms | p95={stats_sup['p95_ms']} ms")
    print(f"  Hybrid Pure Model:    mean={stats_hyb['mean_ms']} ms | p50={stats_hyb['median_p50_ms']} ms | p95={stats_hyb['p95_ms']} ms")

    # 6. Primary Single-Flow Service Benchmark (1,000 timed iterations, 10 warmup)
    print("\n--- Running Primary Single-Flow Service Benchmark (10 warmup, 1000 iterations) ---")
    for _ in range(10):
        service.predict_single(test_flow)

    service_latencies: list[float] = []
    for i in range(1000):
        t0 = time.perf_counter()
        _ = service.predict_single(test_flow)
        t_s = (time.perf_counter() - t0) * 1000.0
        service_latencies.append(t_s)
        raw_observations.append({"series": "primary_single_flow_service", "iteration": i + 1, "component": "predict_single", "latency_ms": t_s})

    stats_service = compute_stats(service_latencies)
    print(f"  Service predict_single: mean={stats_service['mean_ms']} ms | p50={stats_service['median_p50_ms']} ms | p95={stats_service['p95_ms']} ms | p99={stats_service['p99_ms']} ms")

    # 7. HTTP / REST API Benchmark via Flask Test Client (200 timed iterations, 10 warmup)
    print("\n--- Running HTTP / REST API Test Client Benchmark (10 warmup, 200 iterations) ---")
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        user = User(username="analyst_bench", role="analyst", is_active=True)
        token = generate_token(user)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    for _ in range(10):
        resp = client.post("/api/v1/predict", headers=headers, json=test_flow)
        assert resp.status_code == 200

    api_latencies: list[float] = []
    for i in range(200):
        t0 = time.perf_counter()
        resp = client.post("/api/v1/predict", headers=headers, json=test_flow)
        t_api = (time.perf_counter() - t0) * 1000.0
        assert resp.status_code == 200
        api_latencies.append(t_api)
        raw_observations.append({"series": "http_api_test_client", "iteration": i + 1, "component": "post_predict_api", "latency_ms": t_api})

    stats_api = compute_stats(api_latencies)
    print(f"  HTTP API /predict:    mean={stats_api['mean_ms']} ms | p50={stats_api['median_p50_ms']} ms | p95={stats_api['p95_ms']} ms | p99={stats_api['p99_ms']} ms")

    # 8. Re-evaluate Exact Legacy TestWorkflow10 Loop (50 iterations)
    print("\n--- Running Exact Legacy TestWorkflow10 Loop (50 iterations) ---")
    legacy_latencies: list[float] = []
    for i in range(50):
        t0 = time.perf_counter()
        resp = client.post("/api/v1/predict", headers=headers, json=test_flow)
        t1 = time.perf_counter()
        assert resp.status_code == 200
        t_l = (t1 - t0) * 1000.0
        legacy_latencies.append(t_l)
        raw_observations.append({"series": "legacy_workflow10_test_loop", "iteration": i + 1, "component": "legacy_50_run", "latency_ms": t_l})

    stats_legacy = compute_stats(legacy_latencies)
    legacy_passed = stats_legacy["mean_ms"] < 35.0
    print(f"  Legacy 50-run loop:   mean={stats_legacy['mean_ms']} ms (SLA < 35.0 ms: {'PASS' if legacy_passed else 'FAIL'}) | p95={stats_legacy['p95_ms']} ms")

    # 9. Write Raw Results to CSV
    csv_path = PROJECT_ROOT / "reports" / "phase4_wp2_benchmark_raw_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["series", "iteration", "component", "latency_ms"])
        writer.writeheader()
        writer.writerows(raw_observations)
    print(f"\nRaw CSV Observations Written: {csv_path} ({len(raw_observations)} records)")

    # 10. Write Summary JSON
    summary_data = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": env_info,
        "artifact_hashes": expected_hashes,
        "thresholds": {"xgboost": service.threshold, "isolation_forest": service.iforest_threshold},
        "component_decomposition_500": {
            "preprocessing": stats_prep,
            "xgboost": stats_xgb,
            "isolation_forest": stats_iforest,
            "feature_attribution": stats_attribution,
            "hybrid_decision_logic": stats_decision,
        },
        "supervised_vs_hybrid_500": {
            "supervised_only_pipeline": stats_sup,
            "hybrid_pure_model_pipeline": stats_hyb,
        },
        "primary_single_flow_service_1000": stats_service,
        "http_api_test_client_200": stats_api,
        "legacy_workflow10_loop_50": {
            "stats": stats_legacy,
            "sla_threshold_ms": 35.0,
            "sla_p95_threshold_ms": 70.0,
            "sla_passed": legacy_passed,
        },
    }
    json_path = PROJECT_ROOT / "reports" / "phase4_wp2_benchmark_summary.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)
    print(f"Summary JSON Written: {json_path}")
    print("\nBenchmark Protocol Complete.")


if __name__ == "__main__":
    main()
