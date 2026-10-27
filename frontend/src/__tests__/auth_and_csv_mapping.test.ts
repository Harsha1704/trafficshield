import { describe, it, expect, beforeEach } from 'vitest';
import {
  getStoredToken,
  setStoredToken,
  getStoredUser,
  setStoredUser,
} from '../services/api';

const UNSW15_49_COLUMNS = [
  'srcip', 'sport', 'dstip', 'dsport', 'proto', 'state', 'dur', 'sbytes', 'dbytes',
  'sttl', 'dttl', 'sloss', 'dloss', 'service', 'Sload', 'Dload', 'Spkts', 'Dpkts',
  'swin', 'dwin', 'stcpb', 'dtcpb', 'smeansz', 'dmeansz', 'trans_depth', 'res_bdy_len',
  'Sjit', 'Djit', 'Stime', 'Ltime', 'Sintpkt', 'Dintpkt', 'tcprtt', 'synack', 'ackdat',
  'is_sm_ips_ports', 'ct_state_ttl', 'ct_flw_http_mthd', 'is_ftp_login', 'ct_ftp_cmd',
  'ct_srv_src', 'ct_srv_dst', 'ct_dst_ltm', 'ct_src_ ltm', 'ct_src_dport_ltm',
  'ct_dst_sport_ltm', 'ct_dst_src_ltm', 'attack_cat', 'Label',
];

const RAW_TO_CANONICAL_MAP: Record<string, string> = {
  dur: 'duration_seconds',
  duration: 'duration_seconds',
  duration_seconds: 'duration_seconds',
  sbytes: 'fwd_bytes',
  src_bytes: 'fwd_bytes',
  fwd_bytes: 'fwd_bytes',
  sttl: 'sttl',
  sload: 'sload',
  spkts: 'fwd_packets',
  fwd_packets: 'fwd_packets',
  swin: 'swin',
  smeansz: 'smeansz',
  sjit: 'sjit',
  sintpkt: 'sintpkt',
  is_sm_ips_ports: 'is_sm_ips_ports',
};

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
  'dwin',
  'dtcpb',
  'dmeansz',
  'djit',
  'dintpkt',
  'tcprtt',
  'synack',
  'ackdat',
  'label',
  'attack_cat',
];

describe('Authentication State Storage', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it('stores and retrieves token from local/session storage', () => {
    expect(getStoredToken()).toBeNull();
    const token = 'sample_jwt_bearer_token_123';
    setStoredToken(token);
    expect(getStoredToken()).toBe(token);
    expect(localStorage.getItem('trafficshield_session_token')).toBe(token);
    expect(sessionStorage.getItem('trafficshield_session_token')).toBe(token);

    setStoredToken(null);
    expect(getStoredToken()).toBeNull();
  });

  it('stores and retrieves user profile from local/session storage', () => {
    expect(getStoredUser()).toBeNull();
    const user = { id: 'user-1', username: 'analyst', role: 'analyst' };
    setStoredUser(user);
    expect(getStoredUser()).toEqual(user);

    setStoredUser(null);
    expect(getStoredUser()).toBeNull();
  });
});

describe('UNSW-NB15 Raw CSV Adapter & Unidirectional Policy', () => {
  it('correctly maps 49-column headerless UNSW-NB15 row to 10 forward features', () => {
    // Representative row from UNSW-NB15_2.csv
    const rawRow = '59.166.0.0,6055,149.171.126.5,54145,tcp,FIN,0.072974,4238,60788,31,29,7,30,-,458245.4375,6571546.5,72,72,255,255,1003293149,1003585034,59,844,0,0,62.04531,61.899776,1421955842,1421955842,1.02269,0.997042,0.002317,0.002173,0.000144,0,0,0,0,0,13,13,6,7,1,1,2,,0';
    const tokens = rawRow.split(',');
    expect(tokens.length).toBe(49);

    // Build mapping
    const headerToCanonicalIndex: Record<string, number> = {};
    const excludedColumns: string[] = [];

    UNSW15_49_COLUMNS.forEach((rawCol, idx) => {
      const lower = rawCol.trim().toLowerCase();
      if (FORBIDDEN_REVERSE_COLUMNS.includes(lower)) {
        excludedColumns.push(rawCol);
      }
      if (RAW_TO_CANONICAL_MAP[lower]) {
        headerToCanonicalIndex[RAW_TO_CANONICAL_MAP[lower]] = idx;
      }
    });

    // Check all 10 features are mapped
    for (const feat of REQUIRED_FORWARD_FEATURES) {
      expect(headerToCanonicalIndex[feat]).toBeDefined();
    }

    // Extract row
    const extracted: Record<string, number> = {};
    for (const feat of REQUIRED_FORWARD_FEATURES) {
      const idx = headerToCanonicalIndex[feat];
      extracted[feat] = parseFloat(tokens[idx]);
    }

    expect(extracted.duration_seconds).toBeCloseTo(0.072974);
    expect(extracted.fwd_bytes).toBe(4238);
    expect(extracted.sttl).toBe(31);
    expect(extracted.sload).toBeCloseTo(458245.4375);
    expect(extracted.fwd_packets).toBe(72);
    expect(extracted.swin).toBe(255);
    expect(extracted.smeansz).toBe(59);
    expect(extracted.sjit).toBeCloseTo(62.04531);
    expect(extracted.sintpkt).toBeCloseTo(1.02269);
    expect(extracted.is_sm_ips_ports).toBe(0);

    // Verify reverse features are safely excluded
    expect(extracted['dbytes']).toBeUndefined();
    expect(extracted['dpkts']).toBeUndefined();
    expect(extracted['tcprtt']).toBeUndefined();
    expect(extracted['label']).toBeUndefined();
    expect(excludedColumns).toContain('dbytes');
    expect(excludedColumns).toContain('Label');
    expect(excludedColumns).toContain('attack_cat');
  });
});
