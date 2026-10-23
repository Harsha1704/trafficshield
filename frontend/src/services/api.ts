/**
 * Centralized Typed TrafficShield API Client
 */
import type {
  ApiResponse,
  AlertStats,
  BatchPredictResponse,
  CaptureStatusResponse,
  DriftReportResponse,
  HistoricalBatchMetricItem,
  ModelInfoResponse,
  ModelRegistryResponse,
  MonitoringAlertItem,
  MonitoringStatusResponse,
  NetworkInterfaceItem,
  OperationalEvaluationResponse,
  PaginatedResponse,
  SamplePcapItem,
  SecurityAlert,
  SinglePredictRequest,
  SinglePredictResponse,
} from '../types/api';

const DEFAULT_API_BASE = 'http://localhost:5000/api/v1';

export function getApiBaseUrl(): string {
  const custom = localStorage.getItem('trafficshield_api_url');
  if (custom) return custom;
  return import.meta.env.VITE_API_URL || DEFAULT_API_BASE;
}

export function setApiBaseUrl(url: string): void {
  localStorage.setItem('trafficshield_api_url', url);
}

export class ApiClientError extends Error {
  code: string;
  status: number;
  details?: unknown;

  constructor(message: string, code: string = 'API_ERROR', status: number = 500, details?: unknown) {
    super(message);
    this.name = 'ApiClientError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const baseUrl = getApiBaseUrl().replace(/\/$/, '');
  const url = `${baseUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;

  let authToken: string | null = null;
  try {
    authToken = sessionStorage.getItem('trafficshield_session_token');
  } catch {
    // SessionStorage may be restricted in sandboxes
  }

  const defaultHeaders: HeadersInit = {
    'Accept': 'application/json',
  };

  if (authToken) {
    defaultHeaders['Authorization'] = `Bearer ${authToken}`;
  }

  if (options.body && typeof options.body === 'string') {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  const config: RequestInit = {
    ...options,
    credentials: 'include',
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  };

  try {
    const res = await fetch(url, config);
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      throw new ApiClientError(
        `Invalid server response format (${res.status} ${res.statusText})`,
        'INVALID_RESPONSE',
        res.status
      );
    }

    if (!res.ok) {
      const errPayload = data as ApiResponse<unknown>;
      const errMsg = errPayload?.error?.message || `Request failed with HTTP status ${res.status}`;
      const errCode = errPayload?.error?.code || 'HTTP_ERROR';
      throw new ApiClientError(errMsg, errCode, res.status, errPayload?.error?.details);
    }

    return data as T;
  } catch (err: unknown) {
    if (err instanceof ApiClientError) {
      throw err;
    }
    const message = err instanceof Error ? err.message : 'Network request failed';
    throw new ApiClientError(
      `${message}. Ensure the TrafficShield Flask server is running at ${baseUrl}`,
      'NETWORK_ERROR',
      0
    );
  }
}

export const api = {
  // System Health & Info
  async checkHealth(): Promise<{ status: string }> {
    const res = await request<ApiResponse<{ status: string }>>('/health');
    return res.data;
  },

  async getModelInfo(): Promise<ModelInfoResponse> {
    const res = await request<ApiResponse<ModelInfoResponse>>('/model/info');
    return res.data;
  },

  // Scoring
  async predictSingle(record: SinglePredictRequest): Promise<SinglePredictResponse> {
    const res = await request<ApiResponse<SinglePredictResponse>>('/predict', {
      method: 'POST',
      body: JSON.stringify(record),
    });
    return res.data;
  },

  async predictBatch(records: SinglePredictRequest[]): Promise<BatchPredictResponse> {
    const res = await request<ApiResponse<BatchPredictResponse>>('/predict/batch', {
      method: 'POST',
      body: JSON.stringify({ records }),
    });
    return res.data;
  },

  // Alerts & Investigations
  async listAlerts(params: {
    status?: string;
    risk_level?: string;
    is_anomaly?: boolean;
    min_score?: number;
    max_score?: number;
    search?: string;
    page?: number;
    per_page?: number;
  } = {}): Promise<PaginatedResponse<SecurityAlert>> {
    const query = new URLSearchParams();
    if (params.status) query.set('status', params.status);
    if (params.risk_level) query.set('risk_level', params.risk_level);
    if (params.is_anomaly !== undefined) query.set('is_anomaly', String(params.is_anomaly));
    if (params.min_score !== undefined) query.set('min_score', String(params.min_score));
    if (params.max_score !== undefined) query.set('max_score', String(params.max_score));
    if (params.search) query.set('search', params.search);
    if (params.page) query.set('page', String(params.page));
    if (params.per_page) query.set('per_page', String(params.per_page));

    const qs = query.toString() ? `?${query.toString()}` : '';
    return await request<PaginatedResponse<SecurityAlert>>(`/alerts${qs}`);
  },

  async getAlertStats(): Promise<AlertStats> {
    const res = await request<ApiResponse<AlertStats>>('/alerts/stats');
    return res.data;
  },

  async getAlert(alertId: string): Promise<SecurityAlert> {
    const res = await request<ApiResponse<SecurityAlert>>(`/alerts/${alertId}`);
    return res.data;
  },

  async updateAlert(alertId: string, updates: { status?: string; analyst_notes?: string }): Promise<SecurityAlert> {
    const res = await request<ApiResponse<SecurityAlert>>(`/alerts/${alertId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    });
    return res.data;
  },

  async createAlerts(records: Partial<SecurityAlert>[]): Promise<SecurityAlert[]> {
    const res = await request<ApiResponse<SecurityAlert[]>>('/alerts', {
      method: 'POST',
      body: JSON.stringify(records),
    });
    return res.data;
  },

  async seedDemoAlerts(force = false): Promise<SecurityAlert[]> {
    const res = await request<ApiResponse<SecurityAlert[]>>(`/alerts/seed-demo?force=${force}`, {
      method: 'POST',
    });
    return res.data;
  },

  // Intelligent Monitoring & Drift Detection (Milestone 12)
  async getMonitoringStatus(): Promise<MonitoringStatusResponse> {
    const res = await request<ApiResponse<MonitoringStatusResponse>>('/monitoring/status');
    return res.data;
  },

  async getDriftReport(): Promise<DriftReportResponse> {
    const res = await request<ApiResponse<DriftReportResponse>>('/monitoring/drift');
    return res.data;
  },

  async evaluateDriftBatch(records: SinglePredictRequest[], scores?: number[]): Promise<DriftReportResponse> {
    const res = await request<ApiResponse<DriftReportResponse>>('/monitoring/drift/evaluate', {
      method: 'POST',
      body: JSON.stringify({ records, scores }),
    });
    return res.data;
  },

  async listMonitoringAlerts(params: {
    status?: string;
    severity?: string;
    alert_type?: string;
    page?: number;
    per_page?: number;
  } = {}): Promise<PaginatedResponse<MonitoringAlertItem>> {
    const query = new URLSearchParams();
    if (params.status) query.set('status', params.status);
    if (params.severity) query.set('severity', params.severity);
    if (params.alert_type) query.set('alert_type', params.alert_type);
    if (params.page) query.set('page', String(params.page));
    if (params.per_page) query.set('per_page', String(params.per_page));

    const qs = query.toString() ? `?${query.toString()}` : '';
    return await request<PaginatedResponse<MonitoringAlertItem>>(`/monitoring/alerts${qs}`);
  },

  async updateMonitoringAlert(alertId: string, status: 'ACKNOWLEDGED' | 'RESOLVED' | 'SUPPRESSED'): Promise<MonitoringAlertItem> {
    const res = await request<ApiResponse<MonitoringAlertItem>>(`/monitoring/alerts/${alertId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
    return res.data;
  },

  async getHistoricalMetrics(limit = 30): Promise<HistoricalBatchMetricItem[]> {
    const res = await request<ApiResponse<HistoricalBatchMetricItem[]>>(`/monitoring/metrics?limit=${limit}`);
    return res.data;
  },

  async getModelRegistry(): Promise<ModelRegistryResponse> {
    const res = await request<ApiResponse<ModelRegistryResponse>>('/monitoring/registry');
    return res.data;
  },

  async promoteCandidateModel(modelId: string, approvedBy: string, approvalNotes: string): Promise<any> {
    const res = await request<ApiResponse<any>>('/monitoring/registry/promote', {
      method: 'POST',
      body: JSON.stringify({ model_id: modelId, approved_by: approvedBy, approval_notes: approvalNotes }),
    });
    return res.data;
  },

  async submitFeedback(payload: {
    flow_identifier: string;
    model_score: number;
    model_predicted_anomaly: boolean;
    analyst_disposition: string;
    verified_ground_truth?: number | null;
    verification_source?: string;
    notes?: string;
  }): Promise<any> {
    const res = await request<ApiResponse<any>>('/monitoring/feedback', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    return res.data;
  },

  async getFeedbackMetrics(): Promise<OperationalEvaluationResponse> {
    const res = await request<ApiResponse<OperationalEvaluationResponse>>('/monitoring/feedback/metrics');
    return res.data;
  },

  async seedDemoMonitoring(force = false): Promise<any> {
    const res = await request<ApiResponse<any>>(`/monitoring/seed-demo?force=${force}`, {
      method: 'POST',
    });
    return res.data;
  },

  // Authentication & RBAC (Milestone 13)
  async login(credentials: { username: string; password: string }): Promise<{ token: string; user: { id: string; username: string; role: string } }> {
    const res = await request<ApiResponse<{ token: string; user: { id: string; username: string; role: string } }>>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
    try {
      if (res.data?.token) {
        sessionStorage.setItem('trafficshield_session_token', res.data.token);
      }
    } catch {
      // Ignore sessionStorage exceptions
    }
    return res.data;
  },

  async logout(): Promise<void> {
    try {
      sessionStorage.removeItem('trafficshield_session_token');
    } catch {
      // Ignore
    }
    await request<ApiResponse<any>>('/auth/logout', { method: 'POST' });
  },

  async getMe(): Promise<{ id: string; username: string; role: string } | null> {
    try {
      const res = await request<ApiResponse<{ id: string; username: string; role: string }>>('/auth/me');
      return res.data;
    } catch {
      return null;
    }
  },

  // Real-Time Capture & PCAP Replay (Milestone 14)
  async getCaptureStatus(): Promise<CaptureStatusResponse> {
    const res = await request<ApiResponse<CaptureStatusResponse>>('/capture/status');
    return res.data;
  },

  async getInterfaces(): Promise<{ driver_available: boolean; driver_status: string; interfaces: NetworkInterfaceItem[] }> {
    const res = await request<ApiResponse<{ driver_available: boolean; driver_status: string; interfaces: NetworkInterfaceItem[] }>>('/capture/interfaces');
    return res.data;
  },

  async getSamplePcaps(): Promise<SamplePcapItem[]> {
    const res = await request<ApiResponse<SamplePcapItem[]>>('/capture/sample-pcaps');
    return res.data;
  },

  async startPcapReplay(params: { pcap_path: string; speed_multiplier?: number; max_packets?: number }): Promise<CaptureStatusResponse> {
    const res = await request<ApiResponse<CaptureStatusResponse>>('/capture/start-replay', {
      method: 'POST',
      body: JSON.stringify(params),
    });
    return res.data;
  },

  async startLiveCapture(params: { interface: string; bpf_filter?: string }): Promise<CaptureStatusResponse> {
    const res = await request<ApiResponse<CaptureStatusResponse>>('/capture/start-live', {
      method: 'POST',
      body: JSON.stringify(params),
    });
    return res.data;
  },

  async pauseCapture(): Promise<CaptureStatusResponse> {
    const res = await request<ApiResponse<CaptureStatusResponse>>('/capture/pause', {
      method: 'POST',
    });
    return res.data;
  },

  async resumeCapture(): Promise<CaptureStatusResponse> {
    const res = await request<ApiResponse<CaptureStatusResponse>>('/capture/resume', {
      method: 'POST',
    });
    return res.data;
  },

  async stopCapture(): Promise<CaptureStatusResponse> {
    const res = await request<ApiResponse<CaptureStatusResponse>>('/capture/stop', {
      method: 'POST',
    });
    return res.data;
  },
};
