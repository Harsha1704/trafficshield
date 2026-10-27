import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { LiveDetectionPage } from '../pages/LiveDetectionPage';
import { api } from '../services/api';
import type { CaptureStatusResponse, NetworkInterfaceItem, SamplePcapItem } from '../types/api';

vi.mock('../services/api', () => ({
  api: {
    getInterfaces: vi.fn(),
    getSamplePcaps: vi.fn(),
    getCaptureStatus: vi.fn(),
    startPcapReplay: vi.fn(),
    startLiveCapture: vi.fn(),
    pauseCapture: vi.fn(),
    resumeCapture: vi.fn(),
    stopCapture: vi.fn(),
  },
}));

// Mock ResponsiveContainer for jsdom environment
vi.mock('recharts', async () => {
  const actual = await vi.importActual('recharts');
  return {
    ...actual,
    ResponsiveContainer: ({ children }: any) => <div data-testid="recharts-container">{children}</div>,
  };
});

const mockInterfaces: NetworkInterfaceItem[] = [
  {
    name: 'Wi-Fi',
    description: 'Intel Wi-Fi 6 AX201',
    ipv4_addresses: ['192.168.1.50'],
    mac_address: '00:aa:bb:cc:dd:ee',
    is_up: true,
    is_loopback: false,
    driver_available: true,
    driver_status: 'Npcap active and ready',
  },
];

const mockPcaps: SamplePcapItem[] = [
  {
    filename: 'test_traffic.pcap',
    path: 'data/captures/test_traffic.pcap',
    size_bytes: 102400,
  },
];

const sampleStatusWithIntervals: CaptureStatusResponse = {
  worker_state: 'STOPPED',
  capture_mode: 'LIVE_CAPTURE',
  selected_target: 'Wi-Fi',
  error_message: null,
  uptime_seconds: 60,
  start_time: '2026-10-26T17:00:00Z',
  last_packet_timestamp: 1700000060,
  packets_observed: 987,
  bytes_observed: 1234567,
  packets_dropped: 0,
  active_flows_count: 0,
  flows_created: 987,
  flows_completed: 987,
  flows_scored: 987,
  anomalies_detected: 404,
  alerts_persisted: 300,
  alerts_deduplicated: 104,
  queue_depth: 0,
  mean_inference_latency_ms: 16.4,
  latency_p50_ms: 15.9,
  latency_p95_ms: 21.0,
  latency_p99_ms: 28.5,
  source_provenance: 'LIVE_CAPTURE',
  driver_available: true,
  driver_message: 'Npcap active',
  model_integrity: {
    model_name: 'OptunaTuned_XGBoost',
    model_version: '1.0.0',
    model_sha256: 'c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495',
    preprocessor_sha256: 'effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653',
    checksum_verified: true,
  },
  intervals: [
    {
      timestamp: '2026-10-26T17:00:05Z',
      interval_seconds: 5.0,
      packets_captured: 120,
      bytes_captured: 150000,
      throughput_mbps: 0.24,
      flows_created: 110,
      flows_scored: 105,
      anomalies_detected: 12,
      alerts_persisted: 10,
      alerts_deduplicated: 2,
      drops: 0,
      errors: 0,
      native_stats_available: true,
    },
  ],
  session_summary: {
    start_time: '2026-10-26T17:00:00Z',
    end_time: '2026-10-26T17:01:00Z',
    is_historical: true,
    total_packets: 987,
    total_bytes: 1234567,
    total_flows_scored: 987,
    total_anomalies: 404,
    total_alerts_persisted: 300,
    total_alerts_deduplicated: 104,
    mean_inference_latency_ms: 16.4,
    latency_p50_ms: 15.9,
    latency_p95_ms: 21.0,
    latency_p99_ms: 28.5,
    total_drops: 0,
    total_errors: 0,
  },
  recent_events: [],
};

describe('Live Traffic & Anomaly Correlation Panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getInterfaces as any).mockResolvedValue({
      driver_available: true,
      driver_status: 'Npcap driver active',
      interfaces: mockInterfaces,
    });
    (api.getSamplePcaps as any).mockResolvedValue(mockPcaps);
    (api.getCaptureStatus as any).mockResolvedValue(sampleStatusWithIntervals);
  });

  it('renders the rolling correlation chart and session summary with HISTORICAL badge', async () => {
    render(<LiveDetectionPage />);

    await waitFor(() => {
      expect(screen.getByText(/Live Traffic & Anomaly Correlation Stream/i)).toBeDefined();
    });

    // Session summary card
    expect(screen.getByText(/Capture Session Summary/i)).toBeDefined();
    // HISTORICAL badge (present in header and session card)
    expect(screen.getAllByText('HISTORICAL').length).toBeGreaterThanOrEqual(1);

    // Latency percentiles
    expect(screen.getByText(/Mean 16.4 ms/i)).toBeDefined();
    expect(screen.getByText('15.9ms')).toBeDefined();
    expect(screen.getByText('21ms')).toBeDefined();
    expect(screen.getByText('28.5ms')).toBeDefined();
  });

  it('renders the aligned 5-second interval ledger table with deltas', async () => {
    render(<LiveDetectionPage />);

    await waitFor(() => {
      expect(screen.getByText(/Aligned 5-Second Interval Telemetry Ledger/i)).toBeDefined();
    });

    // Header columns
    expect(screen.getByText('Captured Packets')).toBeDefined();
    expect(screen.getByText('Captured Mbps')).toBeDefined();
    expect(screen.getByText('New Flows')).toBeDefined();
    expect(screen.getByText('Scored Flows')).toBeDefined();
    expect(screen.getByText('New Anomalies')).toBeDefined();
    expect(screen.getByText('New Alerts')).toBeDefined();

    // Interval item row values
    expect(screen.getByText('120')).toBeDefined();
    expect(screen.getByText(/0.2400/)).toBeDefined();
    expect(screen.getByText('+12')).toBeDefined();
    expect(screen.getByText('+10')).toBeDefined();
  });

  it('renders technical disclosures for Post-BPF vs Task Manager and Multicast OOD diagnostics', async () => {
    render(<LiveDetectionPage />);

    await waitFor(() => {
      expect(screen.getByText(/Post-BPF Throughput vs. Windows Task Manager/i)).toBeDefined();
    });

    expect(
      screen.getByText(/Multicast Out-of-Distribution Diagnosis \(mDNS \/ SSDP\)/i)
    ).toBeDefined();

    // Strict 4-Tier Security Triage Framework
    expect(screen.getByText(/Strict 4-Tier Anomaly Triage Framework/i)).toBeDefined();
    expect(screen.getByText('1. Model Anomaly')).toBeDefined();
    expect(screen.getByText('2. Benign False Positive')).toBeDefined();
    expect(screen.getByText('3. Confirmed Attack')).toBeDefined();
    expect(screen.getByText('4. Uninvestigated Event')).toBeDefined();
  });
});
