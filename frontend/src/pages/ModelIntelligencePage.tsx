import React from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  Layers,
  Activity,
} from 'lucide-react';
import { Card } from '../components/common/Card';
import { Badge } from '../components/common/Badge';
import type { ModelInfoResponse } from '../types/api';

interface ModelIntelligencePageProps {
  modelInfo: ModelInfoResponse | null;
}

const FEATURE_CONTRACT_DETAILS = [
  { name: 'duration_seconds', timing: 'Flow Completion', role: 'Feature', type: 'Float', desc: 'Flow physical duration in seconds' },
  { name: 'fwd_bytes', timing: 'Flow Completion', role: 'Feature', type: 'Integer', desc: 'Total forward payload/packet bytes' },
  { name: 'sttl', timing: 'Packet Arrival', role: 'Feature', type: 'Integer', desc: 'Source IP Time-To-Live header byte (1-255)' },
  { name: 'sload', timing: 'Flow Completion', role: 'Feature', type: 'Float', desc: 'Source bits per second transmission load' },
  { name: 'fwd_packets', timing: 'Flow Completion', role: 'Feature', type: 'Integer', desc: 'Total packet count observed forward' },
  { name: 'swin', timing: 'Flow Prefix', role: 'Feature', type: 'Integer', desc: 'TCP Advertised Window in forward SYN' },
  { name: 'smeansz', timing: 'Flow Completion', role: 'Feature', type: 'Float', desc: 'Mean forward packet size in bytes' },
  { name: 'sjit', timing: 'Flow Completion', role: 'Feature', type: 'Float', desc: 'Source packet inter-arrival jitter in ms' },
  { name: 'sintpkt', timing: 'Flow Completion', role: 'Feature', type: 'Float', desc: 'Source inter-packet arrival time in ms' },
  { name: 'is_sm_ips_ports', timing: 'Packet Arrival', role: 'Feature', type: 'Binary', desc: 'Equal source/destination IP & Port indicator (LAND attack)' },
  { name: 'packet_rate', timing: 'Derived', role: 'Engineered', type: 'Float', desc: 'Forward packets per second (fwd_packets / dur)' },
  { name: 'byte_rate', timing: 'Derived', role: 'Engineered', type: 'Float', desc: 'Forward bytes per second (fwd_bytes / dur)' },
  { name: 'bytes_per_packet', timing: 'Derived', role: 'Engineered', type: 'Float', desc: 'Mean bytes per forward packet (fwd_bytes / fwd_packets)' },
];

const PROHIBITED_COLUMNS = [
  { name: 'dbytes / Total Backward Bytes', reason: 'Requires observing opposite link return traffic' },
  { name: 'dpkts / Total Backward Packets', reason: 'Requires return packet counters' },
  { name: 'dttl / Backward TTL', reason: 'Requires return IP packet header' },
  { name: 'dload / Destination Bitrate', reason: 'Requires return link throughput' },
  { name: 'tcprtt / synack / ackdat', reason: 'Requires bidirectional TCP handshake timing' },
  { name: 'Flow Bytes/s (bidirectional)', reason: 'Bidirectional aggregate combining forward & reverse bytes' },
  { name: 'label / attack_cat / Label', reason: 'Ground-truth target; severe data leakage' },
];

const AUTHORITATIVE_M9_MODELS = [
  { name: 'OptunaTuned_XGBoost', accuracy: '98.10%', recall: '97.78%', precision: '95.85%', specificity: '98.24%', status: 'PRODUCTION FREEZE' },
  { name: 'HistGradientBoosting', accuracy: '97.90%', recall: '98.12%', precision: '94.21%', specificity: '97.80%', status: 'BENCHMARK' },
  { name: 'CalibratedEnsemble (ISO+LR)', accuracy: '98.54%', recall: '99.96%', precision: '95.22%', specificity: '97.86%', status: 'FALLBACK' },
  { name: 'Statistical (Causal)', accuracy: '86.82%', recall: '63.85%', precision: '88.10%', specificity: '97.10%', status: 'BASELINE' },
];

export const ModelIntelligencePage: React.FC<ModelIntelligencePageProps> = ({ modelInfo }) => {
  const benchmark = modelInfo?.verified_benchmark;

  return (
    <div className="space-y-6">
      {/* Overview Metadata Card */}
      <Card
        title="Deployed Machine Learning Pipeline Contract"
        subtitle="Operational architecture, inference threshold, and feature boundaries"
        badge={<Badge variant="cyan">PRODUCTION READY</Badge>}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 font-mono text-xs">
          <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800">
            <span className="text-slate-400 block mb-1">Architecture</span>
            <span className="text-cyan-300 font-bold text-sm">
              {modelInfo?.model_name || 'OptunaTuned_XGBoost'}
            </span>
          </div>

          <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800">
            <span className="text-slate-400 block mb-1">Model Version</span>
            <span className="text-slate-200 font-bold text-sm">
              v{modelInfo?.model_version || '1.0.0'}
            </span>
          </div>

          <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800">
            <span className="text-slate-400 block mb-1">Decision Threshold</span>
            <span className="text-amber-400 font-bold text-sm">
              τ = {modelInfo?.decision_threshold ?? 0.5}
            </span>
          </div>

          <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800">
            <span className="text-slate-400 block mb-1">Feature Observability</span>
            <span className="text-emerald-400 font-bold text-sm">
              Strict Unidirectional
            </span>
          </div>
        </div>
      </Card>

      {/* Two-Split Reconciliation Card: Day 1 Test vs Day 2 Temporal Holdout */}
      <Card
        title="Authoritative Split Reconciliation (M9 Independent Verification)"
        subtitle="Distinguishes within-dataset held-out test performance from out-of-distribution temporal shift"
        badge={<Badge variant="cyan">M9 AUDIT</Badge>}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-xs">
          {/* Day 1 Held-Out Test */}
          <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-3">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <span className="font-semibold text-cyan-300">Day 1 Held-Out Test Split</span>
              <Badge variant="cyan">19,942 Flows</Badge>
            </div>
            <div className="text-[11px] text-slate-400">
              UNSW-NB15 Jan 22, 2015 capture (12:43 to 12:53 UTC). Chronologically separated from training.
            </div>
            <div className="grid grid-cols-2 gap-2 text-center pt-1">
              <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                <span className="block text-[10px] text-slate-400">Accuracy</span>
                <span className="text-sm font-bold text-slate-100">
                  {benchmark ? (benchmark.heldout_test.accuracy * 100).toFixed(2) + '%' : '98.10%'}
                </span>
              </div>
              <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                <span className="block text-[10px] text-slate-400">Attack Recall</span>
                <span className="text-sm font-bold text-emerald-400">
                  {benchmark ? (benchmark.heldout_test.recall * 100).toFixed(2) + '%' : '97.78%'}
                </span>
              </div>
              <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                <span className="block text-[10px] text-slate-400">Precision</span>
                <span className="text-sm font-bold text-cyan-400">
                  {benchmark ? (benchmark.heldout_test.precision * 100).toFixed(2) + '%' : '95.85%'}
                </span>
              </div>
              <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                <span className="block text-[10px] text-slate-400">Specificity</span>
                <span className="text-sm font-bold text-indigo-400">
                  {benchmark ? (benchmark.heldout_test.specificity * 100).toFixed(2) + '%' : '98.24%'}
                </span>
              </div>
            </div>
            <div className="text-[11px] text-slate-400 pt-1">
              Confusion Matrix: <code className="text-slate-300">[TN: 13,836, FP: 248, FN: 130, TP: 5,728]</code>
            </div>
          </div>

          {/* Day 2 Temporal Holdout */}
          <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-3">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <span className="font-semibold text-amber-300">Day 2 Out-of-Distribution Holdout</span>
              <Badge variant="indigo">20,000 Flows</Badge>
            </div>
            <div className="text-[11px] text-slate-400">
              UNSW-NB15 Feb 15, 2015 capture (24 days after training capture). Independent recording session.
            </div>
            <div className="grid grid-cols-2 gap-2 text-center pt-1">
              <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                <span className="block text-[10px] text-slate-400">Accuracy</span>
                <span className="text-sm font-bold text-slate-100">
                  {benchmark ? (benchmark.day2_temporal_holdout.accuracy * 100).toFixed(2) + '%' : '96.97%'}
                </span>
              </div>
              <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                <span className="block text-[10px] text-slate-400">Attack Recall</span>
                <span className="text-sm font-bold text-emerald-400">
                  {benchmark ? (benchmark.day2_temporal_holdout.recall * 100).toFixed(2) + '%' : '98.37%'}
                </span>
              </div>
              <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                <span className="block text-[10px] text-slate-400">Precision</span>
                <span className="text-sm font-bold text-cyan-400">
                  {benchmark ? (benchmark.day2_temporal_holdout.precision * 100).toFixed(2) + '%' : '90.57%'}
                </span>
              </div>
              <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                <span className="block text-[10px] text-slate-400">Specificity</span>
                <span className="text-sm font-bold text-indigo-400">
                  {benchmark ? (benchmark.day2_temporal_holdout.specificity * 100).toFixed(2) + '%' : '96.50%'}
                </span>
              </div>
            </div>
            <div className="text-[11px] text-slate-400 pt-1">
              Confusion Matrix: <code className="text-slate-300">[TN: 14,384, FP: 522, FN: 83, TP: 5,011]</code>
            </div>
          </div>
        </div>
      </Card>

      {/* Feature Contract & Availability Timing Table */}
      <Card
        title="Feature Policy & Availability Timing Contract (13 Features)"
        subtitle="Distinguishes packet-arrival, flow-prefix, and flow-completion features"
        badge={<Badge variant="indigo">AUDITED</Badge>}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs font-mono">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 uppercase text-[11px]">
                <th className="py-2.5 px-3">#</th>
                <th className="py-2.5 px-3">Feature Name</th>
                <th className="py-2.5 px-3">Availability Timing</th>
                <th className="py-2.5 px-3">Type</th>
                <th className="py-2.5 px-3">Description & Physical Meaning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {FEATURE_CONTRACT_DETAILS.map((f, i) => (
                <tr key={f.name} className="hover:bg-slate-800/30">
                  <td className="py-2.5 px-3 text-slate-500">{i + 1}</td>
                  <td className="py-2.5 px-3 font-semibold text-cyan-300">{f.name}</td>
                  <td className="py-2.5 px-3">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                        f.timing === 'Packet Arrival'
                          ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/60'
                          : f.timing === 'Flow Prefix'
                          ? 'bg-amber-950/60 text-amber-300 border border-amber-800/60'
                          : 'bg-cyan-950/60 text-cyan-300 border border-cyan-800/60'
                      }`}
                    >
                      {f.timing}
                    </span>
                  </td>
                  <td className="py-2.5 px-3 text-slate-400">{f.type}</td>
                  <td className="py-2.5 px-3 text-slate-300">{f.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Two-Column Grid: Prohibited Columns & Tournament Ledger */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Prohibited Columns */}
        <Card
          title="Strictly Prohibited Columns (Zero-Return Policy)"
          subtitle="Features rejected by backend audit to protect unidirectional link observability"
          badge={<Badge variant="slate">ENFORCED</Badge>}
        >
          <div className="space-y-2 text-xs font-mono">
            {PROHIBITED_COLUMNS.map((col) => (
              <div key={col.name} className="p-2.5 rounded bg-rose-950/20 border border-rose-900/40 text-slate-300">
                <span className="font-semibold text-rose-400 block">{col.name}</span>
                <span className="text-[11px] text-slate-400">{col.reason}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Model Tournament Ledger */}
        <Card
          title="Authoritative Model Tournament Ledger (M9 Reproduction)"
          subtitle="Held-out evaluation benchmark on UNSW-NB15 (19,942 test flows)"
          badge={<Badge variant="cyan">M9 AUDIT</Badge>}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs font-mono">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 uppercase text-[11px]">
                  <th className="py-2.5 px-3">Model</th>
                  <th className="py-2.5 px-3">Accuracy</th>
                  <th className="py-2.5 px-3">Recall</th>
                  <th className="py-2.5 px-3">Precision</th>
                  <th className="py-2.5 px-3">Specificity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {AUTHORITATIVE_M9_MODELS.map((m) => (
                  <tr key={m.name} className="hover:bg-slate-800/30">
                    <td className="py-2.5 px-3">
                      <div className="font-semibold text-slate-200">{m.name}</div>
                      <div className="text-[10px] text-cyan-400">{m.status}</div>
                    </td>
                    <td className="py-2.5 px-3 text-slate-100 font-bold">{m.accuracy}</td>
                    <td className="py-2.5 px-3 text-emerald-400 font-bold">{m.recall}</td>
                    <td className="py-2.5 px-3 text-cyan-400 font-bold">{m.precision}</td>
                    <td className="py-2.5 px-3 text-indigo-400 font-bold">{m.specificity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[10px] text-slate-400 font-mono">
            *Verified with strict chronological non-overlap (Jan 22, 2015 train vs test).
          </p>
        </Card>
      </div>

      {/* Cross-Dataset Scientific Limits & M10.1 Provenance Disclosure */}
      <Card
        title="Scientific Boundaries & M10.1 Provenance Audit Disclosure"
        subtitle="Mandatory disclosures regarding cross-dataset generalization limits"
        badge={<Badge variant="indigo">M10.1 AUDITED</Badge>}
      >
        <div className="space-y-3 text-xs text-slate-300">
          <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2">
            <h4 className="font-semibold text-cyan-300 flex items-center gap-1.5 font-mono">
              <CheckCircle2 className="w-4 h-4 text-cyan-400" />
              1. Direct Production Model Transfer Feasibility: UNSUPPORTED
            </h4>
            <p className="text-slate-400">
              The production model relies on <code className="text-amber-300">sttl</code> (IP Time-to-Live) and{' '}
              <code className="text-amber-300">is_sm_ips_ports</code>. In CICFlowMeter / CICIDS2017 datasets, IP TTL is omitted,
              and public captures anonymize or strip IP addresses. Direct transfer of the frozen model without these fields is
              formally classified as unsupported to prevent arbitrary feature fabrication.
            </p>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2">
            <h4 className="font-semibold text-amber-300 flex items-center gap-1.5 font-mono">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              2. M10.1 Evidence Audit Verdict on CICIDS2017
            </h4>
            <p className="text-slate-400">
              In Milestone 10, an evaluation on 10,000 flows was previously labeled "CICIDS2017 Stream". The M10.1 evidence audit
              confirmed that official raw CICIDS2017 files were absent locally (0 MB) and traced the 10,000 flows to an in-memory
              synthetic test fixture generated for adapter testing. As mandated, this result is marked{' '}
              <span className="text-rose-400 font-semibold font-mono">UNVERIFIED as real-world cross-dataset performance</span>.
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
};
