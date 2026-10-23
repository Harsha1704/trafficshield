import React, { useState } from 'react';
import {
  ShieldAlert,
  Search,
  Filter,
  CheckCircle2,
  Clock,
  Save,
  Tag,
  AlertTriangle,
  Info,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
} from 'lucide-react';
import type { AlertStatus, RiskLevel, SecurityAlert } from '../types/api';
import { Card } from '../components/common/Card';
import { SeverityBadge, StatusBadge, Badge } from '../components/common/Badge';
import { Button } from '../components/common/Button';
import { Modal } from '../components/common/Modal';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { api } from '../services/api';

interface AlertsPageProps {
  alerts: SecurityAlert[];
  totalAlerts: number;
  currentPage: number;
  perPage: number;
  loading: boolean;
  onPageChange: (page: number) => void;
  onFilterChange: (filters: { status?: string; risk_level?: string; search?: string }) => void;
  onAlertUpdated: (updated: SecurityAlert) => void;
  selectedAlert: SecurityAlert | null;
  onSelectAlert: (alert: SecurityAlert | null) => void;
}

export const AlertsPage: React.FC<AlertsPageProps> = ({
  alerts,
  totalAlerts,
  currentPage,
  perPage,
  loading,
  onPageChange,
  onFilterChange,
  onAlertUpdated,
  selectedAlert,
  onSelectAlert,
}) => {
  const [filterStatus, setFilterStatus] = useState<string>('ALL');
  const [filterSeverity, setFilterSeverity] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Investigation Modal state
  const [editStatus, setEditStatus] = useState<AlertStatus>('NEW');
  const [editNotes, setEditNotes] = useState<string>('');
  const [savingNotes, setSavingNotes] = useState<boolean>(false);
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false);

  // Sync modal form when selected alert changes
  React.useEffect(() => {
    if (selectedAlert) {
      setEditStatus(selectedAlert.status);
      setEditNotes(selectedAlert.analyst_notes || '');
      setSaveSuccess(false);
    }
  }, [selectedAlert]);

  const handleStatusFilter = (st: string) => {
    setFilterStatus(st);
    onFilterChange({
      status: st === 'ALL' ? undefined : st,
      risk_level: filterSeverity === 'ALL' ? undefined : filterSeverity,
      search: searchQuery || undefined,
    });
  };

  const handleSeverityFilter = (sev: string) => {
    setFilterSeverity(sev);
    onFilterChange({
      status: filterStatus === 'ALL' ? undefined : filterStatus,
      risk_level: sev === 'ALL' ? undefined : sev,
      search: searchQuery || undefined,
    });
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onFilterChange({
      status: filterStatus === 'ALL' ? undefined : filterStatus,
      risk_level: filterSeverity === 'ALL' ? undefined : filterSeverity,
      search: searchQuery || undefined,
    });
  };

  const handleSaveTriage = async () => {
    if (!selectedAlert) return;
    setSavingNotes(true);
    setSaveSuccess(false);

    try {
      const updated = await api.updateAlert(selectedAlert.id, {
        status: editStatus,
        analyst_notes: editNotes,
      });
      onAlertUpdated(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      alert(`Failed to update alert: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSavingNotes(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(totalAlerts / perPage));

  return (
    <div className="space-y-6">
      {/* Top Controls Bar */}
      <Card>
        <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-4">
          {/* Status & Severity Filter Pills */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400 font-mono">Status:</span>
            <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-xs">
              {['ALL', 'NEW', 'INVESTIGATING', 'RESOLVED', 'FALSE_POSITIVE'].map((st) => (
                <button
                  key={st}
                  onClick={() => handleStatusFilter(st)}
                  className={`px-2 py-1 rounded transition-colors font-mono ${
                    filterStatus === st
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {st === 'FALSE_POSITIVE' ? 'FP' : st}
                </button>
              ))}
            </div>

            <span className="text-xs text-slate-400 font-mono ml-2">Risk:</span>
            <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-xs">
              {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((sev) => (
                <button
                  key={sev}
                  onClick={() => handleSeverityFilter(sev)}
                  className={`px-2 py-1 rounded transition-colors font-mono ${
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

          {/* Search Form */}
          <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
            <div className="relative flex-1 sm:w-64">
              <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-500" />
              <input
                type="text"
                placeholder="Search alerts or notes..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
              />
            </div>
            <Button size="sm" type="submit" variant="secondary">
              Filter
            </Button>
          </form>
        </div>
      </Card>

      {/* Main Alerts Table */}
      <Card
        title="Durable Security Alerts & Incident Store"
        subtitle={`Showing ${alerts.length} of ${totalAlerts} persisted security events`}
        badge={<Badge variant="indigo">SQLITE PERSISTENT</Badge>}
      >
        {loading ? (
          <LoadingSpinner message="Querying persistent alert log..." />
        ) : alerts.length === 0 ? (
          <EmptyState
            title="No Matching Alerts"
            description="No alerts match the active filters or search terms. Try clearing filters or running a batch in Traffic Analysis."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 font-mono uppercase tracking-wider text-[11px]">
                  <th className="py-2.5 px-3">Alert ID / Request</th>
                  <th className="py-2.5 px-3">Timestamp (UTC)</th>
                  <th className="py-2.5 px-3">Severity</th>
                  <th className="py-2.5 px-3">Anomaly Score</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Top Attribution</th>
                  <th className="py-2.5 px-3 text-right">Triage</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {alerts.map((alert) => {
                  const topAttr = alert.top_contributing_features?.[0];
                  return (
                    <tr
                      key={alert.id}
                      className="hover:bg-slate-800/40 transition-colors group cursor-pointer"
                      onClick={() => onSelectAlert(alert)}
                    >
                      <td className="py-3 px-3">
                        <div className="font-semibold text-slate-200">{alert.id.substring(0, 8)}...</div>
                        <div className="text-[10px] text-slate-500">{alert.request_id ? `${alert.request_id.substring(0, 12)}...` : 'N/A'}</div>
                      </td>
                      <td className="py-3 px-3 text-slate-300">
                        {alert.timestamp ? new Date(alert.timestamp).toISOString().replace('T', ' ').substring(0, 19) : 'N/A'}
                      </td>
                      <td className="py-3 px-3">
                        <SeverityBadge severity={alert.risk_level} />
                      </td>
                      <td className="py-3 px-3">
                        <span className={`font-semibold ${alert.anomaly_score >= 0.5 ? 'text-rose-400' : 'text-emerald-400'}`}>
                          {alert.anomaly_score.toFixed(4)}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <StatusBadge status={alert.status} />
                      </td>
                      <td className="py-3 px-3 text-slate-400 max-w-xs truncate">
                        {topAttr ? (
                          <span>
                            <span className="text-cyan-400 font-semibold">{topAttr.feature}</span> ({topAttr.contribution})
                          </span>
                        ) : (
                          <span className="text-slate-600">None</span>
                        )}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <button
                          className="px-2.5 py-1 text-[11px] rounded bg-slate-800 group-hover:bg-cyan-950/70 group-hover:text-cyan-300 border border-slate-700/60 group-hover:border-cyan-500/40 transition-colors"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectAlert(alert);
                          }}
                        >
                          Investigate
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Bar */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-4 pt-3 border-t border-slate-800 text-xs text-slate-400">
            <span>
              Page {currentPage} of {totalPages}
            </span>
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="secondary"
                disabled={currentPage <= 1}
                onClick={() => onPageChange(currentPage - 1)}
                icon={<ChevronLeft className="w-3.5 h-3.5" />}
              >
                Prev
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={currentPage >= totalPages}
                onClick={() => onPageChange(currentPage + 1)}
                icon={<ChevronRight className="w-3.5 h-3.5" />}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Investigation Modal Drawer */}
      {selectedAlert && (
        <Modal
          isOpen={Boolean(selectedAlert)}
          onClose={() => onSelectAlert(null)}
          maxWidth="4xl"
          title={
            <div className="flex items-center gap-3">
              <span>Alert Investigation #{selectedAlert.id.substring(0, 8)}</span>
              <SeverityBadge severity={selectedAlert.risk_level} />
            </div>
          }
          subtitle={`Detected on ${selectedAlert.timestamp ? new Date(selectedAlert.timestamp).toISOString() : 'N/A'}`}
        >
          <div className="space-y-5">
            {/* Top Score Banner */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 text-center font-mono">
              <div>
                <span className="block text-[11px] text-slate-400">Anomaly Score</span>
                <span className={`text-xl font-bold ${selectedAlert.anomaly_score >= 0.5 ? 'text-rose-400' : 'text-emerald-400'}`}>
                  {selectedAlert.anomaly_score.toFixed(6)}
                </span>
              </div>
              <div>
                <span className="block text-[11px] text-slate-400">Decision Threshold</span>
                <span className="text-xl font-bold text-amber-400">τ = {selectedAlert.decision_threshold}</span>
              </div>
              <div>
                <span className="block text-[11px] text-slate-400">Model Artifact</span>
                <span className="text-xs text-cyan-300 font-semibold">{selectedAlert.model_name} (v{selectedAlert.model_version})</span>
              </div>
            </div>

            {/* Feature Attributions / Explainability */}
            <div>
              <h4 className="text-xs font-semibold text-slate-200 uppercase tracking-wider mb-2 flex items-center gap-1.5 font-mono">
                <AlertTriangle className="w-3.5 h-3.5 text-cyan-400" />
                Root Cause Attributions & Explanations
              </h4>
              {selectedAlert.top_contributing_features && selectedAlert.top_contributing_features.length > 0 ? (
                <div className="space-y-2">
                  {selectedAlert.top_contributing_features.map((f, i) => (
                    <div key={i} className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 text-xs">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-mono font-semibold text-cyan-300">{f.feature} = {f.value}</span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-slate-800 text-slate-300">
                          {f.contribution} contribution
                        </span>
                      </div>
                      <p className="text-slate-400 text-xs">{f.reason}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-500 italic p-3 bg-slate-900/40 rounded-lg">
                  No salient feature deviation beyond baseline was recorded.
                </p>
              )}
            </div>

            {/* Validated Forward Features Grid */}
            <div>
              <h4 className="text-xs font-semibold text-slate-200 uppercase tracking-wider mb-2 font-mono">
                Validated Input Features (Forward Link Direction)
              </h4>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
                {Object.entries(selectedAlert.input_features || {}).map(([k, v]) => (
                  <div key={k} className="p-2 rounded bg-slate-900/50 border border-slate-800">
                    <span className="block text-[10px] text-slate-400 truncate" title={k}>{k}</span>
                    <span className="font-semibold text-slate-200">{typeof v === 'number' ? (v > 1000 ? v.toLocaleString() : v) : String(v)}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Analyst Triage & Investigation Workflow */}
            <div className="pt-4 border-t border-slate-800 space-y-3">
              <h4 className="text-xs font-semibold text-slate-200 uppercase tracking-wider font-mono">
                Analyst Incident Triage
              </h4>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1 font-mono">Update Status:</label>
                  <select
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value as AlertStatus)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-cyan-500/50 font-mono"
                  >
                    <option value="NEW">NEW (Unacknowledged)</option>
                    <option value="INVESTIGATING">INVESTIGATING (In Triage)</option>
                    <option value="RESOLVED">RESOLVED (Threat Mitigated)</option>
                    <option value="FALSE_POSITIVE">FALSE POSITIVE (Benign Traffic)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs text-slate-400 mb-1 font-mono">Acknowledged At:</label>
                  <div className="px-3 py-2 rounded-lg bg-slate-900/40 border border-slate-800/80 text-xs font-mono text-slate-400">
                    {selectedAlert.acknowledged_at
                      ? new Date(selectedAlert.acknowledged_at).toISOString().replace('T', ' ').substring(0, 19)
                      : 'Pending analyst acknowledgement'}
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-xs text-slate-400 mb-1 font-mono">Analyst Investigation Notes:</label>
                <textarea
                  rows={3}
                  value={editNotes}
                  onChange={(e) => setEditNotes(e.target.value)}
                  placeholder="Record investigation findings, firewall rules updated, or benign false positive rationale..."
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
                />
              </div>

              <div className="flex items-center justify-between pt-2">
                <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
                  <Info className="w-3.5 h-3.5 shrink-0" />
                  <span>Analyst notes update triage status; they do not alter model weights or testbed labels.</span>
                </div>
                <div className="flex items-center gap-2">
                  {saveSuccess && (
                    <span className="text-xs text-emerald-400 font-mono flex items-center gap-1">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Saved!
                    </span>
                  )}
                  <Button
                    size="sm"
                    onClick={handleSaveTriage}
                    loading={savingNotes}
                    icon={<Save className="w-3.5 h-3.5" />}
                  >
                    Save Triage Notes
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
