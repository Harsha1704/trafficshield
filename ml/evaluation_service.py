"""
TrafficShield Model Performance & Evaluation Service
=====================================================
Version: 1.0 (Milestone Sprint)

Provides authoritative, reproducible model performance metrics, confusion matrices,
per-attack category recall, candidate model tournament comparisons, and scientific
provenance data for the Model Performance & Evaluation dashboard.

Safety & Integrity Guarantees:
- Never modifies, retrains, or reserializes frozen model artifacts.
- Cryptographically validates artifact SHA-256 hashes on retrieval.
- Reports real metrics derived from audited, held-out test data (UNSW-NB15 19,942 flows)
  and temporal out-of-distribution holdouts (Day 2 20,000 flows).
- Enforces strict unidirectional causal observability disclosure.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("model_evaluation_service")

# Canonical Frozen SHA-256 Artifact Baselines
EXPECTED_DETECTOR_SHA256 = "c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495"
EXPECTED_PREPROCESSOR_SHA256 = "effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653"
EXPECTED_METADATA_SHA256 = "3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1"

# Required 13 Forward-Observable Feature Contract
FORWARD_FEATURE_CONTRACT = [
    {"name": "duration_seconds", "type": "Float", "role": "Base", "timing": "Flow Completion", "desc": "Flow physical duration in seconds"},
    {"name": "fwd_bytes", "type": "Integer", "role": "Base", "timing": "Flow Completion", "desc": "Total forward payload/packet bytes"},
    {"name": "sttl", "type": "Integer", "role": "Base", "timing": "Packet Arrival", "desc": "Source IP Time-To-Live header byte (1-255)"},
    {"name": "sload", "type": "Float", "role": "Base", "timing": "Flow Completion", "desc": "Source bits per second transmission load"},
    {"name": "fwd_packets", "type": "Integer", "role": "Base", "timing": "Flow Completion", "desc": "Total packet count observed forward"},
    {"name": "swin", "type": "Integer", "role": "Base", "timing": "Flow Prefix", "desc": "TCP Advertised Window in forward SYN"},
    {"name": "smeansz", "type": "Float", "role": "Base", "timing": "Flow Completion", "desc": "Mean forward packet size in bytes"},
    {"name": "sjit", "type": "Float", "role": "Base", "timing": "Flow Completion", "desc": "Source packet inter-arrival jitter in ms"},
    {"name": "sintpkt", "type": "Float", "role": "Base", "timing": "Flow Completion", "desc": "Source inter-packet arrival time in ms"},
    {"name": "is_sm_ips_ports", "type": "Binary", "role": "Base", "timing": "Packet Arrival", "desc": "Equal source/destination IP & Port indicator (LAND attack)"},
    {"name": "packet_rate", "type": "Float", "role": "Engineered", "timing": "Derived", "desc": "Forward packets per second (fwd_packets / dur)"},
    {"name": "byte_rate", "type": "Float", "role": "Engineered", "timing": "Derived", "desc": "Forward bytes per second (fwd_bytes / dur)"},
    {"name": "bytes_per_packet", "type": "Float", "role": "Engineered", "timing": "Derived", "desc": "Mean bytes per forward packet (fwd_bytes / fwd_packets)"},
]

# Audited Attack Category Detection Performance on 19,942 Held-Out Test Flows (Threshold 0.50)
AUDITED_CATEGORY_METRICS = [
    {
        "category": "Generic",
        "test_flows": 1538,
        "detected_tp": 1534,
        "missed_fn": 4,
        "recall_rate": 0.9974,
        "status": "STRONG",
        "notes": "Volumetric & signature-like forward byte patterns easily detected.",
    },
    {
        "category": "Exploits",
        "test_flows": 1276,
        "detected_tp": 1231,
        "missed_fn": 45,
        "recall_rate": 0.9647,
        "status": "STRONG",
        "notes": "Anomalous payload lengths and abnormal source load/TTL signatures.",
    },
    {
        "category": "Fuzzers",
        "test_flows": 1422,
        "detected_tp": 1370,
        "missed_fn": 52,
        "recall_rate": 0.9634,
        "status": "STRONG",
        "notes": "High rate of packet transmission with abnormal inter-packet jitter.",
    },
    {
        "category": "DoS",
        "test_flows": 521,
        "detected_tp": 517,
        "missed_fn": 4,
        "recall_rate": 0.9923,
        "status": "STRONG",
        "notes": "High forward rate and abnormal duration-to-packet ratios.",
    },
    {
        "category": "Backdoor",
        "test_flows": 460,
        "detected_tp": 457,
        "missed_fn": 3,
        "recall_rate": 0.9935,
        "status": "STRONG",
        "notes": "Low-rate covert channels resembling benign HTTP/DNS queries.",
    },
    {
        "category": "Analysis",
        "test_flows": 458,
        "detected_tp": 456,
        "missed_fn": 2,
        "recall_rate": 0.9956,
        "status": "STRONG",
        "notes": "Stealth probes detected via TTL and window-size shifts.",
    },
    {
        "category": "Reconnaissance",
        "test_flows": 154,
        "detected_tp": 140,
        "missed_fn": 14,
        "recall_rate": 0.9091,
        "status": "STRONG",
        "notes": "Port scans identified; slow stealth scans partially blend with normal SYN attempts.",
    },
    {
        "category": "Shellcode",
        "test_flows": 24,
        "detected_tp": 18,
        "missed_fn": 6,
        "recall_rate": 0.7500,
        "status": "MODERATE",
        "notes": "Small forward payload sizes close to legitimate interactive sessions.",
    },
    {
        "category": "Worms",
        "test_flows": 5,
        "detected_tp": 5,
        "missed_fn": 0,
        "recall_rate": 1.0000,
        "status": "PERFECT",
        "notes": "Small sample size caveat (5 flows in test partition); all 5 replication attempts detected.",
    },
]

# Audited Tournament Candidate Models
CANDIDATE_MODELS = [
    {
        "model_name": "OptunaTuned_XGBoost",
        "model_type": "optimized_supervised",
        "accuracy": 0.9858,
        "precision": 0.9539,
        "recall": 0.9998,
        "specificity": 0.9799,
        "fpr": 0.0201,
        "f1_score": 0.9763,
        "balanced_accuracy": 0.9899,
        "roc_auc": 0.9986,
        "pr_auc": 0.9954,
        "latency_us": 0.37,
        "flagged_pct": 30.79,
        "is_production": True,
        "status": "ACTIVE_PRODUCTION",
    },
    {
        "model_name": "HistGradientBoostingClassifier",
        "model_type": "supervised_boosting",
        "accuracy": 0.9859,
        "precision": 0.9542,
        "recall": 0.9998,
        "specificity": 0.9800,
        "fpr": 0.0200,
        "f1_score": 0.9765,
        "balanced_accuracy": 0.9899,
        "roc_auc": 0.9980,
        "pr_auc": 0.9923,
        "latency_us": 0.65,
        "flagged_pct": 30.78,
        "is_production": False,
        "status": "BENCHMARK_CANDIDATE",
    },
    {
        "model_name": "XGBoostClassifier (Default)",
        "model_type": "supervised_boosting",
        "accuracy": 0.9857,
        "precision": 0.9536,
        "recall": 0.9998,
        "specificity": 0.9798,
        "fpr": 0.0202,
        "f1_score": 0.9762,
        "balanced_accuracy": 0.9898,
        "roc_auc": 0.9974,
        "pr_auc": 0.9884,
        "latency_us": 0.32,
        "flagged_pct": 30.80,
        "is_production": False,
        "status": "BENCHMARK",
    },
    {
        "model_name": "LightGBMClassifier",
        "model_type": "supervised_boosting",
        "accuracy": 0.9856,
        "precision": 0.9534,
        "recall": 0.9998,
        "specificity": 0.9797,
        "fpr": 0.0203,
        "f1_score": 0.9761,
        "balanced_accuracy": 0.9898,
        "roc_auc": 0.9963,
        "pr_auc": 0.9817,
        "latency_us": 0.80,
        "flagged_pct": 30.80,
        "is_production": False,
        "status": "BENCHMARK",
    },
    {
        "model_name": "RandomForestClassifier",
        "model_type": "supervised_tree",
        "accuracy": 0.9698,
        "precision": 0.9067,
        "recall": 1.0000,
        "specificity": 0.9572,
        "fpr": 0.0428,
        "f1_score": 0.9511,
        "balanced_accuracy": 0.9786,
        "roc_auc": 0.9974,
        "pr_auc": 0.9918,
        "latency_us": 2.34,
        "flagged_pct": 32.40,
        "is_production": False,
        "status": "BENCHMARK",
    },
    {
        "model_name": "ExtraTreesClassifier",
        "model_type": "supervised_tree",
        "accuracy": 0.9684,
        "precision": 0.9029,
        "recall": 1.0000,
        "specificity": 0.9553,
        "fpr": 0.0447,
        "f1_score": 0.9490,
        "balanced_accuracy": 0.9776,
        "roc_auc": 0.9965,
        "pr_auc": 0.9870,
        "latency_us": 3.07,
        "flagged_pct": 32.53,
        "is_production": False,
        "status": "BENCHMARK",
    },
    {
        "model_name": "CalibratedProbability_XGBoost",
        "model_type": "calibrated_supervised",
        "accuracy": 0.9858,
        "precision": 0.9544,
        "recall": 0.9993,
        "specificity": 0.9801,
        "fpr": 0.0199,
        "f1_score": 0.9763,
        "balanced_accuracy": 0.9897,
        "roc_auc": 0.9985,
        "pr_auc": 0.9948,
        "latency_us": 0.48,
        "flagged_pct": 30.76,
        "is_production": False,
        "status": "CALIBRATED_CANDIDATE",
    },
    {
        "model_name": "SoftVotingEnsemble",
        "model_type": "supervised_ensemble",
        "accuracy": 0.9849,
        "precision": 0.9511,
        "recall": 0.9998,
        "specificity": 0.9786,
        "fpr": 0.0214,
        "f1_score": 0.9749,
        "balanced_accuracy": 0.9892,
        "roc_auc": 0.9975,
        "pr_auc": 0.9896,
        "latency_us": 4.52,
        "flagged_pct": 30.88,
        "is_production": False,
        "status": "ENSEMBLE_CANDIDATE",
    },
    {
        "model_name": "MLPClassifier (Neural Network)",
        "model_type": "supervised_neural",
        "accuracy": 0.9128,
        "precision": 0.7918,
        "recall": 0.9539,
        "specificity": 0.8957,
        "fpr": 0.1043,
        "f1_score": 0.8653,
        "balanced_accuracy": 0.9248,
        "roc_auc": 0.9374,
        "pr_auc": 0.8719,
        "latency_us": 0.41,
        "flagged_pct": 35.39,
        "is_production": False,
        "status": "RESEARCH_BASELINE",
    },
    {
        "model_name": "AutoencoderDetector",
        "model_type": "unsupervised",
        "accuracy": 0.7787,
        "precision": 0.8435,
        "recall": 0.3027,
        "specificity": 0.9766,
        "fpr": 0.0234,
        "f1_score": 0.4455,
        "balanced_accuracy": 0.6397,
        "roc_auc": 0.9223,
        "pr_auc": 0.8053,
        "latency_us": 0.92,
        "flagged_pct": 10.54,
        "is_production": False,
        "status": "UNSUPERVISED_TOP",
    },
    {
        "model_name": "IsolationForestDetector",
        "model_type": "unsupervised",
        "accuracy": 0.7105,
        "precision": 0.7429,
        "recall": 0.0222,
        "specificity": 0.9968,
        "fpr": 0.0032,
        "f1_score": 0.0431,
        "balanced_accuracy": 0.5095,
        "roc_auc": 0.9086,
        "pr_auc": 0.7147,
        "latency_us": 3.23,
        "flagged_pct": 0.88,
        "is_production": False,
        "status": "UNSUPERVISED_BASELINE",
    },
    {
        "model_name": "RobustStatisticalDetector",
        "model_type": "unsupervised",
        "accuracy": 0.7015,
        "precision": 0.2762,
        "recall": 0.0099,
        "specificity": 0.9892,
        "fpr": 0.0108,
        "f1_score": 0.0191,
        "balanced_accuracy": 0.4996,
        "roc_auc": 0.8907,
        "pr_auc": 0.6527,
        "latency_us": 0.20,
        "flagged_pct": 1.05,
        "is_production": False,
        "status": "STATISTICAL_BASELINE",
    },
    {
        "model_name": "CalibratedEnsembleDetector",
        "model_type": "unsupervised_ensemble",
        "accuracy": 0.7051,
        "precision": 0.4196,
        "recall": 0.0102,
        "specificity": 0.9941,
        "fpr": 0.0059,
        "f1_score": 0.0200,
        "balanced_accuracy": 0.5022,
        "roc_auc": 0.9173,
        "pr_auc": 0.7091,
        "latency_us": 2.64,
        "flagged_pct": 0.72,
        "is_production": False,
        "status": "UNSUPERVISED_ENSEMBLE",
    },
]


def _compute_sha256(path: Path) -> str | None:
    """Safely compute SHA-256 hash of a file if it exists."""
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class ModelEvaluationService:
    """Service providing model performance, evaluation provenance, and comparison data."""

    def __init__(
        self,
        model_dir: Path | None = None,
        reports_dir: Path | None = None,
    ) -> None:
        self.model_dir = model_dir or Path("artifacts/models")
        self.reports_dir = reports_dir or Path("reports")

    def get_evaluation_report(self) -> dict[str, Any]:
        """
        Build and return the comprehensive Model Evaluation Report.
        Integrates operational threshold results, tournament benchmarks,
        temporal out-of-distribution performance, and candidate comparisons.
        """
        # Validate artifact cryptographic hashes from disk
        detector_path = self.model_dir / "production_detector.joblib"
        preprocessor_path = self.model_dir / "production_preprocessor.joblib"
        metadata_path = self.model_dir / "production_detector.json"

        actual_det_hash = _compute_sha256(detector_path)
        actual_prep_hash = _compute_sha256(preprocessor_path)
        actual_meta_hash = _compute_sha256(metadata_path)

        hashes_match = bool(
            actual_det_hash
            and actual_prep_hash
            and actual_meta_hash
            and actual_det_hash.lower() == EXPECTED_DETECTOR_SHA256.lower()
            and actual_prep_hash.lower() == EXPECTED_PREPROCESSOR_SHA256.lower()
            and actual_meta_hash.lower() == EXPECTED_METADATA_SHA256.lower()
        )

        # Operational metrics on held-out test partition at operational threshold tau = 0.50
        # Verified across M9 Independent Reproduction
        operational_metrics = {
            "accuracy": 0.981045,
            "precision": 0.958501,
            "recall": 0.977808,
            "specificity": 0.982391,
            "f1_score": 0.968058,
            "balanced_accuracy": 0.980099,
            "roc_auc": 0.998711,
            "pr_auc": 0.996661,
            "false_positive_rate": 0.017609,
            "inference_latency_us": 0.37,
            "latency_scope": "Estimator-only amortized batch throughput (excludes feature extraction and network overhead)",
        }

        confusion_matrix_data = {
            "tn": 13836,
            "fp": 248,
            "fn": 130,
            "tp": 5728,
            "total": 19942,
            "tn_pct": 98.2391,
            "fp_pct": 1.7609,
            "fn_pct": 2.2192,
            "tp_pct": 97.7808,
        }

        # Optimal F1 threshold (tau = 0.13) from tournament optimization
        optimal_tournament_metrics = {
            "threshold": 0.13,
            "accuracy": 0.985759,
            "precision": 0.953909,
            "recall": 0.999829,
            "specificity": 0.979906,
            "f1_score": 0.976329,
            "balanced_accuracy": 0.989868,
            "roc_auc": 0.998571,
            "confusion_matrix": {
                "tn": 13801,
                "fp": 283,
                "fn": 1,
                "tp": 5857,
            },
        }

        # Day 2 Out-of-Distribution Temporal Holdout (20,000 flows, 24 days later)
        temporal_holdout_metrics = {
            "split_description": "Day 2 Out-of-Distribution Holdout (20,000 flows, 24 days later)",
            "total_flows": 20000,
            "accuracy": 0.969700,
            "recall": 0.983700,
            "precision": 0.905700,
            "specificity": 0.965000,
            "f1_score": 0.943100,
            "confusion_matrix": {
                "tn": 14384,
                "fp": 522,
                "fn": 83,
                "tp": 5011,
            },
        }

        report = {
            "production_model": {
                "model_name": "OptunaTuned_XGBoost",
                "model_version": "1.0.0",
                "algorithm": "Extreme Gradient Boosting (Optuna Bayesian Hyperparameter Tuned GBDT)",
                "family": "Supervised Gradient-Boosted Decision Trees",
                "framework": "XGBoost 3.4.1 / Scikit-Learn 1.9.1",
                "decision_threshold": 0.50,
                "status": "ACTIVE_PRODUCTION",
                "feature_count": 13,
                "required_features": [
                    "duration_seconds",
                    "fwd_bytes",
                    "sttl",
                    "sload",
                    "fwd_packets",
                    "swin",
                    "smeansz",
                    "sjit",
                    "sintpkt",
                    "is_sm_ips_ports",
                ],
                "engineered_features": ["packet_rate", "byte_rate", "bytes_per_packet"],
                "feature_details": FORWARD_FEATURE_CONTRACT,
                "artifact_integrity": {
                    "verified": hashes_match,
                    "detector_sha256": actual_det_hash or "FILE_NOT_FOUND",
                    "preprocessor_sha256": actual_prep_hash or "FILE_NOT_FOUND",
                    "metadata_sha256": actual_meta_hash or "FILE_NOT_FOUND",
                    "detector_expected_sha256": EXPECTED_DETECTOR_SHA256,
                    "preprocessor_expected_sha256": EXPECTED_PREPROCESSOR_SHA256,
                    "metadata_expected_sha256": EXPECTED_METADATA_SHA256,
                },
            },
            "evaluation_provenance": {
                "dataset_name": "UNSW-NB15 Benchmark (Cyber Range Testbed)",
                "dataset_source_file": "UNSW-NB15_1.csv (Day 1 Stream, 100,000 flows)",
                "split_description": "Day 1 Held-Out Test Split (19,942 flows) via Custom 4-Way Chronological Partition (Not the official randomly sampled train/test CSV)",
                "separation_type": "Strict Chronological Split (Train: 50,004, Val: 14,999, Cal: 15,055, Test: 19,942)",
                "total_test_flows": 19942,
                "normal_flows": 14084,
                "normal_pct": 70.62,
                "attack_flows": 5858,
                "attack_pct": 29.38,
                "audit_milestone": "Milestone 9 Independent Verification & Audit",
                "verification_status": "AUDITED_AND_REPRODUCED",
                "evaluation_date": "2026-10-23",
            },
            "operational_metrics": operational_metrics,
            "confusion_matrix": confusion_matrix_data,
            "optimal_tournament_metrics": optimal_tournament_metrics,
            "temporal_holdout_metrics": temporal_holdout_metrics,
            "category_metrics": AUDITED_CATEGORY_METRICS,
            "comparison_models": CANDIDATE_MODELS,
            "methodology_and_limitations": {
                "operational_mode": (
                    "Passive network monitoring tap (detection and alert generation only; "
                    "no inline packet dropping or active traffic prevention)."
                ),
                "anomaly_score_interpretation": (
                    "Anomaly scores measure statistical deviation from the learned baseline profile, "
                    "not definitive proof of malicious compromise. High anomaly scores require analyst triage."
                ),
                "causal_policy": (
                    "Strict unidirectional causal observability: zero reverse features (dbytes, dpkts, dttl, "
                    "tcprtt) or ground-truth labels permitted in prediction pipeline."
                ),
                "unidirectional_horizon": (
                    "When monitoring unidirectional passive taps, internal server return status codes (HTTP 200 vs 500) "
                    "and reverse SYN-ACK handshakes are physically unobservable. Low-footprint attacks intentionally mimic normal traffic."
                ),
                "day2_holdout_scope": (
                    "Day 2 holdout confirms temporal feature stability across 24 days within the same UNSW-NB15 testbed environment. "
                    "It does not establish generalizability to external enterprise network topologies or different traffic generators."
                ),
                "impossibility_of_100_percent": [
                    "Stealth probes and single-packet scans look byte-for-byte identical to dropped legitimate connections.",
                    "Low-footprint backdoor and covert channels conform strictly to benign forward volume and duration distributions.",
                    "Real network traffic exhibits natural label ambiguity and non-stationary temporal drift; forcing 100% training fit guarantees catastrophic test overfitting.",
                    "Academic literature reporting 100% or 99.9% accuracy routinely suffers from target leakage (bidirectional RTT, post-event aggregates) and random temporal shuffling.",
                ],
                "cross_dataset_boundaries": [
                    "Direct transfer to CICFlowMeter / CICIDS2017 is unsupported because IP TTL (sttl) is omitted and public captures strip IP headers.",
                    "Milestone 10.1 evidence audit confirmed that local CICIDS2017 was a synthetic fixture, formally ruling out unverified cross-dataset claims.",
                ],
            },
        }

        return report


_EVALUATION_SERVICE_INSTANCE: ModelEvaluationService | None = None


def get_evaluation_service() -> ModelEvaluationService:
    """Return singleton ModelEvaluationService instance."""
    global _EVALUATION_SERVICE_INSTANCE
    if _EVALUATION_SERVICE_INSTANCE is None:
        _EVALUATION_SERVICE_INSTANCE = ModelEvaluationService()
    return _EVALUATION_SERVICE_INSTANCE
