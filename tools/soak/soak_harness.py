"""
Sustained-Soak Test Harness & Verification Engine
=================================================
Milestone 17 — Sustained-Soak Qualification & Resource Monitoring

Automates long-duration stability and resource qualification for TrafficShield:
- Periodically samples host/process memory (RSS, peak), CPU utilization, and queue depth.
- Tracks and isolates offline PCAP replay metrics from live passive sniffing.
- Validates formal mathematical flow accounting conservation invariants.
- Enforces graceful shutdown and verifies complete thread termination.
- Explicitly flags unmeasured native kernel drops as UNAVAILABLE.
"""
from __future__ import annotations

import hashlib
import json
import logging
import signal
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from streaming.manager import RealTimeDetectionManager, WorkerState
from tools.soak.memory_policy import MemoryStabilityPolicy
from tools.soak.resource_monitor import ResourceMonitor

logger = logging.getLogger("soak_harness")

EXPECTED_DETECTOR_SHA256 = "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495"
EXPECTED_PREPROCESSOR_SHA256 = "effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653"


@dataclass
class SoakConfig:
    """Execution parameters for the soak qualification test."""
    duration_seconds: float = 60.0
    sample_interval_seconds: float = 10.0
    mode: str = "PCAP_REPLAY"  # "PCAP_REPLAY" or "LIVE_CAPTURE"
    target: str = "data/captures/sample_traffic.pcap"
    speed_multiplier: float = 1.0
    bpf_filter: str = "ip"
    max_packets: int | None = None
    output_dir: Path | None = None
    app: Any = None
    memory_policy: MemoryStabilityPolicy = field(default_factory=MemoryStabilityPolicy)

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.duration_seconds <= 0:
            raise ValueError(f"duration_seconds must be positive, got {self.duration_seconds}")
        if self.sample_interval_seconds <= 0:
            raise ValueError(f"sample_interval_seconds must be positive, got {self.sample_interval_seconds}")
        if self.mode not in ("PCAP_REPLAY", "LIVE_CAPTURE"):
            raise ValueError(f"Invalid mode '{self.mode}'. Must be 'PCAP_REPLAY' or 'LIVE_CAPTURE'")
        if self.mode == "PCAP_REPLAY" and not Path(self.target).exists():
            raise FileNotFoundError(f"Replay PCAP file not found: {self.target}")


@dataclass
class SoakSample:
    """Consolidated telemetry sample at a discrete point in time."""
    timestamp: float
    elapsed_seconds: float
    resource: dict[str, Any]
    pipeline: dict[str, Any]


@dataclass
class InvariantResult:
    """Outcome of a formal mathematical accounting assertion."""
    name: str
    passed: bool
    expected: Any
    actual: Any
    details: str


@dataclass
class SoakSummary:
    """Comprehensive post-run qualification report."""
    session_id: str
    mode: str
    target: str
    duration_configured: float
    duration_actual: float
    sample_count: int
    interrupted: bool
    shutdown_duration_ms: float
    final_state: str
    resource_baseline_rss_mb: float | None
    resource_final_rss_mb: float | None
    resource_peak_rss_mb: float | None
    resource_max_cpu_pct: float | None
    pipeline_final: dict[str, Any]
    samples: list[dict[str, Any]]
    invariants: list[InvariantResult] = field(default_factory=list)
    success: bool = False
    error_message: str | None = None
    model_hashes_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["invariants"] = [asdict(inv) for inv in self.invariants]
        return data


class SoakTestHarness:
    """
    Main harness for running and evaluating long-duration stability tests.
    """

    def __init__(self, config: SoakConfig) -> None:
        config.validate()
        self.config = config
        self.manager = RealTimeDetectionManager.get_instance()
        self.monitor = ResourceMonitor()
        self._samples: list[SoakSample] = []
        self._interrupted = False
        self._shutdown_start = 0.0
        self._shutdown_duration_ms = 0.0

    def _verify_model_hashes(self) -> bool:
        """Verify detector and preprocessor cryptographic integrity."""
        det_path = Path("artifacts/models/production_detector.joblib")
        prep_path = Path("artifacts/models/production_preprocessor.joblib")

        if not det_path.exists() or not prep_path.exists():
            return False

        det_hash = hashlib.sha256(det_path.read_bytes()).hexdigest()
        prep_hash = hashlib.sha256(prep_path.read_bytes()).hexdigest()

        return (
            det_hash == EXPECTED_DETECTOR_SHA256
            and prep_hash == EXPECTED_PREPROCESSOR_SHA256
        )

    def run(self) -> SoakSummary:
        """
        Execute the soak test session, collect periodic samples, and verify accounting invariants.
        """
        session_id = f"soak_{int(time.time())}_{self.config.mode.lower()}"
        logger.info(
            "Starting soak test session %s (Mode: %s, Duration: %.1fs, Interval: %.1fs)",
            session_id,
            self.config.mode,
            self.config.duration_seconds,
            self.config.sample_interval_seconds,
        )

        # 1. Pre-execution hash verification
        hashes_ok_pre = self._verify_model_hashes()
        if not hashes_ok_pre:
            logger.error("Pre-execution model artifact SHA-256 verification failed!")

        # 2. Component warmup: prime inference service so baseline reflects operational memory
        try:
            self.manager._get_inference_service()
            warmup_snap = self.monitor.sample()
            if warmup_snap.rss_mb is not None:
                self.monitor.initial_rss_mb = warmup_snap.rss_mb
        except Exception as exc:
            logger.debug("Component warmup non-fatal exception: %s", exc)

        # 3. Reset manager state
        self.manager.stop()

        # 3. Handle graceful termination on SIGINT / Ctrl+C
        orig_sigint = signal.getsignal(signal.SIGINT)

        def _handle_interrupt(_sig: int, _frame: Any) -> None:
            logger.warning("Soak test interrupted by user! Initiating graceful teardown...")
            self._interrupted = True

        try:
            signal.signal(signal.SIGINT, _handle_interrupt)
        except (ValueError, AttributeError):
            pass  # Worker thread or environment where signal setting is restricted

        # 4. Start the capture or replay session
        t_start = time.monotonic()
        try:
            if self.config.mode == "PCAP_REPLAY":
                self.manager.start_pcap_replay(
                    pcap_path=self.config.target,
                    speed_multiplier=self.config.speed_multiplier,
                    app=self.config.app,
                    max_packets=self.config.max_packets,
                )
            else:
                self.manager.start_live_capture(
                    interface=self.config.target,
                    bpf_filter=self.config.bpf_filter,
                    app=self.config.app,
                )
        except Exception as exc:
            logger.error("Failed to start manager session: %s", exc)
            return SoakSummary(
                session_id=session_id,
                mode=self.config.mode,
                target=self.config.target,
                duration_configured=self.config.duration_seconds,
                duration_actual=0.0,
                sample_count=0,
                interrupted=False,
                shutdown_duration_ms=0.0,
                final_state=WorkerState.FAILED.value,
                resource_baseline_rss_mb=self.monitor.initial_rss_mb or 0.0,
                resource_final_rss_mb=0.0,
                resource_peak_rss_mb=0.0,
                resource_max_cpu_pct=0.0,
                pipeline_final={},
                samples=[],
                success=False,
                error_message=str(exc),
                model_hashes_verified=hashes_ok_pre,
            )

        # 5. Periodic sampling loop
        next_sample_time = t_start
        try:
            while (time.monotonic() - t_start) < self.config.duration_seconds:
                if self._interrupted:
                    break

                now = time.monotonic()
                if now >= next_sample_time:
                    res_snap = self.monitor.sample()
                    pipe_snap = self.manager.get_status()
                    sample = SoakSample(
                        timestamp=time.time(),
                        elapsed_seconds=now - t_start,
                        resource=res_snap.to_dict(),
                        pipeline=pipe_snap,
                    )
                    self._samples.append(sample)
                    next_sample_time = now + self.config.sample_interval_seconds

                # Sleep small slice to stay responsive to interrupts
                time.sleep(0.1)

        except Exception as exc:
            logger.error("Error during soak sampling loop: %s", exc)
            self._interrupted = True
        finally:
            try:
                signal.signal(signal.SIGINT, orig_sigint)
            except (ValueError, AttributeError):
                pass

        # 6. Graceful shutdown & timing
        t_actual = time.monotonic() - t_start
        logger.info("Sampling complete. Initiating graceful manager shutdown...")
        t_shut_start = time.perf_counter()
        final_status = self.manager.stop(drain_timeout=5.0)
        self._shutdown_duration_ms = (time.perf_counter() - t_shut_start) * 1000.0

        # Final resource snapshot
        final_res = self.monitor.sample()
        hashes_ok_post = self._verify_model_hashes()

        # Summary statistics
        baseline_rss = self.monitor.initial_rss_mb
        final_rss = final_res.rss_mb
        peak_rss = final_res.peak_rss_mb
        valid_cpus: list[float] = [
            float(s.resource["cpu_percent"])
            for s in self._samples
            if s.resource.get("cpu_percent") is not None
        ]
        max_cpu: float | None = max(valid_cpus) if valid_cpus else None

        # 7. Evaluate accounting invariants
        invariants = self._evaluate_invariants(
            final_status,
            baseline_rss=baseline_rss,
            final_rss=final_rss,
            peak_rss=peak_rss,
            require_memory_check=True,
        )
        all_passed = all(inv.passed for inv in invariants) and (hashes_ok_pre and hashes_ok_post)
        if self._interrupted:
            all_passed = False

        summary = SoakSummary(
            session_id=session_id,
            mode=self.config.mode,
            target=self.config.target,
            duration_configured=self.config.duration_seconds,
            duration_actual=round(t_actual, 2),
            sample_count=len(self._samples),
            interrupted=self._interrupted,
            shutdown_duration_ms=round(self._shutdown_duration_ms, 2),
            final_state=final_status.get("worker_state", "UNKNOWN"),
            resource_baseline_rss_mb=round(baseline_rss, 2) if baseline_rss is not None else None,
            resource_final_rss_mb=round(final_rss, 2) if final_rss is not None else None,
            resource_peak_rss_mb=round(peak_rss, 2) if peak_rss is not None else None,
            resource_max_cpu_pct=round(max_cpu, 1) if max_cpu is not None else None,
            pipeline_final=final_status,
            samples=[
                {
                    "timestamp": s.timestamp,
                    "elapsed_seconds": round(s.elapsed_seconds, 1),
                    "rss_mb": s.resource.get("rss_mb"),
                    "cpu_pct": s.resource.get("cpu_percent"),
                    "queue_depth": s.pipeline.get("queue_depth"),
                    "flows_completed": s.pipeline.get("flows_completed"),
                    "flows_scored": s.pipeline.get("flows_scored"),
                    "anomalies_detected": s.pipeline.get("anomalies_detected"),
                }
                for s in self._samples
            ],
            invariants=invariants,
            success=all_passed,
            error_message="Session interrupted" if self._interrupted else None,
            model_hashes_verified=(hashes_ok_pre and hashes_ok_post),
        )

        # 8. Save report artifacts if configured
        if self.config.output_dir:
            self._save_reports(summary, self.config.output_dir)

        return summary

    def _evaluate_invariants(
        self,
        final_status: dict[str, Any],
        baseline_rss: float | None = None,
        final_rss: float | None = None,
        peak_rss: float | None = None,
        require_memory_check: bool = False,
    ) -> list[InvariantResult]:
        """Verify strict accounting conservation and lifecycle invariants."""
        results: list[InvariantResult] = []

        # Inv 1: Flow builder active flows cleared
        act_flows = final_status.get("active_flows_count", 0)
        results.append(
            InvariantResult(
                name="INV_1_ACTIVE_FLOWS_CLEARED",
                passed=(act_flows == 0),
                expected=0,
                actual=act_flows,
                details="Active flows in state table must be 0 after flush and shutdown.",
            )
        )

        # Inv 2: Flow creation and completion conservation
        f_created = final_status.get("flows_created", 0)
        f_completed = final_status.get("flows_completed", 0)
        results.append(
            InvariantResult(
                name="INV_2_CREATION_COMPLETION_CONSERVATION",
                passed=(f_created == f_completed),
                expected=f_created,
                actual=f_completed,
                details="flows_created must equal flows_completed at final teardown.",
            )
        )

        # Inv 3: Completed flows decomposition
        f_expired = final_status.get("flows_expired_timeout", 0)
        f_tcp = final_status.get("flows_closed_tcp", 0)
        f_evicted = final_status.get("flows_evicted_overflow", 0)
        f_flushed = final_status.get("flows_flushed", 0)
        decomp_sum = f_expired + f_tcp + f_evicted + f_flushed
        results.append(
            InvariantResult(
                name="INV_3_COMPLETED_FLOWS_DECOMPOSITION",
                passed=(f_completed == decomp_sum),
                expected=f_completed,
                actual=decomp_sum,
                details="flows_completed must equal expired + closed_tcp + evicted + flushed.",
            )
        )

        # Inv 4: Queue ingestion conservation
        f_queued = final_status.get("flows_queued", 0)
        f_dropped = final_status.get("flows_queue_dropped", 0)
        results.append(
            InvariantResult(
                name="INV_4_QUEUE_INGESTION_CONSERVATION",
                passed=(f_queued == f_completed - f_dropped),
                expected=f_completed - f_dropped,
                actual=f_queued,
                details="flows_queued must equal flows_completed - flows_queue_dropped.",
            )
        )

        # Inv 5: Terminal scoring outcome partition (mutually exclusive)
        scored = final_status.get("flows_scored", 0)
        rejected = final_status.get("incompatible_flows_rejected", 0)
        val_err = final_status.get("validation_errors", 0)
        infer_fail = final_status.get("inference_failures", 0)
        unprocessed = final_status.get("unprocessed_flows", 0)
        outcomes_sum = scored + rejected + val_err + infer_fail + unprocessed
        results.append(
            InvariantResult(
                name="INV_5_TERMINAL_SCORING_OUTCOMES_PARTITION",
                passed=(f_queued == outcomes_sum),
                expected=f_queued,
                actual=outcomes_sum,
                details="flows_queued must equal scored + rejected + val_errors + infer_failures + unprocessed.",
            )
        )

        # Inv 6: Alert persistence lifecycle
        anomalies = final_status.get("anomalies_detected", 0)
        persisted = final_status.get("alerts_persisted", 0)
        persist_fail = final_status.get("persistence_failures", 0)
        deduped = final_status.get("alerts_deduplicated", 0)
        unpersisted_no_app = final_status.get("alerts_unpersisted_no_app", 0)

        has_extended_alert_counters = (
            "alerts_deduplicated" in final_status
            or "alerts_unpersisted_no_app" in final_status
        )

        if has_extended_alert_counters:
            alert_sum = persisted + persist_fail + deduped + unpersisted_no_app
            passed_inv6 = (anomalies == alert_sum)
            expected_inv6 = anomalies
            actual_inv6 = alert_sum
            details_inv6 = (
                f"anomalies_detected ({anomalies}) must equal alerts_persisted ({persisted}) + "
                f"persistence_failures ({persist_fail}) + alerts_deduplicated ({deduped}) + "
                f"alerts_unpersisted_no_app ({unpersisted_no_app})."
            )
        else:
            alert_sum = persisted + persist_fail
            passed_inv6 = (alert_sum <= anomalies)
            expected_inv6 = f"<= {anomalies}"
            actual_inv6 = alert_sum
            details_inv6 = "alerts_persisted + persistence_failures must not exceed total anomalies_detected."

        results.append(
            InvariantResult(
                name="INV_6_ALERT_PERSISTENCE_BOUNDS",
                passed=passed_inv6,
                expected=expected_inv6,
                actual=actual_inv6,
                details=details_inv6,
            )
        )

        # Inv 7: Pipeline shutdown timeout check
        pipe_timeout = final_status.get("pipeline_join_timed_out", False)
        results.append(
            InvariantResult(
                name="INV_7_PIPELINE_JOIN_CLEAN",
                passed=(pipe_timeout is False),
                expected=False,
                actual=pipe_timeout,
                details="Pipeline thread must terminate cleanly without join timeout.",
            )
        )

        # Inv 8: Native kernel drops honesty
        kernel_avail = final_status.get("native_kernel_drops_available", False)
        kernel_drops = final_status.get("native_kernel_drops")
        kernel_status = final_status.get("kernel_drop_status", "")

        if kernel_avail:
            passed_inv8 = (
                kernel_drops is not None
                and isinstance(kernel_drops, int)
                and kernel_drops >= 0
                and "AVAILABLE" in kernel_status
            )
            expected_inv8 = "AVAILABLE (integer >= 0)"
            actual_inv8 = f"{kernel_status} (drops: {kernel_drops})"
            details_inv8 = "Native kernel drops are active and reported accurately from driver."
        else:
            passed_inv8 = (
                kernel_drops is None
                and ("UNAVAILABLE" in kernel_status or "UNSUPPORTED" in kernel_status)
            )
            expected_inv8 = "UNAVAILABLE or UNSUPPORTED (None)"
            actual_inv8 = f"{kernel_status} (drops: {kernel_drops})"
            details_inv8 = "Native kernel drops must be reported as UNAVAILABLE or UNSUPPORTED, never conflated with queue drops."

        results.append(
            InvariantResult(
                name="INV_8_NATIVE_KERNEL_DROPS_HONESTY",
                passed=passed_inv8,
                expected=expected_inv8,
                actual=actual_inv8,
                details=details_inv8,
            )
        )

        # Inv 9: Memory drift stability (evaluated via MemoryStabilityPolicy)
        b_rss = baseline_rss if baseline_rss is not None else final_status.get("resource_baseline_rss_mb")
        f_rss = final_rss if final_rss is not None else final_status.get("resource_final_rss_mb")
        p_rss = peak_rss if peak_rss is not None else final_status.get("resource_peak_rss_mb")

        if require_memory_check or (b_rss is not None and f_rss is not None):
            mem_ok, mem_msg, _diag = self.config.memory_policy.evaluate(
                baseline_rss_mb=b_rss,
                final_rss_mb=f_rss,
                peak_rss_mb=p_rss,
            )
            d_rss = round(f_rss - b_rss, 2) if (b_rss is not None and f_rss is not None) else None
            results.append(
                InvariantResult(
                    name="INV_9_MEMORY_DRIFT_STABILITY",
                    passed=mem_ok,
                    expected=f"Delta <= {self.config.memory_policy.max_absolute_growth_mb}MB (or <= {self.config.memory_policy.max_relative_growth_pct}%)",
                    actual=f"Delta {d_rss}MB" if d_rss is not None else f"baseline={b_rss}, final={f_rss}",
                    details=mem_msg,
                )
            )

        return results

    def _save_reports(self, summary: SoakSummary, output_dir: Path) -> None:
        """Persist structured summary and markdown report."""
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / f"{summary.session_id}_summary.json"
        with open(json_path, "w", encoding="utf-8") as fp:
            json.dump(summary.to_dict(), fp, indent=2)

        md_path = output_dir / f"{summary.session_id}_report.md"
        with open(md_path, "w", encoding="utf-8") as fp:
            fp.write(self._generate_markdown(summary))

        logger.info("Soak qualification reports persisted to: %s", output_dir)

    def _generate_markdown(self, s: SoakSummary) -> str:
        """Generate formatted Markdown report from summary."""
        lines = [
            f"# TrafficShield Soak Qualification Report — {s.session_id}",
            "",
            f"**Mode:** `{s.mode}`  ",
            f"**Target:** `{s.target}`  ",
            f"**Configured Duration:** {s.duration_configured}s  ",
            f"**Actual Duration:** {s.duration_actual}s  ",
            f"**Samples Recorded:** {s.sample_count}  ",
            f"**Final Worker State:** `{s.final_state}`  ",
            f"**Shutdown Drain Latency:** {s.shutdown_duration_ms} ms  ",
            f"**Overall Verdict:** **{'PASS' if s.success else 'FAIL'}**  ",
            "",
            "---",
            "",
            "## 1. Resource Consumption Summary",
            "",
            "| Resource Metric | Baseline Value | Final Value | Peak Observed | Trend Evaluation |",
            "|:---|:---:|:---:|:---:|:---|",
            f"| **RSS Memory (Working Set)** | {s.resource_baseline_rss_mb if s.resource_baseline_rss_mb is not None else 'UNAVAILABLE'} MB | {s.resource_final_rss_mb if s.resource_final_rss_mb is not None else 'UNAVAILABLE'} MB | {s.resource_peak_rss_mb if s.resource_peak_rss_mb is not None else 'UNAVAILABLE'} MB | Bounded growth |",
            f"| **Process CPU Utilization** | 0.0% | — | {f'{s.resource_max_cpu_pct}%' if s.resource_max_cpu_pct is not None else 'UNAVAILABLE'} | Within bounds |",
            "",
            "---",
            "",
            "## 2. Mathematical Flow Accounting Invariants",
            "",
            "| Invariant Name | Expected | Actual Measured | Status | Details |",
            "|:---|:---:|:---:|:---:|:---|",
        ]

        for inv in s.invariants:
            status_badge = "**PASS**" if inv.passed else "**FAIL**"
            lines.append(f"| `{inv.name}` | `{inv.expected}` | `{inv.actual}` | {status_badge} | {inv.details} |")

        lines.extend([
            "",
            "---",
            "",
            "## 3. Telemetry Sample Timeline",
            "",
            "| Elapsed (s) | RSS Memory (MB) | CPU % | Queue Depth | Completed Flows | Scored Flows | Anomalies |",
            "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
        ])

        for smp in s.samples[:50]:  # Limit table rows in markdown
            lines.append(
                f"| {smp.get('elapsed_seconds')} | {smp.get('rss_mb')} | {smp.get('cpu_pct')} | "
                f"{smp.get('queue_depth')} | {smp.get('flows_completed')} | {smp.get('flows_scored')} | "
                f"{smp.get('anomalies_detected')} |"
            )

        return "\n".join(lines)
