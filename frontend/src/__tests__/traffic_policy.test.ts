import { describe, it, expect } from 'vitest';

const REQUIRED_FORWARD_FEATURES = [
  'duration_seconds',
  'fwd_bytes',
  'sttl',
  'sload',
  'fwd_packets',
  'swin',
  'smeansz',
  'sjit',
  'sintpkt',
  'is_sm_ips_ports',
];

const FORBIDDEN_REVERSE_COLUMNS = [
  'dbytes',
  'dpkts',
  'dttl',
  'dload',
  'tcprtt',
  'synack',
  'ackdat',
  'label',
  'attack_cat',
];

function validateColumns(headers: string[]) {
  const clean = headers.map((h) => h.toLowerCase().trim());
  const forbidden = clean.filter((h) => FORBIDDEN_REVERSE_COLUMNS.includes(h));
  const missing = REQUIRED_FORWARD_FEATURES.filter((req) => !clean.includes(req.toLowerCase()));
  return {
    isValid: forbidden.length === 0 && missing.length === 0,
    forbidden,
    missing,
  };
}

describe('Frontend Feature Policy Guard', () => {
  it('passes when all 10 required forward features are provided without reverse fields', () => {
    const validHeaders = [
      'duration_seconds',
      'fwd_bytes',
      'sttl',
      'sload',
      'fwd_packets',
      'swin',
      'smeansz',
      'sjit',
      'sintpkt',
      'is_sm_ips_ports',
    ];
    const result = validateColumns(validHeaders);
    expect(result.isValid).toBe(true);
    expect(result.forbidden).toHaveLength(0);
    expect(result.missing).toHaveLength(0);
  });

  it('rejects input containing forbidden reverse-direction features', () => {
    const leakyHeaders = [
      'duration_seconds',
      'fwd_bytes',
      'sttl',
      'sload',
      'fwd_packets',
      'swin',
      'smeansz',
      'sjit',
      'sintpkt',
      'is_sm_ips_ports',
      'dbytes',
      'tcprtt',
    ];
    const result = validateColumns(leakyHeaders);
    expect(result.isValid).toBe(false);
    expect(result.forbidden).toContain('dbytes');
    expect(result.forbidden).toContain('tcprtt');
  });

  it('rejects ground-truth label leakage in prediction input', () => {
    const labelHeaders = [
      'duration_seconds',
      'fwd_bytes',
      'sttl',
      'sload',
      'fwd_packets',
      'swin',
      'smeansz',
      'sjit',
      'sintpkt',
      'is_sm_ips_ports',
      'label',
      'attack_cat',
    ];
    const result = validateColumns(labelHeaders);
    expect(result.isValid).toBe(false);
    expect(result.forbidden).toContain('label');
    expect(result.forbidden).toContain('attack_cat');
  });

  it('detects missing forward features', () => {
    const incompleteHeaders = ['duration_seconds', 'fwd_bytes'];
    const result = validateColumns(incompleteHeaders);
    expect(result.isValid).toBe(false);
    expect(result.missing).toContain('sttl');
    expect(result.missing).toContain('sload');
  });
});
