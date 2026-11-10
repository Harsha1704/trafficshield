import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  api,
  getApiBaseUrl,
  getDefaultApiBaseUrl,
  setApiBaseUrl,
  DEFAULT_API_BASE,
  LOCAL_DEV_API_BASE,
} from '../services/api';

describe('TrafficShield Centralized API Client', () => {
  const originalEnv = { ...import.meta.env };

  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    // Reset env to original
    Object.assign(import.meta.env, originalEnv);
    delete import.meta.env.VITE_API_URL;
  });

  afterEach(() => {
    Object.assign(import.meta.env, originalEnv);
  });

  it('resolves localhost API base URL when VITE_API_URL is unset in development mode', () => {
    (import.meta.env as any).PROD = false;
    (import.meta.env as any).MODE = 'development';
    expect(getDefaultApiBaseUrl()).toBe(DEFAULT_API_BASE);
    expect(getDefaultApiBaseUrl()).toBe(LOCAL_DEV_API_BASE);
    expect(getApiBaseUrl()).toBe('http://localhost:5000/api/v1');
  });

  it('resolves localhost API base URL when VITE_API_URL is unset in production build mode', () => {
    (import.meta.env as any).PROD = true;
    (import.meta.env as any).MODE = 'production';
    expect(getDefaultApiBaseUrl()).toBe(DEFAULT_API_BASE);
    expect(getApiBaseUrl()).toBe('http://localhost:5000/api/v1');
  });

  it('prioritizes explicit VITE_API_URL over default in both development and production', () => {
    import.meta.env.VITE_API_URL = 'https://custom-gateway.internal/api/v1';
    expect(getDefaultApiBaseUrl()).toBe('https://custom-gateway.internal/api/v1');
    expect(getApiBaseUrl()).toBe('https://custom-gateway.internal/api/v1');
  });

  it('allows overriding API base URL via persistent storage', () => {
    setApiBaseUrl('http://192.168.1.100:8000/api/v1');
    expect(getApiBaseUrl()).toBe('http://192.168.1.100:8000/api/v1');
  });

  it('throws ApiClientError with structured error details on failure', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        success: false,
        error: {
          code: 'FEATURE_POLICY_VIOLATION',
          message: 'Forbidden reverse-dependent columns rejected: [dbytes]',
        },
      }),
    });

    await expect(
      api.predictSingle({
        duration_seconds: 1.0,
        fwd_bytes: 100,
        sttl: 64,
        sload: 100,
        fwd_packets: 10,
        swin: 255,
        smeansz: 10,
        sjit: 1,
        sintpkt: 10,
        is_sm_ips_ports: 0,
      })
    ).rejects.toThrow('Forbidden reverse-dependent columns rejected: [dbytes]');
  });

  it('correctly maps successful model info response', async () => {
    const mockModelInfo = {
      success: true,
      data: {
        service: 'TrafficShield Production Anomaly Scoring API',
        model_name: 'OptunaTuned_XGBoost',
        model_version: '1.0.0',
        decision_threshold: 0.5,
        feature_policy: 'Unidirectional Causal-Only (Zero Return/Reverse Observation)',
        required_forward_features: ['duration_seconds', 'fwd_bytes'],
        engineered_features: ['packet_rate', 'byte_rate', 'bytes_per_packet'],
        model_loaded: true,
        preprocessor_loaded: true,
      },
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockModelInfo,
    });

    const info = await api.getModelInfo();
    expect(info.model_name).toBe('OptunaTuned_XGBoost');
    expect(info.decision_threshold).toBe(0.5);
    expect(info.model_loaded).toBe(true);
  });
});
