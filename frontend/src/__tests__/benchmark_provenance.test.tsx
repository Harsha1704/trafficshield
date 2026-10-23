import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { OverviewPage } from '../pages/OverviewPage';
import { ModelIntelligencePage } from '../pages/ModelIntelligencePage';
import type { AlertStats, ModelInfoResponse } from '../types/api';

const mockModelInfo: ModelInfoResponse = {
  service: 'TrafficShield Production Anomaly Scoring API',
  model_name: 'OptunaTuned_XGBoost',
  model_version: '1.0.0',
  decision_threshold: 0.5,
  feature_policy: 'Unidirectional Causal-Only (Zero Return/Reverse Observation)',
  required_forward_features: ['sttl', 'sload', 'fwd_packets', 'fwd_bytes', 'swin', 'smeansz', 'sjit', 'sintpkt', 'is_sm_ips_ports'],
  engineered_features: ['packet_rate', 'byte_rate', 'bytes_per_packet'],
  model_loaded: true,
  preprocessor_loaded: true,
  verified_benchmark: {
    evaluation_dataset: 'UNSW-NB15',
    verification_milestone: 'M9 Independent Reproduction',
    heldout_test: {
      split_description: 'Day 1 Held-Out Test Split (19,942 flows)',
      flows: 19942,
      accuracy: 0.981045,
      recall: 0.977808,
      precision: 0.958501,
      specificity: 0.982391,
      fpr: 0.017609,
      f1_score: 0.968058,
      roc_auc: 0.998711,
      pr_auc: 0.996661,
      confusion_matrix: [13836, 248, 130, 5728],
    },
    day2_temporal_holdout: {
      split_description: 'Day 2 Out-of-Distribution Holdout (20,000 flows, 24 days later)',
      flows: 20000,
      accuracy: 0.9697,
      recall: 0.9837,
      precision: 0.9057,
      specificity: 0.965,
      fpr: 0.035,
      f1_score: 0.9431,
      confusion_matrix: [14384, 522, 83, 5011],
    },
    cross_dataset_limits: {
      cicids2017_status: 'DIRECT_TRANSFER_UNSUPPORTED',
      cicids2017_local_raw_data: 'ABSENT_LOCALLY (0 MB)',
      audit_verdict: 'M10.1 Provenance Audit Confirmed Synthetic Fixture (Unverified on real CICIDS2017)',
    },
  },
};

const mockStatsDemo: AlertStats = {
  total_records: 12,
  total_anomalies: 8,
  anomaly_rate: 66.67,
  mean_anomaly_score: 0.742,
  max_anomaly_score: 0.985,
  severity_distribution: { CRITICAL: 4, HIGH: 3, MEDIUM: 1, LOW: 4 },
  status_distribution: { NEW: 8, INVESTIGATING: 2, RESOLVED: 1, FALSE_POSITIVE: 1 },
  data_mode: 'DEMO_FIXTURE',
  production_records: 0,
  demo_records: 12,
};

const mockStatsProd: AlertStats = {
  total_records: 50,
  total_anomalies: 5,
  anomaly_rate: 10.0,
  mean_anomaly_score: 0.245,
  max_anomaly_score: 0.892,
  severity_distribution: { CRITICAL: 2, HIGH: 2, MEDIUM: 1, LOW: 45 },
  status_distribution: { NEW: 3, INVESTIGATING: 1, RESOLVED: 1, FALSE_POSITIVE: 0 },
  data_mode: 'PRODUCTION_ONLY',
  production_records: 50,
  demo_records: 0,
};

describe('Benchmark Reconciliation & Provenance Verification', () => {
  it('renders reconciled authoritative M9 benchmarks (98.10% test, 96.97% Day 2) on Overview', () => {
    render(
      <OverviewPage
        stats={mockStatsProd}
        recentAlerts={[]}
        modelInfo={mockModelInfo}
        onNavigateToAlerts={vi.fn()}
        onNavigateToTraffic={vi.fn()}
        onSelectAlert={vi.fn()}
        onSeedDemo={vi.fn()}
        seeding={false}
      />
    );

    // Verify reconciled 98.10% heldout test accuracy is rendered
    expect(screen.getByText('98.10%')).toBeDefined();
    // Verify Day 2 temporal accuracy is displayed
    expect(screen.getByText('Day 2 Holdout')).toBeDefined();
    expect(screen.getByText('96.97%')).toBeDefined();
    // Verify no uncontextualized claim of 99.98% recall without audit qualification
    expect(screen.queryByText('99.98%')).toBeNull();
  });

  it('displays DEMONSTRATION DATASET banner when in demo fixture mode', () => {
    render(
      <OverviewPage
        stats={mockStatsDemo}
        recentAlerts={[]}
        modelInfo={mockModelInfo}
        onNavigateToAlerts={vi.fn()}
        onNavigateToTraffic={vi.fn()}
        onSelectAlert={vi.fn()}
        onSeedDemo={vi.fn()}
        seeding={false}
      />
    );

    // Verify prominent banner
    expect(screen.getByText(/DEMONSTRATION DATASET ACTIVE/)).toBeDefined();
    expect(screen.getByText(/originate from testbed demo fixtures/)).toBeDefined();
    // Flow counter should clearly indicate demonstration data
    expect(screen.getByText('Demonstration Flows')).toBeDefined();
  });

  it('never labels ingested traffic counters as live network telemetry', () => {
    const { container } = render(
      <OverviewPage
        stats={mockStatsProd}
        recentAlerts={[]}
        modelInfo={mockModelInfo}
        onNavigateToAlerts={vi.fn()}
        onNavigateToTraffic={vi.fn()}
        onSelectAlert={vi.fn()}
        onSeedDemo={vi.fn()}
        seeding={false}
      />
    );

    // Check that the counter is labeled as Persisted Ingested Flows
    expect(screen.getByText('Persisted Ingested Flows')).toBeDefined();
    // Ensure "Live Network Telemetry" or "Live Traffic" is not falsely claimed
    expect(container.textContent).not.toContain('Live Network Telemetry');
  });

  it('renders M9 two-split temporal generalization breakdown in Model Intelligence', () => {
    render(
      <ModelIntelligencePage
        modelInfo={mockModelInfo}
      />
    );

    expect(screen.getByText('Authoritative Split Reconciliation (M9 Independent Verification)')).toBeDefined();
    expect(screen.getByText('Day 1 Held-Out Test Split')).toBeDefined();
    expect(screen.getByText('Day 2 Out-of-Distribution Holdout')).toBeDefined();
    expect(screen.getAllByText('98.10%').length).toBeGreaterThan(0);
    expect(screen.getAllByText('96.97%').length).toBeGreaterThan(0);
  });
});
