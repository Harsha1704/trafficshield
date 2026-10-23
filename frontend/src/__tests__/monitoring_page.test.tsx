import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MonitoringPage } from '../pages/MonitoringPage';
import { api } from '../services/api';

vi.mock('../services/api', () => ({
  api: {
    getMonitoringStatus: vi.fn(),
    getDriftReport: vi.fn(),
    listMonitoringAlerts: vi.fn(),
    getHistoricalMetrics: vi.fn(),
    getModelRegistry: vi.fn(),
    getFeedbackMetrics: vi.fn(),
    updateMonitoringAlert: vi.fn(),
    submitFeedback: vi.fn(),
    seedDemoMonitoring: vi.fn(),
  },
}));

const mockStatus = {
  service: 'TrafficShield Intelligent Monitoring Engine',
  version: '1.0.0',
  monitoring_mode: 'BATCH_AND_SCHEDULED',
  data_freshness: '2026-10-23T12:00:00Z',
  active_model: {
    name: 'OptunaTuned_XGBoost',
    version: '1.0.0',
    artifact_hash: 'c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495',
    lifecycle_status: 'PRODUCTION',
  },
  kpis: {
    total_batches_recorded: 15,
    total_flows_evaluated: 7500,
    total_anomalies_flagged: 1850,
    recent_24h_flows: 2400,
    average_latency_ms: 24.5,
    active_monitoring_alerts: 2,
  },
  active_alerts: [],
  reference_baseline_meta: {
    source: 'UNSW-NB15 Day 1 Calibration Partition (5,000 flows)',
  },
};

const mockDriftReport = {
  overall_status: 'WARNING' as const,
  sample_size: 500,
  batch_id: 'batch-demo-001',
  timestamp: '2026-10-23T12:00:00Z',
  feature_drift: [
    {
      feature: 'sttl',
      metric_type: 'PSI',
      metric_value: 0.185,
      threshold_warning: 0.10,
      threshold_critical: 0.25,
      status: 'WARNING' as const,
      p_value: 0.02,
      baseline_mean: 62.4,
      current_mean: 112.5,
      baseline_std: 38.1,
      current_std: 65.4,
      sample_size: 500,
      explanation: 'Moderate distribution shift detected on Source TTL.',
    },
    {
      feature: 'sload',
      metric_type: 'PSI',
      metric_value: 0.045,
      threshold_warning: 0.10,
      threshold_critical: 0.25,
      status: 'STABLE' as const,
      p_value: 0.82,
      baseline_mean: 182405.0,
      current_mean: 191200.0,
      baseline_std: 1420500.0,
      current_std: 1450000.0,
      sample_size: 500,
      explanation: 'Distribution is consistent with reference baseline.',
    },
  ],
  score_drift: {
    feature: 'anomaly_score',
    metric_type: 'PSI',
    metric_value: 0.082,
    threshold_warning: 0.10,
    threshold_critical: 0.25,
    status: 'STABLE' as const,
    baseline_mean: 0.228,
    current_mean: 0.245,
    sample_size: 500,
    explanation: 'Anomaly score distribution is stable.',
  },
  data_quality: {
    is_clean: true,
    violations: [],
  },
  disclaimer:
    'Statistical distribution drift detects input covariate shift or concept drift relative to reference baseline. It does NOT constitute proof of an adversarial cyberattack or operational failure.',
};

const mockAlerts = {
  success: true,
  data: [
    {
      id: 'mon-alert-001',
      timestamp: '2026-10-23T12:00:00Z',
      alert_type: 'FEATURE_DRIFT',
      severity: 'WARNING' as const,
      target_feature: 'sttl',
      metric_name: 'PSI',
      metric_value: 0.185,
      threshold: 0.10,
      sample_size: 500,
      summary: "Feature 'sttl' distribution drift (WARNING): PSI=0.1850.",
      details: {},
      status: 'ACTIVE' as const,
      occurrence_count: 3,
      acknowledged_at: null,
      resolved_at: null,
      is_demo: false,
    },
  ],
  meta: {
    pagination: { total: 1, page: 1, per_page: 15, pages: 1 },
  },
};

const mockRegistry = {
  active_model: {
    id: 'reg-001',
    model_name: 'OptunaTuned_XGBoost',
    model_version: '1.0.0',
    preprocessor_version: '1.0.0',
    model_artifact_hash: 'c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495',
    preprocessor_artifact_hash: 'effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653',
    lifecycle_status: 'PRODUCTION' as const,
    decision_threshold: 0.5,
    feature_contract: ['sttl', 'sload', 'duration_seconds'],
    is_active: true,
    promoted_at: '2026-10-23T10:00:00Z',
    promoted_by: 'lead_mlops_architect',
    approval_notes: 'Initial production baseline.',
  },
  registry_ledger: [
    {
      id: 'reg-001',
      model_name: 'OptunaTuned_XGBoost',
      model_version: '1.0.0',
      preprocessor_version: '1.0.0',
      model_artifact_hash: 'c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495',
      preprocessor_artifact_hash: 'effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653',
      lifecycle_status: 'PRODUCTION' as const,
      decision_threshold: 0.5,
      feature_contract: ['sttl', 'sload', 'duration_seconds'],
      is_active: true,
      promoted_at: '2026-10-23T10:00:00Z',
      promoted_by: 'lead_mlops_architect',
      approval_notes: 'Initial production baseline.',
    },
  ],
  governance_policy: {
    automatic_promotion_permitted: false,
    approval_required: true,
    validation_report_required: true,
    zero_unlabeled_retraining: true,
  },
};

const mockFeedback = {
  status: 'NO_GROUND_TRUTH' as const,
  total_feedback_records: 4,
  verified_ground_truth_count: 0,
  analyst_dispositions: {
    CONFIRMED_THREAT: 2,
    BENIGN_FALSE_POSITIVE: 1,
    SUSPICIOUS_UNVERIFIED: 1,
  },
  disclaimer:
    'Unlabeled traffic cannot be assumed benign or malicious. Operational precision and recall are calculated strictly when authoritative post-incident ground truth is verified.',
  metrics: null,
};

describe('Milestone 12: Monitoring & Drift Dashboard Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getMonitoringStatus as any).mockResolvedValue(mockStatus);
    (api.getDriftReport as any).mockResolvedValue(mockDriftReport);
    (api.listMonitoringAlerts as any).mockResolvedValue(mockAlerts);
    (api.getHistoricalMetrics as any).mockResolvedValue([]);
    (api.getModelRegistry as any).mockResolvedValue(mockRegistry);
    (api.getFeedbackMetrics as any).mockResolvedValue(mockFeedback);
  });

  it('renders Intelligent Monitoring & Drift Engine header and governance metadata', async () => {
    render(<MonitoringPage />);

    await waitFor(() => {
      expect(screen.getByText('INTELLIGENT MONITORING & DRIFT ENGINE')).toBeDefined();
    });

    expect(screen.getByText(/BATCH & SCHEDULED/)).toBeDefined();
    expect(screen.getByText(/Active Model: OptunaTuned_XGBoost v1.0.0/)).toBeDefined();
  });

  it('renders Feature Drift Matrix with calculated PSI, KS p-value, and non-causal disclaimer', async () => {
    render(<MonitoringPage />);

    await waitFor(() => {
      expect(screen.getByText('Input Feature Distribution Shift & PSI Matrix (13 Features)')).toBeDefined();
    });

    expect(screen.getAllByText('sttl').length).toBeGreaterThan(0);
    expect(screen.getByText('sload')).toBeDefined();
    // Non-causal disclaimer check
    expect(screen.getByText(/Non-Causal Disclaimer: Distribution shifts detect traffic profile changes/)).toBeDefined();
  });

  it('renders Operational Monitoring Alerts and supports acknowledgement', async () => {
    render(<MonitoringPage />);

    await waitFor(() => {
      expect(screen.getByText("Feature 'sttl' distribution drift (WARNING): PSI=0.1850.")).toBeDefined();
    });

    expect(screen.getByText('Acknowledge')).toBeDefined();
    expect(screen.getByText('Resolve')).toBeDefined();
  });

  it('renders Ground-Truth Feedback card with prominent unverified data disclaimer', async () => {
    render(<MonitoringPage />);

    await waitFor(() => {
      expect(screen.getByText('Operational Performance on Confirmed Ground Truth')).toBeDefined();
    });

    expect(
      screen.getByText(/Unlabeled traffic cannot be assumed benign or malicious/)
    ).toBeDefined();
  });

  it('renders Model Registry ledger with strict governance lock notice', async () => {
    render(<MonitoringPage />);

    await waitFor(() => {
      expect(screen.getByText('Model Registry & Lifecycle Governance Ledger')).toBeDefined();
    });

    expect(
      screen.getByText(/Automatic model retraining or promotion is disabled/)
    ).toBeDefined();
    expect(screen.getByText('GOVERNANCE LOCKED')).toBeDefined();
  });
});
