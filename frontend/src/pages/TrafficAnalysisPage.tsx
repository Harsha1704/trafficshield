import React, { useState, useRef } from 'react';
import {
  UploadCloud,
  FileText,
  AlertCircle,
  CheckCircle2,
  Download,
  Database,
  ArrowRight,
  Filter,
  Layers,
  Sparkles,
} from 'lucide-react';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { SeverityBadge, Badge } from '../components/common/Badge';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { api, ApiClientError } from '../services/api';
import type { BatchPredictResponse, SinglePredictRequest, SinglePredictResponse } from '../types/api';

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

// Demonstration sample batches for instant analyst validation
const SAMPLE_MIXED_BATCH: SinglePredictRequest[] = [
  {
    duration_seconds: 0.0015,
    fwd_bytes: 142000,
    sttl: 254,
    sload: 757333333.3,
    fwd_packets: 210,
    swin: 255,
    smeansz: 676.2,
    sjit: 14.5,
    sintpkt: 0.007,
    is_sm_ips_ports: 0,
  },
  {
    duration_seconds: 0.045,
    fwd_bytes: 78000,
    sttl: 254,
    sload: 13866666.7,
    fwd_packets: 95,
    swin: 0,
    smeansz: 821.0,
    sjit: 38.2,
    sintpkt: 0.47,
    is_sm_ips_ports: 0,
  },
  {
    duration_seconds: 0.85,
    fwd_bytes: 4200,
    sttl: 64,
    sload: 39529.4,
    fwd_packets: 16,
    swin: 255,
    smeansz: 262.5,
    sjit: 1.8,
    sintpkt: 56.6,
    is_sm_ips_ports: 0,
  },
  {
    duration_seconds: 1.2,
    fwd_bytes: 2840,
    sttl: 64,
    sload: 18933.3,
    fwd_packets: 10,
    swin: 255,
    smeansz: 284.0,
    sjit: 0.8,
    sintpkt: 133.3,
    is_sm_ips_ports: 0,
  },
  {
    duration_seconds: 0.0008,
    fwd_bytes: 84000,
    sttl: 254,
    sload: 840000000.0,
    fwd_packets: 140,
    swin: 255,
    smeansz: 600.0,
    sjit: 8.2,
    sintpkt: 0.006,
    is_sm_ips_ports: 0,
  },
];

export const TrafficAnalysisPage: React.FC<{
  onAlertsPersisted?: () => void;
}> = ({ onAlertsPersisted }) => {
  const [parsedRows, setParsedRows] = useState<SinglePredictRequest[]>([]);
  const [columnsDetected, setColumnsDetected] = useState<string[]>([]);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [forbiddenDetected, setForbiddenDetected] = useState<string[]>([]);
  const [fileName, setFileName] = useState<string | null>(null);

  const [scoring, setScoring] = useState<boolean>(false);
  const [batchResult, setBatchResult] = useState<BatchPredictResponse | null>(null);
  const [filterSeverity, setFilterSeverity] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const [persisting, setPersisting] = useState<boolean>(false);
  const [persistSuccess, setPersistSuccess] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Validate columns against feature policy
  const validateHeadersAndRows = (headers: string[], rows: Record<string, number>[]) => {
    const forbidden = headers.filter((h) => FORBIDDEN_REVERSE_COLUMNS.includes(h.toLowerCase().trim()));
    setForbiddenDetected(forbidden);

    const missing = REQUIRED_FORWARD_FEATURES.filter((req) => !headers.includes(req));
    const errors: string[] = [];

    if (forbidden.length > 0) {
      errors.push(
        `Feature policy violation: Input contains prohibited reverse/label columns: ${forbidden.join(', ')}`
      );
    }
    if (missing.length > 0) {
      errors.push(
        `Schema incomplete: Missing required forward observable features: ${missing.join(', ')}`
      );
    }

    setValidationErrors(errors);

    if (errors.length === 0) {
      const validRequests: SinglePredictRequest[] = rows.map((r) => {
        const item: Record<string, number> = {};
        for (const f of REQUIRED_FORWARD_FEATURES) {
          item[f] = Number(r[f]) || 0;
        }
        return item as unknown as SinglePredictRequest;
      });
      setParsedRows(validRequests);
    } else {
      setParsedRows([]);
    }
  };

  // CSV Text Parser
  const parseCSVText = (text: string, name: string) => {
    setFileName(name);
    setBatchResult(null);
    setPersistSuccess(null);

    const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
    if (lines.length < 2) {
      setValidationErrors(['CSV file must have a header row and at least one data row.']);
      return;
    }

    const headers = lines[0].split(',').map((h) => h.trim().replace(/^["']|["']$/g, ''));
    setColumnsDetected(headers);

    const rows: Record<string, number>[] = [];
    for (let i = 1; i < lines.length; i++) {
      if (rows.length >= 5000) break; // API max limit
      const values = lines[i].split(',').map((v) => v.trim());
      if (values.length !== headers.length) continue;

      const rowObj: Record<string, number> = {};
      headers.forEach((h, idx) => {
        rowObj[h] = parseFloat(values[idx]) || 0;
      });
      rows.push(rowObj);
    }

    validateHeadersAndRows(headers, rows);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.endsWith('.csv')) {
      setValidationErrors(['Unsupported file type. Please upload a standard CSV flow file.']);
      return;
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      parseCSVText(text, file.name);
    };
    reader.readAsText(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file && file.name.endsWith('.csv')) {
      const reader = new FileReader();
      reader.onload = (event) => {
        const text = event.target?.result as string;
        parseCSVText(text, file.name);
      };
      reader.readAsText(file);
    } else {
      setValidationErrors(['Please drop a valid .csv network flow file.']);
    }
  };

  const loadSampleBatch = () => {
    setFileName('sample_traffic_demonstration.csv');
    setColumnsDetected(REQUIRED_FORWARD_FEATURES);
    setForbiddenDetected([]);
    setValidationErrors([]);
    setParsedRows(SAMPLE_MIXED_BATCH);
    setBatchResult(null);
    setPersistSuccess(null);
  };

  const handleExecuteBatch = async () => {
    if (parsedRows.length === 0) return;
    setScoring(true);
    setValidationErrors([]);
    setPersistSuccess(null);

    try {
      const res = await api.predictBatch(parsedRows);
      setBatchResult(res);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setValidationErrors([`${err.code}: ${err.message}`]);
      } else {
        setValidationErrors(['Batch scoring request failed. Verify backend connectivity.']);
      }
    } finally {
      setScoring(false);
    }
  };

  // Persist flagged anomalies to SQLite backend
  const handlePersistAnomalies = async () => {
    if (!batchResult) return;
    const anomalies = batchResult.predictions.filter((p) => p.is_anomaly);
    if (anomalies.length === 0) return;

    setPersisting(true);
    try {
      const alertRecords = anomalies.map((p, idx) => {
        const rawFeatures = parsedRows[idx] || {};
        return {
          request_id: p.request_id,
          anomaly_score: p.anomaly_score,
          is_anomaly: p.is_anomaly,
          risk_level: p.risk_level,
          decision_threshold: p.decision_threshold,
          model_name: p.model_name,
          model_version: '1.0.0',
          status: 'NEW' as const,
          analyst_notes: `Batch upload flagged flow from ${fileName || 'upload'}.`,
          input_features: rawFeatures,
          top_contributing_features: p.top_contributing_features,
          protocol: 'TCP',
          dst_port: 80,
        };
      });

      await api.createAlerts(alertRecords);
      setPersistSuccess(`Successfully persisted ${anomalies.length} flagged anomalies to durable SOC storage.`);
      if (onAlertsPersisted) onAlertsPersisted();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Persistence failed';
      setValidationErrors([`Persistence error: ${msg}`]);
    } finally {
      setPersisting(false);
    }
  };

  // Filtered Predictions List
  const filteredPredictions = batchResult
    ? batchResult.predictions.filter((p) => {
        if (filterSeverity !== 'ALL' && p.risk_level !== filterSeverity) return false;
        if (searchQuery) {
          const q = searchQuery.toLowerCase();
          const matchId = p.request_id.toLowerCase().includes(q);
          const matchAttr = p.top_contributing_features.some((f) =>
            f.feature.toLowerCase().includes(q) || f.reason.toLowerCase().includes(q)
          );
          if (!matchId && !matchAttr) return false;
        }
        return true;
      })
    : [];

  const exportResultsCSV = () => {
    if (!batchResult) return;
    const headers = ['request_id', 'is_anomaly', 'anomaly_score', 'decision_threshold', 'risk_level', 'top_feature_1', 'top_feature_2'];
    const rows = batchResult.predictions.map((p) => [
      p.request_id,
      p.is_anomaly ? 'TRUE' : 'FALSE',
      p.anomaly_score,
      p.decision_threshold,
      p.risk_level,
      p.top_contributing_features[0]?.feature || '',
      p.top_contributing_features[1]?.feature || '',
    ]);

    const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trafficshield_batch_scored_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {/* Upload Zone & Pre-Flight Verification */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card
          className="lg:col-span-2"
          title="Network Flow Ingestion & Policy Verification"
          subtitle="Upload unidirectional flow captures in CSV format (Max 5,000 flows per batch)"
        >
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            className="flex flex-col items-center justify-center p-8 rounded-xl border-2 border-dashed border-slate-700/80 bg-slate-900/30 hover:border-cyan-500/50 hover:bg-slate-900/50 transition-all cursor-pointer group"
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={handleFileUpload}
            />
            <div className="p-3 mb-3 rounded-xl bg-slate-800 border border-slate-700 text-slate-400 group-hover:text-cyan-400 transition-colors">
              <UploadCloud className="w-8 h-8" />
            </div>
            <p className="text-sm font-semibold text-slate-200">
              Drop flow CSV file here or <span className="text-cyan-400 underline">browse</span>
            </p>
            <p className="mt-1 text-xs text-slate-400">
              Strictly forward-observable features only. Max 5,000 rows.
            </p>
          </div>

          {/* Demonstration Quick-Load */}
          <div className="mt-4 flex items-center justify-between p-3 rounded-lg bg-slate-900/60 border border-slate-800">
            <div className="flex items-center gap-2 text-xs text-slate-300">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              <span>Or load pre-configured demonstration traffic batch:</span>
            </div>
            <Button size="sm" variant="secondary" onClick={loadSampleBatch}>
              Load 5-Flow Sample
            </Button>
          </div>
        </Card>

        {/* Pre-Flight Inspection Summary */}
        <Card
          title="Pre-Flight Policy Check"
          subtitle="Causal feature contract verification"
          badge={
            parsedRows.length > 0 && validationErrors.length === 0 ? (
              <Badge variant="cyan">PASS</Badge>
            ) : (
              <Badge variant="slate">PENDING</Badge>
            )
          }
        >
          <div className="space-y-3 text-xs">
            {fileName && (
              <div className="flex items-center justify-between p-2 rounded bg-slate-900/80 border border-slate-800">
                <span className="text-slate-400 font-mono">File:</span>
                <span className="text-slate-200 font-mono truncate max-w-[180px]">{fileName}</span>
              </div>
            )}

            <div className="flex items-center justify-between p-2 rounded bg-slate-900/80 border border-slate-800">
              <span className="text-slate-400">Valid Rows Ready:</span>
              <span className="text-cyan-400 font-mono font-semibold">{parsedRows.length}</span>
            </div>

            {forbiddenDetected.length > 0 && (
              <div className="p-2.5 rounded bg-rose-950/40 border border-rose-800/60 text-rose-300 space-y-1">
                <div className="flex items-center gap-1.5 font-semibold">
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                  <span>Prohibited Columns Detected</span>
                </div>
                <p className="text-[11px] font-mono">{forbiddenDetected.join(', ')}</p>
              </div>
            )}

            {validationErrors.length > 0 && (
              <div className="p-2.5 rounded bg-amber-950/40 border border-amber-800/60 text-amber-300 space-y-1">
                <div className="flex items-center gap-1.5 font-semibold">
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                  <span>Validation Incomplete</span>
                </div>
                {validationErrors.map((err, i) => (
                  <p key={i} className="text-[11px]">{err}</p>
                ))}
              </div>
            )}

            <Button
              className="w-full mt-2"
              disabled={parsedRows.length === 0 || validationErrors.length > 0}
              loading={scoring}
              onClick={handleExecuteBatch}
              icon={<ArrowRight className="w-4 h-4" />}
            >
              Execute Batch Anomaly Scoring
            </Button>
          </div>
        </Card>
      </div>

      {/* Batch Results View */}
      {batchResult && (
        <Card
          title="Batch Scoring Results & Attribution"
          subtitle={`Analyzed ${batchResult.total_records} network flows via production XGBoost pipeline`}
          badge={<Badge variant="cyan">COMPLETED</Badge>}
          action={
            <div className="flex items-center gap-2">
              <Button size="sm" variant="secondary" onClick={exportResultsCSV} icon={<Download className="w-3.5 h-3.5" />}>
                Export CSV
              </Button>
              {batchResult.anomalies_detected > 0 && (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={handlePersistAnomalies}
                  loading={persisting}
                  icon={<Database className="w-3.5 h-3.5" />}
                >
                  Persist {batchResult.anomalies_detected} Anomalies
                </Button>
              )}
            </div>
          }
        >
          {persistSuccess && (
            <div className="mb-4 p-3 rounded-lg bg-emerald-950/60 border border-emerald-800/60 text-emerald-300 text-xs flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>{persistSuccess}</span>
            </div>
          )}

          {/* Summary Row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5 font-mono text-center">
            <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
              <span className="block text-[11px] text-slate-400">Total Scored</span>
              <span className="text-base font-bold text-slate-100">{batchResult.total_records}</span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
              <span className="block text-[11px] text-slate-400">Anomalies Detected</span>
              <span className="text-base font-bold text-rose-400">{batchResult.anomalies_detected}</span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
              <span className="block text-[11px] text-slate-400">Anomaly %</span>
              <span className="text-base font-bold text-amber-400">{batchResult.anomaly_percentage}%</span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
              <span className="block text-[11px] text-slate-400">Mean Anomaly Score</span>
              <span className="text-base font-bold text-cyan-400">{batchResult.mean_anomaly_score.toFixed(4)}</span>
            </div>
          </div>

          {/* Filters Bar */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 mb-4">
            <div className="flex items-center gap-1.5 w-full sm:w-auto">
              <Filter className="w-4 h-4 text-slate-500" />
              <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-xs">
                {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((sev) => (
                  <button
                    key={sev}
                    onClick={() => setFilterSeverity(sev)}
                    className={`px-2.5 py-1 rounded transition-colors font-mono ${
                      filterSeverity === sev
                        ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {sev}
                  </button>
                ))}
              </div>
            </div>

            <input
              type="text"
              placeholder="Search request ID or reason..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full sm:w-64 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
            />
          </div>

          {/* Results Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 font-mono uppercase tracking-wider text-[11px]">
                  <th className="py-2.5 px-3">#</th>
                  <th className="py-2.5 px-3">Request ID</th>
                  <th className="py-2.5 px-3">Classification</th>
                  <th className="py-2.5 px-3">Severity</th>
                  <th className="py-2.5 px-3">Anomaly Score</th>
                  <th className="py-2.5 px-3">Top Attributions & Explanations</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {filteredPredictions.map((pred, idx) => (
                  <tr key={pred.request_id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="py-2.5 px-3 text-slate-500">{idx + 1}</td>
                    <td className="py-2.5 px-3 text-slate-300">{pred.request_id.substring(0, 8)}...</td>
                    <td className="py-2.5 px-3">
                      {pred.is_anomaly ? (
                        <span className="text-rose-400 font-semibold">ANOMALY</span>
                      ) : (
                        <span className="text-emerald-400">NORMAL</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3">
                      <SeverityBadge severity={pred.risk_level} />
                    </td>
                    <td className="py-2.5 px-3">
                      <span className={pred.anomaly_score >= 0.5 ? 'text-rose-400 font-bold' : 'text-emerald-400'}>
                        {pred.anomaly_score.toFixed(4)}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-slate-400">
                      {pred.top_contributing_features.length > 0 ? (
                        <div className="space-y-1">
                          {pred.top_contributing_features.map((f, fi) => (
                            <div key={fi} className="text-[11px]">
                              <span className="text-cyan-300 font-semibold">{f.feature}</span> ({f.value}):{' '}
                              <span className="text-slate-400">{f.reason}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span className="text-slate-600">No anomalous feature deviation</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
};
