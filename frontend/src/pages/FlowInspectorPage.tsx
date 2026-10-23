import React, { useState } from 'react';
import {
  Search,
  Zap,
  Play,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  Info,
  ShieldAlert,
  Save,
} from 'lucide-react';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { SeverityBadge, Badge } from '../components/common/Badge';
import { api, ApiClientError } from '../services/api';
import type { SinglePredictRequest, SinglePredictResponse } from '../types/api';

const PRESETS: Record<string, { label: string; description: string; data: SinglePredictRequest }> = {
  normal_https: {
    label: 'Normal HTTPS Client Session',
    description: 'Standard 443 TCP session with normal local TTL (64) and low byte rate.',
    data: {
      duration_seconds: 1.45,
      fwd_bytes: 4800,
      sttl: 64,
      sload: 26482.7,
      fwd_packets: 18,
      swin: 255,
      smeansz: 266.6,
      sjit: 2.1,
      sintpkt: 80.5,
      is_sm_ips_ports: 0,
    },
  },
  syn_flood: {
    label: 'Volumetric SYN Flood Attack',
    description: 'Ultra-high rate packet flood with spoofed testbed TTL (254) and saturated link load.',
    data: {
      duration_seconds: 0.0018,
      fwd_bytes: 185000,
      sttl: 254,
      sload: 822222222.2,
      fwd_packets: 280,
      swin: 255,
      smeansz: 660.7,
      sjit: 18.2,
      sintpkt: 0.006,
      is_sm_ips_ports: 0,
    },
  },
  port_scan: {
    label: 'Rapid Recon PortScan Probe',
    description: 'Fast single-packet probes with 0 duration and small packet length.',
    data: {
      duration_seconds: 0.0001,
      fwd_bytes: 44,
      sttl: 254,
      sload: 3520000.0,
      fwd_packets: 1,
      swin: 1024,
      smeansz: 44.0,
      sjit: 0.0,
      sintpkt: 0.0,
      is_sm_ips_ports: 0,
    },
  },
  dns_amplification: {
    label: 'DNS Amplification Reflection',
    description: 'UDP reflection bursts with large responses and high packet sizing.',
    data: {
      duration_seconds: 0.08,
      fwd_bytes: 92000,
      sttl: 254,
      sload: 9200000.0,
      fwd_packets: 80,
      swin: 0,
      smeansz: 1150.0,
      sjit: 42.1,
      sintpkt: 1.0,
      is_sm_ips_ports: 0,
    },
  },
  ssh_backup: {
    label: 'Benign Bulk SSH Backup',
    description: 'Elevated byte throughput from internal scheduled backup with normal TTL.',
    data: {
      duration_seconds: 12.5,
      fwd_bytes: 2500000,
      sttl: 64,
      sload: 1600000.0,
      fwd_packets: 1800,
      swin: 255,
      smeansz: 1388.8,
      sjit: 1.4,
      sintpkt: 6.9,
      is_sm_ips_ports: 0,
    },
  },
};

export const FlowInspectorPage: React.FC<{
  onAlertPersisted?: () => void;
}> = ({ onAlertPersisted }) => {
  const [formData, setFormData] = useState<SinglePredictRequest>({ ...PRESETS.normal_https.data });
  const [activePreset, setActivePreset] = useState<string>('normal_https');
  const [scoring, setScoring] = useState<boolean>(false);
  const [result, setResult] = useState<SinglePredictResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [persisting, setPersisting] = useState<boolean>(false);
  const [persistMsg, setPersistMsg] = useState<string | null>(null);

  const handlePresetSelect = (key: string) => {
    setActivePreset(key);
    setFormData({ ...PRESETS[key].data });
    setResult(null);
    setErrorMessage(null);
    setPersistMsg(null);
  };

  const handleInputChange = (field: keyof SinglePredictRequest, value: string) => {
    const num = parseFloat(value) || 0;
    setFormData((prev) => ({ ...prev, [field]: num }));
  };

  const handleInspect = async () => {
    setScoring(true);
    setErrorMessage(null);
    setPersistMsg(null);

    try {
      const res = await api.predictSingle(formData);
      setResult(res);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setErrorMessage(`${err.code}: ${err.message}`);
      } else {
        setErrorMessage('Inspection failed. Verify backend connectivity.');
      }
    } finally {
      setScoring(false);
    }
  };

  const handlePersistResult = async () => {
    if (!result) return;
    setPersisting(true);
    setPersistMsg(null);

    try {
      await api.createAlerts([
        {
          request_id: result.request_id,
          anomaly_score: result.anomaly_score,
          is_anomaly: result.is_anomaly,
          risk_level: result.risk_level,
          decision_threshold: result.decision_threshold,
          model_name: result.model_name,
          model_version: '1.0.0',
          status: 'NEW',
          analyst_notes: `Manual inspection flow. Preset: ${PRESETS[activePreset]?.label || 'Custom'}.`,
          input_features: formData,
          top_contributing_features: result.top_contributing_features,
          protocol: 'TCP',
          dst_port: 80,
        },
      ]);
      setPersistMsg('Persisted flow to SOC alerts database.');
      if (onAlertPersisted) onAlertPersisted();
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : 'Persistence failed');
    } finally {
      setPersisting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Presets Selector */}
      <Card
        title="Interactive Flow Inspector & Test Bench"
        subtitle="Evaluate individual network flow observations against production XGBoost decision boundaries"
      >
        <div className="space-y-2">
          <label className="text-xs text-slate-400 font-mono">Load Pre-Configured Test Traffic Vector:</label>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
            {Object.entries(PRESETS).map(([key, p]) => (
              <button
                key={key}
                onClick={() => handlePresetSelect(key)}
                className={`p-2.5 rounded-lg text-left transition-all border text-xs font-mono ${
                  activePreset === key
                    ? 'bg-cyan-950/60 border-cyan-500/50 text-cyan-300 shadow-sm shadow-cyan-950/40'
                    : 'bg-slate-900/60 border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-850'
                }`}
              >
                <div className="font-semibold truncate">{p.label}</div>
                <div className="text-[10px] text-slate-400 mt-1 line-clamp-2">{p.description}</div>
              </button>
            ))}
          </div>
        </div>
      </Card>

      {/* Main Grid: Form Left, Result Right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Form Inputs (7 Cols) */}
        <Card
          className="lg:col-span-7"
          title="Forward Observable Metrics (Single-Direction)"
          subtitle="Strictly forward packet header fields and cumulative counters"
          action={
            <Button
              size="sm"
              variant="secondary"
              onClick={() => handlePresetSelect(activePreset)}
              icon={<RotateCcw className="w-3.5 h-3.5" />}
            >
              Reset
            </Button>
          }
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-mono">
            <div>
              <label className="block text-slate-400 mb-1">
                duration_seconds <span className="text-slate-500">(s)</span>
              </label>
              <input
                type="number"
                step="any"
                value={formData.duration_seconds}
                onChange={(e) => handleInputChange('duration_seconds', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                fwd_bytes <span className="text-slate-500">(bytes)</span>
              </label>
              <input
                type="number"
                step="any"
                value={formData.fwd_bytes}
                onChange={(e) => handleInputChange('fwd_bytes', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                sttl <span className="text-slate-500">(Source TTL, 1-255)</span>
              </label>
              <input
                type="number"
                value={formData.sttl}
                onChange={(e) => handleInputChange('sttl', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                sload <span className="text-slate-500">(Source bits/sec)</span>
              </label>
              <input
                type="number"
                step="any"
                value={formData.sload}
                onChange={(e) => handleInputChange('sload', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                fwd_packets <span className="text-slate-500">(count)</span>
              </label>
              <input
                type="number"
                value={formData.fwd_packets}
                onChange={(e) => handleInputChange('fwd_packets', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                swin <span className="text-slate-500">(TCP Init Window)</span>
              </label>
              <input
                type="number"
                value={formData.swin}
                onChange={(e) => handleInputChange('swin', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                smeansz <span className="text-slate-500">(Mean packet bytes)</span>
              </label>
              <input
                type="number"
                step="any"
                value={formData.smeansz}
                onChange={(e) => handleInputChange('smeansz', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                sjit <span className="text-slate-500">(Source jitter, ms)</span>
              </label>
              <input
                type="number"
                step="any"
                value={formData.sjit}
                onChange={(e) => handleInputChange('sjit', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                sintpkt <span className="text-slate-500">(Inter-packet time, ms)</span>
              </label>
              <input
                type="number"
                step="any"
                value={formData.sintpkt}
                onChange={(e) => handleInputChange('sintpkt', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                is_sm_ips_ports <span className="text-slate-500">(Same IP/Port 0/1)</span>
              </label>
              <select
                value={formData.is_sm_ips_ports}
                onChange={(e) => handleInputChange('is_sm_ips_ports', e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 focus:outline-none focus:border-cyan-500/50"
              >
                <option value={0}>0 (Distinct IPs/Ports)</option>
                <option value={1}>1 (Identical IP/Port - Land Attack)</option>
              </select>
            </div>
          </div>

          <div className="mt-5 pt-4 border-t border-slate-800 flex items-center justify-between">
            <span className="text-[11px] text-slate-500 flex items-center gap-1 font-mono">
              <Info className="w-3.5 h-3.5" /> Rate features automatically derived on backend.
            </span>
            <Button onClick={handleInspect} loading={scoring} icon={<Play className="w-4 h-4" />}>
              Score Observation
            </Button>
          </div>
        </Card>

        {/* Inference Result Card (5 Cols) */}
        <Card
          className="lg:col-span-5"
          title="Inference Verdict & Attributions"
          subtitle="Real-time model score & root cause explanation"
          badge={
            result ? (
              result.is_anomaly ? (
                <Badge variant="cyan">ANOMALY</Badge>
              ) : (
                <Badge variant="slate">BENIGN</Badge>
              )
            ) : null
          }
        >
          {errorMessage && (
            <div className="p-3 mb-4 rounded-lg bg-rose-950/60 border border-rose-800/60 text-rose-300 text-xs">
              {errorMessage}
            </div>
          )}

          {persistMsg && (
            <div className="p-3 mb-4 rounded-lg bg-emerald-950/60 border border-emerald-800/60 text-emerald-300 text-xs flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>{persistMsg}</span>
            </div>
          )}

          {!result ? (
            <div className="flex flex-col items-center justify-center p-8 text-center text-slate-500 space-y-2">
              <Zap className="w-8 h-8 text-slate-600" />
              <p className="text-xs font-mono">Click "Score Observation" to query production XGBoost endpoint.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Verdict Banner */}
              <div
                className={`p-4 rounded-xl border text-center font-mono ${
                  result.is_anomaly
                    ? 'bg-rose-950/30 border-rose-500/40 text-rose-300'
                    : 'bg-emerald-950/30 border-emerald-500/40 text-emerald-300'
                }`}
              >
                <div className="text-[11px] uppercase tracking-widest text-slate-400">Classification Verdict</div>
                <div className="text-2xl font-bold tracking-wider mt-1">
                  {result.is_anomaly ? 'ANOMALOUS FLOW DETECTED' : 'NORMAL BENIGN FLOW'}
                </div>
                <div className="mt-2 flex items-center justify-center gap-2">
                  <SeverityBadge severity={result.risk_level} />
                  <span className="text-xs text-slate-400">Score: {result.anomaly_score.toFixed(4)}</span>
                </div>
              </div>

              {/* Score Meter */}
              <div>
                <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-1">
                  <span>Score (0.0 to 1.0):</span>
                  <span>Threshold: τ = {result.decision_threshold}</span>
                </div>
                <div className="w-full h-3 rounded-full bg-slate-900 border border-slate-800 overflow-hidden relative">
                  <div
                    className={`h-full transition-all duration-300 ${
                      result.anomaly_score >= 0.5 ? 'bg-gradient-to-r from-orange-500 to-rose-500' : 'bg-emerald-500'
                    }`}
                    style={{ width: `${Math.min(100, Math.max(0, result.anomaly_score * 100))}%` }}
                  />
                  {/* Threshold marker */}
                  <div
                    className="absolute top-0 bottom-0 w-0.5 bg-amber-400 shadow-sm shadow-amber-400"
                    style={{ left: `${result.decision_threshold * 100}%` }}
                    title={`Threshold: ${result.decision_threshold}`}
                  />
                </div>
              </div>

              {/* Explanations */}
              <div>
                <h4 className="text-xs font-semibold text-slate-200 uppercase tracking-wider mb-2 font-mono flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 text-cyan-400" />
                  Salient Feature Attributions
                </h4>
                {result.top_contributing_features.length > 0 ? (
                  <div className="space-y-1.5">
                    {result.top_contributing_features.map((f, i) => (
                      <div key={i} className="p-2.5 rounded bg-slate-900/60 border border-slate-800 text-xs">
                        <div className="flex items-center justify-between font-mono">
                          <span className="text-cyan-300 font-semibold">{f.feature} = {f.value}</span>
                          <span className="text-[10px] uppercase text-slate-400">{f.contribution}</span>
                        </div>
                        <p className="text-slate-400 text-[11px] mt-0.5">{f.reason}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500 italic p-3 bg-slate-900/40 rounded-lg">
                    No features exceeded the anomalous deviation threshold.
                  </p>
                )}
              </div>

              {/* Persist Action */}
              <div className="pt-2 border-t border-slate-800 flex justify-end">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={handlePersistResult}
                  loading={persisting}
                  icon={<Save className="w-3.5 h-3.5" />}
                >
                  Save as Alert
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};
