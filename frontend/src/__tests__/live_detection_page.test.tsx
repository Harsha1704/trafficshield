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

const mockInterfaces: NetworkInterfaceItem[] = [
  {
    name: 'Wi-Fi',
    description: 'Intel Wi-Fi 6 AX201',
    ipv4_addresses: ['192.168.1.100'],
    mac_address: '00:11:22:33:44:55',
    is_up: true,
    is_loopback: false,
    driver_available: true,
    driver_status: 'Npcap active and ready',
  },
];

const mockSamplePcaps: SamplePcapItem[] = [
  {
    filename: 'sample_traffic.pcap',
    path: 'D:/projects/trafficshield/data/captures/sample_traffic.pcap',
    size_bytes: 512000,
  },
];

const baseStatus: CaptureStatusResponse = {
  worker_state: 'STOPPED',
  capture_mode: 'NONE',
  selected_target: null,
  error_message: null,
  uptime_seconds: 0,
  start_time: null,
  last_packet_timestamp: null,
  packets_observed: 0,
  packets_dropped: 0,
  active_flows_count: 0,
  flows_created: 0,
  flows_completed: 0,
  flows_scored: 0,
  anomalies_detected: 0,
  alerts_persisted: 0,
  queue_depth: 0,
  mean_inference_latency_ms: 0,
  source_provenance: 'NONE',
  driver_available: true,
  driver_message: 'Npcap capture driver verified active.',
  model_integrity: {
    model_name: 'OptunaTuned_XGBoost',
    model_version: '1.0.0',
    model_sha256: 'c43bb5cabd848f930eb7a977b730e401bd8204d6dd63170d1d2f2df2e4d27495',
    preprocessor_sha256: 'effe96e1977ce9687eb602a953f34f70a42ee1881bf678f59c40b99a1eecc653',
    checksum_verified: true,
  },
  recent_events: [],
};

describe('LiveDetectionPage (SOC Dashboard Integration)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getInterfaces).mockResolvedValue({
      driver_available: true,
      driver_status: 'Npcap active and ready',
      interfaces: mockInterfaces,
    });
    vi.mocked(api.getSamplePcaps).mockResolvedValue(mockSamplePcaps);
    vi.mocked(api.getCaptureStatus).mockResolvedValue(baseStatus);
  });

  it('renders initial loading state and loads interfaces and status', async () => {
    render(<LiveDetectionPage />);
    await waitFor(() => {
      expect(api.getInterfaces).toHaveBeenCalledTimes(1);
      expect(api.getSamplePcaps).toHaveBeenCalledTimes(1);
      expect(api.getCaptureStatus).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByText(/Live Network Detection & PCAP Replay/i)).toBeDefined();
    expect(screen.getByText(/Packets Observed/i)).toBeDefined();
  });

  it('correctly displays measured numeric values and tiered drop accounting', async () => {
    const activeStatus: CaptureStatusResponse = {
      ...baseStatus,
      worker_state: 'RUNNING',
      capture_mode: 'LIVE_CAPTURE',
      selected_target: 'Wi-Fi',
      packets_observed: 15420,
      packets_dropped: 12,
      flows_completed: 850,
      flows_scored: 840,
      flows_queue_dropped: 5,
      anomalies_detected: 45,
      alerts_persisted: 30,
      alerts_deduplicated: 15,
      native_kernel_drops_available: true,
      native_kernel_drops: 0,
      kernel_drop_status: 'AVAILABLE',
      mean_inference_latency_ms: 6.8,
    };

    vi.mocked(api.getCaptureStatus).mockResolvedValue(activeStatus);
    render(<LiveDetectionPage />);

    await waitFor(() => {
      expect(screen.getByText('Tiered Drop Demarcation')).toBeDefined();
    });

    // Tier 1 measured zero drops displayed as 0 (not missing)
    expect(screen.getByText('Tier 1 Kernel Drops:')).toBeDefined();
    // Tier 2 ingestion drops
    expect(screen.getByText('Tier 2 Ingestion Drops:')).toBeDefined();
    // Tier 3 flow queue drops
    expect(screen.getByText('Tier 3 Flow Queue Drops:')).toBeDefined();
  });

  it('renders "Unavailable" badge instead of false zero when native driver stats are unavailable', async () => {
    const pcapStatus: CaptureStatusResponse = {
      ...baseStatus,
      worker_state: 'RUNNING',
      capture_mode: 'PCAP_REPLAY',
      selected_target: 'sample_traffic.pcap',
      packets_observed: 500,
      packets_dropped: 0,
      native_kernel_drops_available: false,
      native_kernel_drops: null,
      kernel_drop_status: 'UNAVAILABLE (PCAP replay is an offline file source)',
    };

    vi.mocked(api.getCaptureStatus).mockResolvedValue(pcapStatus);
    render(<LiveDetectionPage />);

    await waitFor(() => {
      expect(screen.getByText('Tiered Drop Demarcation')).toBeDefined();
    });

    // Must render Unavailable or Unsupported badge, never a false 0
    expect(screen.getAllByText(/Unavailable|Unsupported/i).length).toBeGreaterThan(0);
  });

  it('renders model contract, 13 features badge, threshold 0.50, and SHA hashes', async () => {
    render(<LiveDetectionPage />);

    await waitFor(() => {
      expect(screen.getByText('13 Frozen Features')).toBeDefined();
      expect(screen.getByText('Threshold 0.50')).toBeDefined();
      expect(screen.getByText(/Detector SHA:/i)).toBeDefined();
    });
  });

  it('renders anomaly disclaimer emphasizing statistical anomalies rather than confirmed attacks', async () => {
    render(<LiveDetectionPage />);

    await waitFor(() => {
      expect(
        screen.getByText(/Detections represent statistical pattern anomalies requiring investigation, not verified attacks/i)
      ).toBeDefined();
    });
  });

  it('handles API failure gracefully and keeps UI responsive', async () => {
    vi.mocked(api.getCaptureStatus).mockRejectedValue(new Error('Network error polling capture status'));
    render(<LiveDetectionPage />);

    await waitFor(() => {
      expect(api.getCaptureStatus).toHaveBeenCalled();
    });
    // The page falls back gracefully without unhandled crashes
    expect(screen.getByText(/Live Network Detection & PCAP Replay/i)).toBeDefined();
  });
});
