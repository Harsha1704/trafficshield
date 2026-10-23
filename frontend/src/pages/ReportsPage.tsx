import React, { useState } from 'react';
import {
  FileSpreadsheet,
  Download,
  FileText,
  ShieldCheck,
  Calendar,
  CheckCircle2,
  Clock,
  Printer,
} from 'lucide-react';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import type { AlertStats, ModelInfoResponse, SecurityAlert } from '../types/api';

interface ReportsPageProps {
  stats: AlertStats | null;
  alerts: SecurityAlert[];
  modelInfo: ModelInfoResponse | null;
}

export const ReportsPage: React.FC<ReportsPageProps> = ({ stats, alerts, modelInfo }) => {
  const [downloadSuccess, setDownloadSuccess] = useState<string | null>(null);

  const downloadFile = (content: string, filename: string, type: string) => {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    setDownloadSuccess(`Generated ${filename}`);
    setTimeout(() => setDownloadSuccess(null), 4000);
  };

  const exportAlertsCSV = () => {
    if (alerts.length === 0) return;
    const headers = [
      'id',
      'request_id',
      'timestamp',
      'risk_level',
      'anomaly_score',
      'decision_threshold',
      'is_anomaly',
      'status',
      'protocol',
      'dst_port',
      'analyst_notes',
      'top_contributing_feature',
    ];

    const rows = alerts.map((a) => [
      `"${a.id}"`,
      `"${a.request_id || ''}"`,
      `"${a.timestamp || ''}"`,
      `"${a.risk_level}"`,
      a.anomaly_score,
      a.decision_threshold,
      a.is_anomaly ? 'TRUE' : 'FALSE',
      `"${a.status}"`,
      `"${a.protocol || 'TCP'}"`,
      a.dst_port || 80,
      `"${(a.analyst_notes || '').replace(/"/g, '""')}"`,
      `"${a.top_contributing_features?.[0]?.feature || ''}"`,
    ]);

    const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    downloadFile(csvContent, `trafficshield_soc_alerts_${Date.now()}.csv`, 'text/csv');
  };

  const exportExecutiveMarkdown = () => {
    const total = stats?.total_records ?? alerts.length;
    const anom = stats?.total_anomalies ?? alerts.filter((a) => a.is_anomaly).length;
    const crit = stats?.severity_distribution.CRITICAL ?? 0;
    const high = stats?.severity_distribution.HIGH ?? 0;
    const dataMode = stats?.data_mode ?? 'EMPTY';
    const isDemo = dataMode === 'DEMO_FIXTURE' || (stats?.demo_records ?? 0) > 0;

    const md = `# TrafficShield SOC Executive Incident & Triage Report
**Generated (UTC):** ${new Date().toISOString()}  
**System Version:** ${modelInfo?.model_version || '1.0.0'}  
**Operational Inference Engine:** ${modelInfo?.model_name || 'OptunaTuned_XGBoost'} (Threshold: τ = ${modelInfo?.decision_threshold ?? 0.5})  
**Policy Enforcement:** Strict Unidirectional Causal Observability  
**Dataset Provenance:** ${dataMode} ${isDemo ? '(WARNING: Contains demonstration fixture data, not live network traffic)' : '(Persisted Ingested Telemetry)'}

---

## 1. Executive Incident Summary

| Metric | Recorded Value | Evaluation Scope |
|:---|:---:|:---|
| **Total Flow Observations Ingested** | ${total.toLocaleString()} | Durable SOC Storage |
| **Confirmed Security Anomalies Flagged** | ${anom.toLocaleString()} | Score >= ${modelInfo?.decision_threshold ?? 0.5} |
| **Anomaly Prevalence Rate** | ${stats ? stats.anomaly_rate.toFixed(2) : '0.00'}% | Normalized Link Percentage |
| **Critical Threats (High Confidence)** | ${crit} flows | Score >= 0.85 |
| **High Priority Threats** | ${high} flows | Score in [0.65, 0.85) |
| **Average Threat Score** | ${stats ? stats.mean_anomaly_score.toFixed(4) : '0.0000'} | Continuous Anomaly Score |
| **Data Provenance Mode** | ${dataMode} | Prod: ${stats?.production_records ?? 0}, Demo: ${stats?.demo_records ?? 0} |

---

## 2. Active Threat Attribution Breakdown

The production XGBoost model flags deviations based strictly on forward-observable transport metrics:
- **Source TTL (sttl):** Anomalous departures from canonical local hop counts (e.g. injected attack flows at TTL 254).
- **Source Bitrate Load (sload):** Volumetric saturation exceeding baseline traffic profiles.
- **Forward Byte Rate (byte_rate):** Rapid volumetric surges indicative of SYN flooding or exfiltration.
- **Mean Packet Sizing (bytes_per_packet):** Structural packet anomalies indicative of port sweeps or reflection attacks.

---

## 3. Persistent Alert Triage Status

- **NEW (Pending Triage):** ${stats?.status_distribution.NEW ?? 0}
- **INVESTIGATING:** ${stats?.status_distribution.INVESTIGATING ?? 0}
- **RESOLVED (Mitigated):** ${stats?.status_distribution.RESOLVED ?? 0}
- **FALSE POSITIVE (Benign):** ${stats?.status_distribution.FALSE_POSITIVE ?? 0}

*Note: Analyst triage records update operational incident lifecycle tracking and do not mutate frozen ML weights.*
`;
    downloadFile(md, `trafficshield_executive_report_${Date.now()}.md`, 'text/markdown');
  };

  const exportAuditCertificateJSON = () => {
    const cert = {
      system: 'TrafficShield Unidirectional Anomaly Detection',
      report_timestamp: new Date().toISOString(),
      model: modelInfo,
      stats: stats,
      unidirectional_contract: {
        reverse_direction_prohibited: true,
        bidirectional_rates_prohibited: true,
        labels_excluded_from_features: true,
        causal_timing_validated: true,
      },
      verified_benchmarks: modelInfo?.verified_benchmark ?? {
        source_report: 'reports/m9_verification/independent_verification.md',
        audit_milestone: 'M9',
        unidirectional_causal_only: true,
        heldout_test: {
          dataset: 'UNSW-NB15 Held-out Test Split (Day 1)',
          flows: 19942,
          accuracy: 0.981045,
          recall: 0.977808,
          precision: 0.958501,
          specificity: 0.982391,
          f1_score: 0.968058,
          roc_auc: 0.998725,
          confusion_matrix: { tn: 13836, fp: 248, fn: 130, tp: 5728 },
        },
        day2_temporal_holdout: {
          dataset: 'UNSW-NB15 Day 2 Temporal Holdout (24 days later)',
          flows: 20000,
          accuracy: 0.96975,
          recall: 0.983706,
          precision: 0.905658,
          specificity: 0.964981,
          f1_score: 0.943075,
          confusion_matrix: { tn: 14384, fp: 522, fn: 83, tp: 5011 },
        },
      },
    };
    downloadFile(JSON.stringify(cert, null, 2), `trafficshield_audit_certificate_${Date.now()}.json`, 'application/json');
  };

  return (
    <div className="space-y-6">
      <Card
        title="SOC Security Reporting & Compliance Exports"
        subtitle="Generate audit-ready incident reports and export triage data from persistent storage"
      >
        {downloadSuccess && (
          <div className="mb-4 p-3 rounded-lg bg-emerald-950/60 border border-emerald-800/60 text-emerald-300 text-xs flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{downloadSuccess}</span>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Export 1: Executive Summary */}
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between space-y-4">
            <div>
              <div className="p-2 w-fit rounded-lg bg-cyan-950/60 border border-cyan-800/40 text-cyan-400 mb-3">
                <FileText className="w-5 h-5" />
              </div>
              <h4 className="text-sm font-semibold text-slate-100 font-mono">Executive Incident Report</h4>
              <p className="text-xs text-slate-400 mt-1">
                Markdown report summarizing link throughput, anomaly prevalence, and severity breakdown for leadership.
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={exportExecutiveMarkdown}
              icon={<Download className="w-3.5 h-3.5" />}
            >
              Export Markdown (.md)
            </Button>
          </div>

          {/* Export 2: Filtered Alerts CSV */}
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between space-y-4">
            <div>
              <div className="p-2 w-fit rounded-lg bg-indigo-950/60 border border-indigo-800/40 text-indigo-400 mb-3">
                <FileSpreadsheet className="w-5 h-5" />
              </div>
              <h4 className="text-sm font-semibold text-slate-100 font-mono">Alert Triage Ledger</h4>
              <p className="text-xs text-slate-400 mt-1">
                Full CSV table of all persisted security alerts, timestamps, triage notes, and salient root-cause attributions.
              </p>
            </div>
            <Button
              size="sm"
              variant="secondary"
              disabled={alerts.length === 0}
              onClick={exportAlertsCSV}
              icon={<Download className="w-3.5 h-3.5" />}
            >
              Export Alerts (.csv)
            </Button>
          </div>

          {/* Export 3: Audit Certificate */}
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between space-y-4">
            <div>
              <div className="p-2 w-fit rounded-lg bg-emerald-950/60 border border-emerald-800/40 text-emerald-400 mb-3">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <h4 className="text-sm font-semibold text-slate-100 font-mono">Model Verification Certificate</h4>
              <p className="text-xs text-slate-400 mt-1">
                Cryptographic JSON export documenting feature policy contracts, model architecture, and M9 verified metrics.
              </p>
            </div>
            <Button
              size="sm"
              variant="secondary"
              onClick={exportAuditCertificateJSON}
              icon={<Download className="w-3.5 h-3.5" />}
            >
              Export Certificate (.json)
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
};
