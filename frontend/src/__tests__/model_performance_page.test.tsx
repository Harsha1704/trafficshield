import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ModelPerformancePage } from '../pages/ModelPerformancePage';
import { api } from '../services/api';
import type { ModelEvaluationResponse } from '../types/api';

const mockEvaluationData: ModelEvaluationResponse = {
  production_model: {
    model_name: 'OptunaTuned_XGBoost',
    model_version: '1.0.0',
    algorithm: 'Extreme Gradient Boosting (Optuna Bayesian Hyperparameter Tuned GBDT)',
    family: 'Supervised Gradient-Boosted Decision Trees',
    framework: 'XGBoost 3.4.1 / Scikit-Learn 1.9.1',
    decision_threshold: 0.5,
    status: 'ACTIVE_PRODUCTION',
    feature_count: 13,
    required_features: ['duration_seconds', 'fwd_bytes', 'sttl', 'sload', 'fwd_packets', 'swin', 'smeansz', 'sjit', 'sintpkt', 'is_sm_ips_ports'],
    engineered_features: ['packet_rate', 'byte_rate', 'bytes_per_packet'],
    feature_details: [
      { name: 'duration_seconds', type: 'Float', role: 'Base', timing: 'Flow Completion', desc: 'Flow duration' },
    ],
    artifact_integrity: {
      verified: true,
      detector_sha256: 'c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495',
      preprocessor_sha256: 'effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653',
      metadata_sha256: '3553f1a47c1c2fd67b031cadb42400246997778f8dcf42026e2ebfb882ba73b1',
    },
  },
  evaluation_provenance: {
    dataset_name: 'UNSW-NB15 Benchmark (Cyber Range Testbed)',
    split_description: 'Day 1 Held-Out Test Split (19,942 flows)',
    separation_type: 'Strict Chronological Split',
    total_test_flows: 19942,
    normal_flows: 14084,
    normal_pct: 70.62,
    attack_flows: 5858,
    attack_pct: 29.38,
    audit_milestone: 'Milestone 9 Independent Verification & Audit',
    verification_status: 'AUDITED_AND_REPRODUCED',
    evaluation_date: '2026-10-23',
  },
  operational_metrics: {
    accuracy: 0.981045,
    precision: 0.958501,
    recall: 0.977808,
    specificity: 0.982391,
    f1_score: 0.968058,
    balanced_accuracy: 0.980099,
    roc_auc: 0.998711,
    pr_auc: 0.996661,
    false_positive_rate: 0.017609,
    inference_latency_us: 0.37,
  },
  confusion_matrix: {
    tn: 13836,
    fp: 248,
    fn: 130,
    tp: 5728,
    total: 19942,
    tn_pct: 98.24,
    fp_pct: 1.76,
    fn_pct: 2.22,
    tp_pct: 97.78,
  },
  optimal_tournament_metrics: {
    threshold: 0.13,
    accuracy: 0.985759,
    precision: 0.953909,
    recall: 0.999829,
    specificity: 0.979906,
    f1_score: 0.976329,
    balanced_accuracy: 0.989868,
    roc_auc: 0.998571,
    confusion_matrix: {
      tn: 13801,
      fp: 283,
      fn: 1,
      tp: 5857,
    },
  },
  temporal_holdout_metrics: {
    split_description: 'Day 2 Out-of-Distribution Holdout (20,000 flows, 24 days later)',
    total_flows: 20000,
    accuracy: 0.9697,
    recall: 0.9837,
    precision: 0.9057,
    specificity: 0.965,
    f1_score: 0.9431,
    confusion_matrix: {
      tn: 14384,
      fp: 522,
      fn: 83,
      tp: 5011,
    },
  },
  category_metrics: [
    { category: 'Generic', test_flows: 1538, detected_tp: 1534, missed_fn: 4, recall_rate: 0.9974, status: 'STRONG', notes: 'Volumetric' },
    { category: 'Exploits', test_flows: 1276, detected_tp: 1231, missed_fn: 45, recall_rate: 0.9647, status: 'STRONG', notes: 'Payload' },
    { category: 'Fuzzers', test_flows: 1422, detected_tp: 1370, missed_fn: 52, recall_rate: 0.9634, status: 'STRONG', notes: 'Jitter' },
    { category: 'DoS', test_flows: 521, detected_tp: 517, missed_fn: 4, recall_rate: 0.9923, status: 'STRONG', notes: 'Rate' },
    { category: 'Backdoor', test_flows: 460, detected_tp: 457, missed_fn: 3, recall_rate: 0.9935, status: 'STRONG', notes: 'Covert' },
    { category: 'Analysis', test_flows: 458, detected_tp: 456, missed_fn: 2, recall_rate: 0.9956, status: 'STRONG', notes: 'Probes' },
    { category: 'Reconnaissance', test_flows: 154, detected_tp: 140, missed_fn: 14, recall_rate: 0.9091, status: 'STRONG', notes: 'Scan' },
    { category: 'Shellcode', test_flows: 24, detected_tp: 18, missed_fn: 6, recall_rate: 0.75, status: 'MODERATE', notes: 'Interactive' },
    { category: 'Worms', test_flows: 5, detected_tp: 5, missed_fn: 0, recall_rate: 1.0, status: 'PERFECT', notes: 'Replication' },
  ],
  comparison_models: [
    {
      model_name: 'OptunaTuned_XGBoost',
      model_type: 'optimized_supervised',
      accuracy: 0.9858,
      precision: 0.9539,
      recall: 0.9998,
      specificity: 0.9799,
      fpr: 0.0201,
      f1_score: 0.9763,
      balanced_accuracy: 0.9899,
      roc_auc: 0.9986,
      pr_auc: 0.9954,
      latency_us: 0.37,
      flagged_pct: 30.79,
      is_production: true,
      status: 'ACTIVE_PRODUCTION',
    },
    {
      model_name: 'HistGradientBoostingClassifier',
      model_type: 'supervised_boosting',
      accuracy: 0.9859,
      precision: 0.9542,
      recall: 0.9998,
      specificity: 0.98,
      fpr: 0.02,
      f1_score: 0.9765,
      balanced_accuracy: 0.9899,
      roc_auc: 0.998,
      pr_auc: 0.9923,
      latency_us: 0.65,
      flagged_pct: 30.78,
      is_production: false,
      status: 'BENCHMARK_CANDIDATE',
    },
  ],
  methodology_and_limitations: {
    causal_policy: 'Strict unidirectional causal observability: zero reverse features.',
    unidirectional_horizon: 'When monitoring unidirectional passive taps, internal server return status codes are physically unobservable.',
    impossibility_of_100_percent: [
      'Stealth probes and single-packet scans look byte-for-byte identical to dropped legitimate connections.',
      'Low-footprint backdoor and covert channels conform strictly to benign forward volume.',
      'Real network traffic exhibits natural label ambiguity and non-stationary drift.',
      'Target leakage prohibition: academic literature reporting 100% routinely leaks reverse state.',
    ],
    cross_dataset_boundaries: [
      'Direct transfer to CICIDS2017 unsupported because IP TTL is omitted.',
      'Milestone 10.1 evidence audit confirmed local CICIDS2017 was a synthetic fixture.',
    ],
  },
};

describe('ModelPerformancePage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(api, 'getModelEvaluation').mockResolvedValue(mockEvaluationData);
  });

  it('renders page header and active production model overview', async () => {
    render(<ModelPerformancePage />);

    expect(await screen.findByText('Model Performance & Evaluation')).toBeDefined();
    expect(screen.getAllByText('OptunaTuned_XGBoost').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('v1.0.0')).toBeDefined();
    expect(screen.getByText('τ = 0.5')).toBeDefined();
    expect(screen.getByText('ALL SHA-256 HASHES VERIFIED')).toBeDefined();
  });

  it('renders performance metric cards with exact operational percentages', async () => {
    render(<ModelPerformancePage />);

    expect(await screen.findByText('ACCURACY')).toBeDefined();
    expect(screen.getAllByText('98.10%').length).toBeGreaterThanOrEqual(1); // Accuracy
    expect(screen.getAllByText('97.78%').length).toBeGreaterThanOrEqual(1); // Recall
    expect(screen.getAllByText('95.85%').length).toBeGreaterThanOrEqual(1); // Precision
    expect(screen.getAllByText('98.24%').length).toBeGreaterThanOrEqual(1); // Specificity
    expect(screen.getAllByText('96.81%').length).toBeGreaterThanOrEqual(1); // F1
    expect(screen.getAllByText('98.01%').length).toBeGreaterThanOrEqual(1); // Balanced Accuracy
    expect(screen.getAllByText('0.9987').length).toBeGreaterThanOrEqual(1); // ROC-AUC
    expect(screen.getAllByText('0.37 µs').length).toBeGreaterThanOrEqual(1); // Latency
  });

  it('renders confusion matrix counts and toggles to percentages', async () => {
    render(<ModelPerformancePage />);

    // Check count values
    expect(await screen.findByText('13,836')).toBeDefined(); // TN
    expect(screen.getByText('248')).toBeDefined(); // FP
    expect(screen.getByText('130')).toBeDefined(); // FN
    expect(screen.getByText('5,728')).toBeDefined(); // TP

    // Click Percentages toggle
    const pctButton = screen.getByRole('button', { name: /Percentages/i });
    fireEvent.click(pctButton);

    // Verify percentages displayed
    expect(screen.getAllByText('98.24%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('1.76%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('2.22%').length).toBeGreaterThanOrEqual(1);
  });

  it('toggles to optimal F1 threshold mode', async () => {
    render(<ModelPerformancePage />);

    const optimalButton = await screen.findByRole('button', { name: /Optimal F1/i });
    fireEvent.click(optimalButton);

    // Optimal recall 99.98% should now be displayed
    expect(screen.getAllByText('99.98%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('98.58%').length).toBeGreaterThanOrEqual(1); // Optimal Accuracy
  });

  it('renders attack category detection breakdown', async () => {
    render(<ModelPerformancePage />);

    expect(await screen.findByText('Exploits')).toBeDefined();
    expect(screen.getByText('Fuzzers')).toBeDefined();
    expect(screen.getByText('Generic')).toBeDefined();
    expect(screen.getByText('DoS')).toBeDefined();
    expect(screen.getByText('Backdoor')).toBeDefined();
    expect(screen.getByText('Reconnaissance')).toBeDefined();
    expect(screen.getByText('Shellcode')).toBeDefined();
    expect(screen.getByText('Worms')).toBeDefined();
  });

  it('renders temporal holdout and limitations disclosures', async () => {
    render(<ModelPerformancePage />);

    expect(await screen.findByText('Out-of-Distribution Temporal Holdout (Day 2)')).toBeDefined();
    expect(screen.getByText('Day 2 Accuracy')).toBeDefined();
    expect(screen.getByText('96.97%')).toBeDefined();
    expect(screen.getByText('Why 100% Accuracy is Operationally Infeasible')).toBeDefined();
  });

  it('handles API error state gracefully', async () => {
    vi.spyOn(api, 'getModelEvaluation').mockRejectedValue(new Error('Network offline'));
    render(<ModelPerformancePage />);

    expect(await screen.findByText('Evaluation Telemetry Unavailable')).toBeDefined();
    expect(screen.getByText('Network offline')).toBeDefined();
    expect(screen.getByRole('button', { name: /Retry Evaluation Load/i })).toBeDefined();
  });
});
