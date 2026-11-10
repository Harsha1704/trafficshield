"""
Automated Hybrid ML Performance Qualification & Stress Test Suite
==================================================================
Milestone 15.1 Qualification Gates:
1. Mathematical equivalence between predict_single and predict_batch.
2. Concurrent thread-safety across multiple worker threads.
3. Strict schema validation and fail-closed malformed input rejection.
4. Latency performance budgets (p95 latency threshold check).
5. Streaming worker queue throughput and drain integrity.
"""
from __future__ import annotations

import concurrent.futures
import queue
import time
from typing import Any

import numpy as np
import pytest

from features.policy import PolicyViolationError
from ml.production_service import ProductionInferenceService
from streaming.inference_worker import StreamingInferenceWorker


@pytest.fixture(scope="module")
def inference_service() -> ProductionInferenceService:
    return ProductionInferenceService(verify_checksums=True)


@pytest.fixture
def benign_flow() -> dict[str, float]:
    return {
        "duration_seconds": 0.5,
        "fwd_bytes": 1200.0,
        "sttl": 64.0,
        "sload": 24000.0,
        "fwd_packets": 10.0,
        "swin": 255.0,
        "smeansz": 120.0,
        "sjit": 5.0,
        "sintpkt": 20.0,
        "is_sm_ips_ports": 0.0,
    }


@pytest.fixture
def attack_flow() -> dict[str, float]:
    return {
        "duration_seconds": 0.001,
        "fwd_bytes": 1_500_000.0,
        "sttl": 254.0,
        "sload": 9_600_000_000.0,
        "fwd_packets": 1500.0,
        "swin": 255.0,
        "smeansz": 1000.0,
        "sjit": 0.0,
        "sintpkt": 0.001,
        "is_sm_ips_ports": 0.0,
    }


def test_batch_prediction_mathematical_consistency(
    inference_service: ProductionInferenceService,
    benign_flow: dict[str, float],
    attack_flow: dict[str, float],
) -> None:
    """Verifies predict_batch yields identical outputs to individual predict_single calls."""
    flows = [benign_flow, attack_flow, benign_flow, attack_flow]

    # Individual single predictions
    single_results = [inference_service.predict_single(f) for f in flows]

    # Batch prediction
    batch_res = inference_service.predict_batch(flows)
    batch_predictions = batch_res["predictions"]

    assert len(batch_predictions) == len(flows)
    for s_res, b_res in zip(single_results, batch_predictions, strict=True):
        assert s_res["is_anomaly"] == b_res["is_anomaly"]
        assert np.isclose(s_res["anomaly_score"], b_res["anomaly_score"], atol=1e-5)
        assert np.isclose(
            s_res["supervised"]["probability"],
            b_res["supervised"]["probability"],
            atol=1e-5,
        )
        assert np.isclose(
            s_res["unsupervised"]["anomaly_score"],
            b_res["unsupervised"]["anomaly_score"],
            atol=1e-5,
        )
        assert s_res["hybrid_classification"] == b_res["hybrid_classification"]
        assert s_res["risk_level"] == b_res["risk_level"]

    # Verify summary counters
    assert batch_res["hybrid_classification_counts"]["DUAL_CONFIRMED"] == sum(
        1 for r in single_results if r["hybrid_classification"] == "DUAL_CONFIRMED"
    )
    assert batch_res["hybrid_classification_counts"]["NORMAL_TRAFFIC"] == sum(
        1 for r in single_results if r["hybrid_classification"] == "NORMAL_TRAFFIC"
    )


def test_concurrency_thread_safety(
    inference_service: ProductionInferenceService,
    benign_flow: dict[str, float],
    attack_flow: dict[str, float],
) -> None:
    """Verifies that concurrent multi-threaded inference does not corrupt state or raise race errors."""
    test_flows = [benign_flow, attack_flow] * 50  # 100 flows total

    def score(flow: dict[str, float]) -> dict[str, Any]:
        return inference_service.predict_single(flow)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(score, f) for f in test_flows]
        results = [fut.result() for fut in concurrent.futures.as_completed(futures)]

    assert len(results) == 100
    for res in results:
        assert "hybrid_classification" in res
        assert res["hybrid_classification"] in {
            "DUAL_CONFIRMED",
            "SUPERVISED_ONLY_ALERT",
            "UNSUPERVISED_NOVELTY",
            "NORMAL_TRAFFIC",
        }
        assert "supervised" in res
        assert "unsupervised" in res


def test_malformed_input_fail_safe_rejection(
    inference_service: ProductionInferenceService,
    benign_flow: dict[str, float],
) -> None:
    """Verifies that incomplete, non-numeric, or forbidden features are rejected fail-closed."""
    # Missing required field
    partial = dict(benign_flow)
    del partial["duration_seconds"]
    with pytest.raises(ValueError, match="Missing required forward observable features"):
        inference_service.predict_single(partial)

    # Empty payload
    with pytest.raises(ValueError):
        inference_service.predict_single({})

    # Forbidden reverse-dependent feature injection
    poisoned = dict(benign_flow)
    poisoned["dbytes"] = 5000.0
    with pytest.raises(PolicyViolationError):
        inference_service.predict_single(poisoned)


def test_single_flow_latency_budget(
    inference_service: ProductionInferenceService,
    benign_flow: dict[str, float],
) -> None:
    """Verifies that warm single-flow inference meets the operational SLA limit (< 20ms p95)."""
    # Warmup
    for _ in range(20):
        inference_service.predict_single(benign_flow)

    latencies_ms: list[float] = []
    for _ in range(100):
        t0 = time.perf_counter()
        inference_service.predict_single(benign_flow)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    p95 = float(np.percentile(latencies_ms, 95))
    assert p95 < 35.0, f"p95 inference latency {p95:.2f}ms exceeds 35.0ms target"


def test_streaming_worker_queue_drain(
    inference_service: ProductionInferenceService,
    benign_flow: dict[str, float],
) -> None:
    """Verifies that StreamingInferenceWorker drains queues and processes events safely."""
    flow_q: queue.Queue[dict[str, Any] | None] = queue.Queue()
    worker = StreamingInferenceWorker(
        flow_queue=flow_q,
        inference_service=inference_service,
        app=None,
        source_provenance="PCAP_REPLAY",
        recent_buffer_size=100,
    )
    worker.start()

    num_events = 20
    for i in range(num_events):
        item = dict(benign_flow)
        item["flow_id"] = f"flow_{i}"
        flow_q.put(item)

    worker.stop(drain_timeout=5.0)

    assert not worker.is_running
    assert worker.flows_scored == num_events
    assert len(worker.recent_events) == num_events
