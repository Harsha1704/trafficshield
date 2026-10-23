import React, { useEffect, useState, useCallback } from 'react';
import {
  Gauge,
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Cpu,
  Layers,
  RefreshCw,
  ShieldAlert,
  Database,
  Check,
  XCircle,
  HelpCircle,
  FileCheck2,
} from 'lucide-react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { api } from '../services/api';
import type {
  DriftReportResponse,
  HistoricalBatchMetricItem,
  ModelRegistryResponse,
  MonitoringAlertItem,
  MonitoringStatusResponse,
  OperationalEvaluationResponse,
} from '../types/api';

export const MonitoringPage: React.FC = () => {
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Monitoring State
  const [statusData, setStatusData] = useState<MonitoringStatusResponse | null>(null);
  const [driftReport, setDriftReport] = useState<DriftReportResponse | null>(null);
  const [alerts, setAlerts] = useState<MonitoringAlertItem[]>([]);
  const [history, setHistory] = useState<HistoricalBatchMetricItem[]>([]);
  const [registry, setRegistry] = useState<ModelRegistryResponse | null>(null);
  const [feedbackEval, setFeedbackEval] = useState<OperationalEvaluationResponse | null>(null);

  // Feedback form state
  const [feedbackFlowId, setFeedbackFlowId] = useState<string>('flow-inspect-001');
  const [feedbackScore, setFeedbackScore] = useState<number>(0.85);
  const [feedbackDisposition, setFeedbackDisposition] = useState<string>('CONFIRMED_THREAT');
  const [feedbackVerified, setFeedbackVerified] = useState<string>('none');
  const [feedbackSubmitting, setFeedbackSubmitting] = useState<boolean>(false);
  const [feedbackSuccess, setFeedbackSuccess] = useState<string | null>(null);

  // Seeding state
  const [seeding, setSeeding] = useState<boolean>(false);

  const fetchMonitoringData = useCallback(async () => {
    setError(null);
    try {
      const [st, dr, al, hist, reg, fb] = await Promise.all([
        api.getMonitoringStatus(),
        api.getDriftReport(),
        api.listMonitoringAlerts({ page: 1, per_page: 15 }),
        api.getHistoricalMetrics(30),
        api.getModelRegistry(),
        api.getFeedbackMetrics(),
      ]);

      setStatusData(st);
      setDriftReport(dr);
      setAlerts(al.data);
      setHistory(hist);
      setRegistry(reg);
      setFeedbackEval(fb);
    } catch (err: any) {
      setError(err?.message || 'Failed to load monitoring telemetry.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchMonitoringData();
  }, [fetchMonitoringData]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchMonitoringData();
  };

  const handleAcknowledgeAlert = async (alertId: string) => {
    try {
      await api.updateMonitoringAlert(alertId, 'ACKNOWLEDGED');
      fetchMonitoringData();
    } catch (err: any) {
      alert(`Error acknowledging alert: ${err.message}`);
    }
  };

  const handleResolveAlert = async (alertId: string) => {
    try {
      await api.updateMonitoringAlert(alertId, 'RESOLVED');
      fetchMonitoringData();
    } catch (err: any) {
      alert(`Error resolving alert: ${err.message}`);
    }
  };

  const handleSeedDemo = async () => {
    setSeeding(true);
    try {
      await api.seedDemoMonitoring(true);
      fetchMonitoringData();
    } catch (err: any) {
      alert(`Demo seeding failed: ${err.message}`);
    } finally {
      setSeeding(false);
    }
  };

  const handleFeedbackSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFeedbackSubmitting(true);
    setFeedbackSuccess(null);
    try {
      const verifiedVal =
        feedbackVerified === '1' ? 1 : feedbackVerified === '0' ? 0 : null;

      await api.submitFeedback({
        flow_identifier: feedbackFlowId,
        model_score: feedbackScore,
        model_predicted_anomaly: feedbackScore >= 0.5,
        analyst_disposition: feedbackDisposition,
        verified_ground_truth: verifiedVal,
        verification_source: 'soc_analyst_workbench',
        notes: 'Submitted via SOC Monitoring & Drift Console.',
      });

      setFeedbackSuccess('Feedback recorded successfully.');
      fetchMonitoringData();
      setTimeout(() => setFeedbackSuccess(null), 4000);
    } catch (err: any) {
      alert(`Feedback submission failed: ${err.message}`);
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] text-slate-400 space-y-3 font-mono">
        <RefreshCw className="w-8 h-8 animate-spin text-cyan-400" />
        <p className="text-xs">Loading intelligent monitoring engine telemetry...</p>
      </div>
    );
  }

  const activeAlertCount = statusData?.kpis.active_monitoring_alerts ?? 0;
  const isDemo = alerts.some((a) => a.is_demo);

  return (
    <div className="space-y-6">
      {/* Top Banner: Engine Status & Governance */}
      <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 font-mono">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-cyan-950/80 border border-cyan-800/60 text-cyan-400 shrink-0">
            <Gauge className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-slate-100">
                INTELLIGENT MONITORING & DRIFT ENGINE
              </h2>
              <Badge variant="cyan">BATCH & SCHEDULED</Badge>
              {isDemo && <Badge variant="warning">DEMO TELEMETRY</Badge>}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Reference Baseline: UNSW-NB15 Calibration Partition (5,000 flows) · Active Model: {statusData?.active_model.name} v{statusData?.active_model.version}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleRefresh}
            loading={refreshing}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Refresh Telemetry
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={handleSeedDemo}
            loading={seeding}
            icon={<Database className="w-3.5 h-3.5" />}
          >
            Seed Demo Telemetry
          </Button>
        </div>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-950/40 border border-rose-800/60 text-rose-300 text-xs flex items-center gap-2 font-mono">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Bento Row 1: KPI Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 font-mono">
        <Card className="border-rose-500/20 bg-gradient-to-br from-[#140d12] to-[#0a080d]">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider text-rose-300">Active Drift Alerts</span>
            <div className="p-2 rounded-lg bg-rose-950/60 border border-rose-800/40 text-rose-400">
              <ShieldAlert className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100">{activeAlertCount}</span>
            <span className="text-xs text-slate-400">operational issues</span>
          </div>
          <p className="mt-2 text-[11px] text-slate-400">
            {activeAlertCount === 0 ? 'All 13 features within statistical tolerance' : 'Feature or concept shift detected'}
          </p>
        </Card>

        <Card className="border-cyan-500/20 bg-gradient-to-br from-[#0c111d] to-[#080d16]">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider text-cyan-300">Monitored Flows</span>
            <div className="p-2 rounded-lg bg-cyan-950/60 border border-cyan-800/40 text-cyan-400">
              <Activity className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100">
              {(statusData?.kpis.total_flows_evaluated ?? 0).toLocaleString()}
            </span>
            <span className="text-xs text-slate-400">across {statusData?.kpis.total_batches_recorded ?? 0} batches</span>
          </div>
          <p className="mt-2 text-[11px] text-slate-400">
            {statusData?.kpis.total_anomalies_flagged ?? 0} anomalies flagged overall
          </p>
        </Card>

        <Card className="border-amber-500/20 bg-gradient-to-br from-[#14100c] to-[#0d0a08]">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider text-amber-300">Inference Latency</span>
            <div className="p-2 rounded-lg bg-amber-950/60 border border-amber-800/40 text-amber-400">
              <Clock className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-amber-300">
              {statusData?.kpis.average_latency_ms.toFixed(1) ?? '0.0'} ms
            </span>
            <span className="text-xs text-slate-400">avg SLA: 250ms</span>
          </div>
          <p className="mt-2 text-[11px] text-slate-400">
            Batch throughput optimized on CPU
          </p>
        </Card>

        <Card className="border-emerald-500/20 bg-gradient-to-br from-[#0c1411] to-[#070d0a]">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider text-emerald-300">Forensic Ground Truth</span>
            <div className="p-2 rounded-lg bg-emerald-950/60 border border-emerald-800/40 text-emerald-400">
              <FileCheck2 className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-emerald-300">
              {feedbackEval?.verified_ground_truth_count ?? 0}
            </span>
            <span className="text-xs text-slate-400">verified labels</span>
          </div>
          <p className="mt-2 text-[11px] text-slate-400">
            {feedbackEval?.status === 'OPERATIONAL_METRICS_CALCULATED'
              ? `Operational Precision: ${((feedbackEval.metrics?.precision ?? 0) * 100).toFixed(1)}%`
              : 'Zero unverified accuracy fabrication'}
          </p>
        </Card>
      </div>

      {/* Bento Row 2: Feature Drift Matrix */}
      <Card
        title="Input Feature Distribution Shift & PSI Matrix (13 Features)"
        subtitle="Population Stability Index and two-sample Kolmogorov-Smirnov statistics against reference baseline"
        badge={
          <Badge
            variant={
              driftReport?.overall_status === 'CRITICAL'
                ? 'danger'
                : driftReport?.overall_status === 'WARNING'
                ? 'warning'
                : 'cyan'
            }
          >
            {driftReport?.overall_status || 'STABLE'}
          </Badge>
        }
      >
        <div className="mb-3 p-3 rounded-lg bg-slate-900/60 border border-slate-800 text-[11px] text-slate-400 font-mono">
          <p>
            <strong>Statistical Shift Notice:</strong> Population Stability Index (PSI) measures input covariate shift. PSI &lt; 0.10 is stable, 0.10–0.25 indicates moderate deviation, and &ge; 0.25 indicates critical distribution departure.
          </p>
          <p className="text-amber-300/80 mt-1">
            *Non-Causal Disclaimer: Distribution shifts detect traffic profile changes. They do NOT constitute scientific proof of a cyberattack.
          </p>
        </div>

        <div className="overflow-x-auto font-mono text-xs">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 text-[11px] uppercase tracking-wider">
                <th className="py-2.5 px-3">Feature</th>
                <th className="py-2.5 px-3">Baseline Mean ± Std</th>
                <th className="py-2.5 px-3">Current Mean ± Std</th>
                <th className="py-2.5 px-3">PSI Metric</th>
                <th className="py-2.5 px-3">KS p-value</th>
                <th className="py-2.5 px-3">Status</th>
                <th className="py-2.5 px-3">Explanation & Insight</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {driftReport?.feature_drift.map((f) => {
                let badgeVariant: 'cyan' | 'warning' | 'danger' | 'slate' = 'cyan';
                if (f.status === 'CRITICAL') badgeVariant = 'danger';
                else if (f.status === 'WARNING') badgeVariant = 'warning';
                else if (f.status === 'INSUFFICIENT_DATA') badgeVariant = 'slate';

                return (
                  <tr key={f.feature} className="hover:bg-slate-900/40 transition-colors">
                    <td className="py-2.5 px-3 font-semibold text-cyan-300">{f.feature}</td>
                    <td className="py-2.5 px-3 text-slate-300">
                      {f.baseline_mean.toFixed(2)} ± {f.baseline_std.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-3 text-slate-200">
                      {f.current_mean.toFixed(2)} ± {f.current_std.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-3 font-bold text-slate-100">{f.metric_value.toFixed(4)}</td>
                    <td className="py-2.5 px-3 text-slate-400">
                      {f.p_value !== null ? f.p_value.toFixed(4) : 'N/A'}
                    </td>
                    <td className="py-2.5 px-3">
                      <Badge variant={badgeVariant}>{f.status}</Badge>
                    </td>
                    <td className="py-2.5 px-3 text-[11px] text-slate-400 max-w-xs truncate" title={f.explanation}>
                      {f.explanation}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Bento Row 3: Historical Telemetry Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card
          title="Scoring Latency Trend"
          subtitle="Batch processing time in milliseconds against operational SLA threshold (250ms)"
        >
          {history.length === 0 ? (
            <div className="h-48 flex items-center justify-center text-xs font-mono text-slate-400">
              No historical batch metrics recorded yet.
            </div>
          ) : (
            <div className="h-56 w-full font-mono text-xs">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <XAxis dataKey="batch_id" stroke="#64748b" fontSize={10} tickLine={false} />
                  <YAxis stroke="#64748b" fontSize={10} tickLine={false} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#090d16',
                      borderColor: '#1e293b',
                      borderRadius: '8px',
                      color: '#f8fafc',
                      fontSize: '11px',
                    }}
                  />
                  <Line type="monotone" dataKey="latency_ms" stroke="#38bdf8" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card
          title="Anomaly Detection Prevalence Trend"
          subtitle="Percentage of flows flagged as anomalies across recorded scoring batches"
        >
          {history.length === 0 ? (
            <div className="h-48 flex items-center justify-center text-xs font-mono text-slate-400">
              No historical batch metrics recorded yet.
            </div>
          ) : (
            <div className="h-56 w-full font-mono text-xs">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <XAxis dataKey="batch_id" stroke="#64748b" fontSize={10} tickLine={false} />
                  <YAxis stroke="#64748b" fontSize={10} tickLine={false} domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#090d16',
                      borderColor: '#1e293b',
                      borderRadius: '8px',
                      color: '#f8fafc',
                      fontSize: '11px',
                    }}
                  />
                  <Line type="monotone" dataKey="anomaly_rate" stroke="#f43f5e" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      {/* Bento Row 4: Operational Monitoring Alerts Ledger */}
      <Card
        title="Operational Monitoring Alerts & Drift Ledger"
        subtitle="Debounced operational incidents with lifecycle acknowledgement and resolution"
        badge={<Badge variant="cyan">{alerts.length} ALERTS</Badge>}
      >
        {alerts.length === 0 ? (
          <div className="p-8 text-center font-mono text-xs text-slate-400">
            <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
            <p>No operational monitoring alerts. All features and scoring pipelines are operating normally.</p>
          </div>
        ) : (
          <div className="overflow-x-auto font-mono text-xs">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 text-[11px] uppercase tracking-wider">
                  <th className="py-2.5 px-3">Type</th>
                  <th className="py-2.5 px-3">Severity</th>
                  <th className="py-2.5 px-3">Feature</th>
                  <th className="py-2.5 px-3">Metric Value</th>
                  <th className="py-2.5 px-3">Occurrences</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Summary</th>
                  <th className="py-2.5 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {alerts.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-900/40 transition-colors">
                    <td className="py-2.5 px-3 text-slate-200">{a.alert_type}</td>
                    <td className="py-2.5 px-3">
                      <Badge variant={a.severity === 'CRITICAL' ? 'danger' : 'warning'}>
                        {a.severity}
                      </Badge>
                    </td>
                    <td className="py-2.5 px-3 font-semibold text-cyan-300">{a.target_feature || 'Overall'}</td>
                    <td className="py-2.5 px-3 text-slate-100">{a.metric_value.toFixed(4)}</td>
                    <td className="py-2.5 px-3 text-slate-300">×{a.occurrence_count}</td>
                    <td className="py-2.5 px-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${
                          a.status === 'ACTIVE'
                            ? 'bg-rose-950/80 text-rose-300 border border-rose-800'
                            : a.status === 'ACKNOWLEDGED'
                            ? 'bg-amber-950/80 text-amber-300 border border-amber-800'
                            : 'bg-emerald-950/80 text-emerald-300 border border-emerald-800'
                        }`}
                      >
                        {a.status}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-[11px] text-slate-400 max-w-xs truncate" title={a.summary}>
                      {a.summary}
                    </td>
                    <td className="py-2.5 px-3 text-right space-x-1">
                      {a.status === 'ACTIVE' && (
                        <button
                          onClick={() => handleAcknowledgeAlert(a.id)}
                          className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[10px] transition-colors"
                        >
                          Acknowledge
                        </button>
                      )}
                      {a.status !== 'RESOLVED' && (
                        <button
                          onClick={() => handleResolveAlert(a.id)}
                          className="px-2 py-1 rounded bg-emerald-950 hover:bg-emerald-900 border border-emerald-800 text-emerald-300 text-[10px] transition-colors"
                        >
                          Resolve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Bento Row 5: Model Registry Ledger & Governance Controls */}
      <Card
        title="Model Registry & Lifecycle Governance Ledger"
        subtitle="Versioned model artifacts, SHA-256 hashes, feature contracts, and promotion approvals"
        badge={<Badge variant="indigo">GOVERNANCE LOCKED</Badge>}
      >
        <div className="mb-4 p-3 rounded-lg bg-indigo-950/40 border border-indigo-800/40 text-indigo-300 text-xs font-mono">
          <p>
            <strong>Strict Governance Contract:</strong> Automatic model retraining or promotion is disabled. Any candidate model promotion requires independent M9/M10 verification and explicit human approval audit notes.
          </p>
        </div>

        <div className="overflow-x-auto font-mono text-xs">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 text-[11px] uppercase tracking-wider">
                <th className="py-2.5 px-3">Model Name & Version</th>
                <th className="py-2.5 px-3">Artifact SHA-256 Checksum</th>
                <th className="py-2.5 px-3">Lifecycle State</th>
                <th className="py-2.5 px-3">Threshold</th>
                <th className="py-2.5 px-3">Promoted By</th>
                <th className="py-2.5 px-3">Approval Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {registry?.registry_ledger.map((m) => (
                <tr key={m.id} className="hover:bg-slate-900/40 transition-colors">
                  <td className="py-2.5 px-3">
                    <span className="font-semibold text-slate-100">{m.model_name}</span>
                    <span className="text-slate-400 block text-[10px]">v{m.model_version}</span>
                  </td>
                  <td className="py-2.5 px-3 text-slate-300 font-mono text-[10px]">
                    <code>{m.model_artifact_hash.slice(0, 16)}...</code>
                  </td>
                  <td className="py-2.5 px-3">
                    <Badge variant={m.lifecycle_status === 'PRODUCTION' ? 'cyan' : 'slate'}>
                      {m.lifecycle_status}
                    </Badge>
                  </td>
                  <td className="py-2.5 px-3 text-amber-300 font-bold">τ = {m.decision_threshold}</td>
                  <td className="py-2.5 px-3 text-slate-300">{m.promoted_by || 'system_bootstrap'}</td>
                  <td className="py-2.5 px-3 text-[11px] text-slate-400 max-w-sm truncate" title={m.approval_notes || ''}>
                    {m.approval_notes || 'Initial verified baseline.'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Bento Row 6: Analyst Ground-Truth Feedback & Operational Evaluation */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 font-mono">
        {/* Left Col: Submit Ground Truth Feedback */}
        <Card
          className="lg:col-span-1"
          title="Submit Analyst Disposition"
          subtitle="Record investigation findings without mutating frozen weights"
        >
          {feedbackSuccess && (
            <div className="mb-3 p-2.5 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs flex items-center gap-1.5">
              <Check className="w-3.5 h-3.5 shrink-0" />
              <span>{feedbackSuccess}</span>
            </div>
          )}

          <form onSubmit={handleFeedbackSubmit} className="space-y-3 text-xs">
            <div>
              <label className="block text-slate-400 mb-1">Flow Identifier</label>
              <input
                type="text"
                value={feedbackFlowId}
                onChange={(e) => setFeedbackFlowId(e.target.value)}
                className="w-full px-3 py-1.5 rounded bg-slate-900 border border-slate-700 text-slate-100"
                required
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">Model Continuous Score</label>
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={feedbackScore}
                onChange={(e) => setFeedbackScore(parseFloat(e.target.value))}
                className="w-full px-3 py-1.5 rounded bg-slate-900 border border-slate-700 text-slate-100"
                required
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">Analyst Investigation Verdict</label>
              <select
                value={feedbackDisposition}
                onChange={(e) => setFeedbackDisposition(e.target.value)}
                className="w-full px-3 py-1.5 rounded bg-slate-900 border border-slate-700 text-slate-100"
              >
                <option value="CONFIRMED_THREAT">CONFIRMED_THREAT (True Positive)</option>
                <option value="BENIGN_FALSE_POSITIVE">BENIGN_FALSE_POSITIVE (Normal Traffic)</option>
                <option value="SUSPICIOUS_UNVERIFIED">SUSPICIOUS_UNVERIFIED (Pending Forensics)</option>
                <option value="POLICY_VIOLATION">POLICY_VIOLATION (Unauthorized Benign)</option>
              </select>
            </div>

            <div>
              <label className="block text-slate-400 mb-1">Confirmed Post-Incident Ground Truth</label>
              <select
                value={feedbackVerified}
                onChange={(e) => setFeedbackVerified(e.target.value)}
                className="w-full px-3 py-1.5 rounded bg-slate-900 border border-slate-700 text-slate-100"
              >
                <option value="none">Unverified (Do not extrapolate to accuracy)</option>
                <option value="1">Confirmed Malicious (Ground Truth = 1)</option>
                <option value="0">Confirmed Benign (Ground Truth = 0)</option>
              </select>
            </div>

            <Button
              size="sm"
              variant="primary"
              className="w-full mt-2"
              loading={feedbackSubmitting}
            >
              Submit Feedback
            </Button>
          </form>
        </Card>

        {/* Right 2 Cols: Operational Evaluation Matrix */}
        <Card
          className="lg:col-span-2"
          title="Operational Performance on Confirmed Ground Truth"
          subtitle="Precision, Recall, and FPR computed strictly when verified labels exist"
          badge={
            <Badge variant={feedbackEval?.status === 'OPERATIONAL_METRICS_CALCULATED' ? 'cyan' : 'slate'}>
              {feedbackEval?.status || 'NO_GROUND_TRUTH'}
            </Badge>
          }
        >
          {feedbackEval?.status === 'NO_GROUND_TRUTH' ? (
            <div className="p-6 text-center text-xs text-slate-400 space-y-3">
              <HelpCircle className="w-8 h-8 text-cyan-400 mx-auto" />
              <p className="max-w-md mx-auto leading-relaxed">
                {feedbackEval.disclaimer}
              </p>
              <div className="p-3 rounded bg-slate-900/60 border border-slate-800 text-[11px] inline-block">
                Analyst Dispositions Logged: {feedbackEval.total_feedback_records} (0 Confirmed Ground Truth)
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                  <span className="text-[10px] text-slate-400 block">Verified Sample</span>
                  <span className="text-lg font-bold text-slate-100">{feedbackEval?.metrics?.verified_sample_size}</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                  <span className="text-[10px] text-slate-400 block">Operational Precision</span>
                  <span className="text-lg font-bold text-cyan-400">
                    {((feedbackEval?.metrics?.precision ?? 0) * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                  <span className="text-[10px] text-slate-400 block">Operational Recall</span>
                  <span className="text-lg font-bold text-emerald-400">
                    {((feedbackEval?.metrics?.recall ?? 0) * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                  <span className="text-[10px] text-slate-400 block">False Positive Rate</span>
                  <span className="text-lg font-bold text-rose-400">
                    {((feedbackEval?.metrics?.fpr ?? 0) * 100).toFixed(1)}%
                  </span>
                </div>
              </div>

              <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 text-xs">
                <span className="text-slate-400 block mb-1">Confusion Matrix:</span>
                <code className="text-slate-200">
                  [TP: {feedbackEval?.metrics?.confusion_matrix.tp}, FP: {feedbackEval?.metrics?.confusion_matrix.fp}, FN: {feedbackEval?.metrics?.confusion_matrix.fn}, TN: {feedbackEval?.metrics?.confusion_matrix.tn}]
                </code>
              </div>

              <p className="text-[11px] text-slate-400 leading-tight">
                *{feedbackEval?.disclaimer}
              </p>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};
