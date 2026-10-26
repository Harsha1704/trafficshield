/**
 * TrafficShield API Type Definitions
 * Exact TypeScript schemas matching Flask backend v1 contracts.
 */

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type AlertStatus = 'NEW' | 'INVESTIGATING' | 'RESOLVED' | 'FALSE_POSITIVE';

export interface TopContributingFeature {
  feature: string;
  value: number;
  contribution: string;
  reason: string;
}

export interface SinglePredictRequest {
  duration_seconds: number;
  fwd_bytes: number;
  sttl: number;
  sload: number;
  fwd_packets: number;
  swin: number;
  smeansz: number;
  sjit: number;
  sintpkt: number;
  is_sm_ips_ports: number;
  [key: string]: number; // Allows other forward numbers if policy permits
}

export interface SinglePredictResponse {
  request_id: string;
  is_anomaly: boolean;
  anomaly_score: number;
  decision_threshold: number;
  risk_level: RiskLevel;
  model_name: string;
  top_contributing_features: TopContributingFeature[];
}

export interface BatchPredictResponse {
  total_records: number;
  anomalies_detected: number;
  anomaly_percentage: number;
  mean_anomaly_score: number;
  max_anomaly_score: number;
  predictions: SinglePredictResponse[];
}

export interface BenchmarkSplitMetrics {
  split_description: string;
  flows: number;
  accuracy: number;
  recall: number;
  precision: number;
  specificity: number;
  fpr: number;
  f1_score: number;
  roc_auc?: number;
  pr_auc?: number;
  confusion_matrix: number[];
}

export interface VerifiedBenchmarkInfo {
  evaluation_dataset: string;
  verification_milestone: string;
  heldout_test: BenchmarkSplitMetrics;
  day2_temporal_holdout: BenchmarkSplitMetrics;
  cross_dataset_limits: {
    cicids2017_status: string;
    cicids2017_local_raw_data: string;
    audit_verdict: string;
  };
}

export interface ModelInfoResponse {
  service: string;
  model_name: string;
  model_version: string;
  decision_threshold: number;
  feature_policy: string;
  required_forward_features: string[];
  engineered_features: string[];
  model_loaded: boolean;
  preprocessor_loaded: boolean;
  verified_benchmark?: VerifiedBenchmarkInfo;
}

export interface SecurityAlert {
  id: string;
  request_id: string | null;
  timestamp: string;
  is_anomaly: boolean;
  anomaly_score: number;
  decision_threshold: number;
  risk_level: RiskLevel;
  model_name: string;
  model_version: string;
  status: AlertStatus;
  analyst_notes: string | null;
  acknowledged_at: string | null;
  created_at: string;
  updated_at: string;
  input_features: Record<string, number>;
  top_contributing_features: TopContributingFeature[];
  protocol?: string | null;
  src_port?: number | null;
  dst_port?: number | null;
  is_demo?: boolean;
  source?: string;
}

export interface AlertStats {
  total_records: number;
  production_records?: number;
  demo_records?: number;
  data_mode?: 'EMPTY' | 'DEMO_FIXTURE' | 'PRODUCTION_ONLY' | 'MIXED';
  storage_backend?: string;
  total_anomalies: number;
  anomaly_rate: number;
  mean_anomaly_score: number;
  max_anomaly_score: number;
  severity_distribution: {
    CRITICAL: number;
    HIGH: number;
    MEDIUM: number;
    LOW: number;
  };
  status_distribution: {
    NEW: number;
    INVESTIGATING: number;
    RESOLVED: number;
    FALSE_POSITIVE: number;
  };
}

export interface PaginationMeta {
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface PaginatedResponse<T> {
  success: boolean;
  data: T[];
  meta: {
    pagination: PaginationMeta;
  };
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
  error?: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export interface SystemHealthResponse {
  status: string;
  version: string;
  model_loaded: boolean;
  uptime_seconds?: number;
}

// ─── Monitoring & Drift Detection Types (Milestone 12) ────────────────────────
export type DriftStatus = 'STABLE' | 'WARNING' | 'CRITICAL' | 'INSUFFICIENT_DATA';

export interface FeatureDriftItem {
  feature: string;
  metric_type: string;
  metric_value: number;
  threshold_warning: number;
  threshold_critical: number;
  status: DriftStatus;
  p_value: number | null;
  baseline_mean: number;
  current_mean: number;
  baseline_std: number;
  current_std: number;
  sample_size: number;
  explanation: string;
}

export interface ScoreDriftItem {
  feature: string;
  metric_type: string;
  metric_value: number;
  threshold_warning: number;
  threshold_critical: number;
  status: DriftStatus;
  baseline_mean: number;
  current_mean: number;
  sample_size: number;
  explanation: string;
}

export interface DriftReportResponse {
  overall_status: DriftStatus;
  sample_size: number;
  batch_id?: string;
  timestamp?: string;
  feature_drift: FeatureDriftItem[];
  score_drift: ScoreDriftItem | null;
  data_quality: {
    is_clean: boolean;
    violations: string[];
    total_missing_cells?: number;
    total_invalid_cells?: number;
  };
  disclaimer: string;
}

export interface MonitoringAlertItem {
  id: string;
  timestamp: string;
  alert_type: string;
  severity: 'INFO' | 'WARNING' | 'CRITICAL';
  target_feature: string | null;
  metric_name: string;
  metric_value: number;
  threshold: number;
  sample_size: number;
  summary: string;
  details: Record<string, any>;
  status: 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED' | 'SUPPRESSED';
  occurrence_count: number;
  acknowledged_at: string | null;
  resolved_at: string | null;
  is_demo: boolean;
}

export interface MonitoringStatusResponse {
  service: string;
  version: string;
  monitoring_mode: string;
  data_freshness: string;
  active_model: {
    name: string;
    version: string;
    artifact_hash: string;
    lifecycle_status: string;
  };
  kpis: {
    total_batches_recorded: number;
    total_flows_evaluated: number;
    total_anomalies_flagged: number;
    recent_24h_flows: number;
    average_latency_ms: number;
    active_monitoring_alerts: number;
  };
  active_alerts: MonitoringAlertItem[];
  reference_baseline_meta: {
    source?: string;
    sample_size?: number;
    window?: string;
  };
}

export interface ModelRegistryItem {
  id: string;
  model_name: string;
  model_version: string;
  preprocessor_version: string;
  model_artifact_hash: string;
  preprocessor_artifact_hash: string;
  lifecycle_status: 'PRODUCTION' | 'VALIDATED' | 'CANDIDATE' | 'ARCHIVED' | 'RETIRED';
  decision_threshold: number;
  feature_contract: string[];
  is_active: boolean;
  promoted_at: string | null;
  promoted_by: string | null;
  approval_notes: string | null;
  created_at?: string;
}

export interface ModelRegistryResponse {
  active_model: ModelRegistryItem | null;
  registry_ledger: ModelRegistryItem[];
  governance_policy: {
    automatic_promotion_permitted: boolean;
    approval_required: boolean;
    validation_report_required: boolean;
    zero_unlabeled_retraining: boolean;
  };
}

export interface OperationalEvaluationResponse {
  status: 'OPERATIONAL_METRICS_CALCULATED' | 'NO_GROUND_TRUTH';
  total_feedback_records: number;
  verified_ground_truth_count: number;
  analyst_dispositions: Record<string, number>;
  disclaimer: string;
  metrics: {
    verified_sample_size: number;
    accuracy: number;
    precision: number;
    recall: number;
    fpr: number;
    f1_score: number;
    confusion_matrix: { tp: number; fp: number; fn: number; tn: number };
  } | null;
}

export interface HistoricalBatchMetricItem {
  id: string;
  batch_id: string;
  timestamp: string;
  flow_count: number;
  anomaly_count: number;
  anomaly_rate: number;
  mean_score: number;
  p95_score: number;
  latency_ms: number;
  source: string;
  is_demo: boolean;
}

export type WorkerState = 'STOPPED' | 'STARTING' | 'RUNNING' | 'DEGRADED' | 'FAILED' | 'PAUSED';
export type CaptureMode = 'NONE' | 'PCAP_REPLAY' | 'LIVE_CAPTURE';

export interface NetworkInterfaceItem {
  name: string;
  description: string;
  ipv4_addresses: string[];
  mac_address: string | null;
  is_up: boolean;
  is_loopback: boolean;
  driver_available: boolean;
  driver_status: string;
}

export interface StreamingEventRecord {
  event_id: string;
  timestamp: string;
  flow_id: string;
  src_ip?: string;
  dst_ip?: string;
  src_port?: number;
  dst_port?: number;
  protocol?: string;
  source_provenance: string;
  anomaly_score: number;
  decision_threshold: number;
  is_anomaly: boolean;
  risk_level: RiskLevel;
  inference_latency_ms: number;
  model_name: string;
  model_version: string;
  top_features: TopContributingFeature[];
  is_provisional: boolean;
}

export interface CaptureStatusResponse {
  worker_state: WorkerState;
  capture_mode: CaptureMode;
  selected_target: string | null;
  error_message: string | null;
  uptime_seconds: number;
  start_time: string | null;
  last_packet_timestamp: number | null;
  packets_observed: number;
  packets_dropped: number;
  active_flows_count: number;
  flows_created: number;
  flows_completed: number;
  flows_flushed?: number;
  flows_closed_tcp?: number;
  flows_expired_timeout?: number;
  flows_evicted_overflow?: number;
  flows_queued?: number;
  flows_queue_dropped?: number;
  flows_scored: number;
  incompatible_flows_rejected?: number;
  validation_errors?: number;
  inference_failures?: number;
  persistence_failures?: number;
  unprocessed_flows?: number;
  anomalies_detected: number;
  alerts_persisted: number;
  alerts_deduplicated?: number;
  alerts_unpersisted_no_app?: number;
  pipeline_join_timed_out?: boolean;
  queue_depth: number;
  mean_inference_latency_ms: number;
  latency_p50_ms?: number;
  latency_p95_ms?: number;
  latency_p99_ms?: number;
  native_kernel_drops_available?: boolean;
  native_kernel_drops?: number | null;
  native_kernel_drops_delta?: number | null;
  native_packets_received?: number | null;
  native_interface_drops?: number | null;
  native_interface_drops_supported?: boolean;
  native_interface_drops_status?: string;
  kernel_drop_status?: string;
  kernel_poll_interval_seconds?: number | null;
  kernel_driver_name?: string;
  source_provenance: string;
  driver_available: boolean;
  driver_message: string;
  model_integrity: {
    model_name: string;
    model_version: string;
    model_sha256: string;
    preprocessor_sha256: string;
    checksum_verified: boolean;
  };
  recent_events: StreamingEventRecord[];
}

export interface SamplePcapItem {
  filename: string;
  path: string;
  size_bytes: number;
}
