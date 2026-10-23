import React, { useState } from 'react';
import {
  Settings,
  Database,
  Wifi,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  Server,
  Layers,
} from 'lucide-react';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { getApiBaseUrl, setApiBaseUrl, api } from '../services/api';

interface SettingsPageProps {
  onRefreshData: () => void;
  onSeedDemo: () => void;
  seeding: boolean;
}

export const SettingsPage: React.FC<SettingsPageProps> = ({
  onRefreshData,
  onSeedDemo,
  seeding,
}) => {
  const [apiUrl, setApiUrlState] = useState<string>(getApiBaseUrl());
  const [testingConnection, setTestingConnection] = useState<boolean>(false);
  const [connectionStatus, setConnectionStatus] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  const handleSaveApiUrl = () => {
    setApiBaseUrl(apiUrl.trim());
    setConnectionStatus({ ok: true, message: 'API Base URL saved successfully.' });
    onRefreshData();
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    setConnectionStatus(null);
    try {
      await api.checkHealth();
      setConnectionStatus({ ok: true, message: 'Successfully connected to TrafficShield Flask API.' });
    } catch (err: unknown) {
      setConnectionStatus({
        ok: false,
        message: err instanceof Error ? err.message : 'Connection failed.',
      });
    } finally {
      setTestingConnection(false);
    }
  };

  const handleResetDefault = () => {
    const defaultUrl = 'http://localhost:5000/api/v1';
    setApiUrlState(defaultUrl);
    setApiBaseUrl(defaultUrl);
    setConnectionStatus({ ok: true, message: 'Reset API URL to default (http://localhost:5000/api/v1).' });
    onRefreshData();
  };

  return (
    <div className="space-y-6">
      <Card
        title="API Server & Infrastructure Configuration"
        subtitle="Manage endpoint routing and communication with the Flask ML scoring service"
      >
        <div className="space-y-4 max-w-xl">
          <div>
            <label className="block text-xs text-slate-400 font-mono mb-1">
              TrafficShield API Base URL:
            </label>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={apiUrl}
                onChange={(e) => setApiUrlState(e.target.value)}
                placeholder="http://localhost:5000/api/v1"
                className="flex-1 px-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500/50"
              />
              <Button size="sm" onClick={handleSaveApiUrl}>
                Save
              </Button>
            </div>
            <p className="mt-1 text-[11px] text-slate-400">
              Configures client network requests. Automatically saved to persistent browser storage.
            </p>
          </div>

          <div className="flex items-center gap-2 pt-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={handleTestConnection}
              loading={testingConnection}
              icon={<Wifi className="w-3.5 h-3.5" />}
            >
              Test Connection
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleResetDefault}
              icon={<RotateCcw className="w-3.5 h-3.5" />}
            >
              Reset to Default
            </Button>
          </div>

          {connectionStatus && (
            <div
              className={`p-3 rounded-lg border text-xs flex items-center gap-2 ${
                connectionStatus.ok
                  ? 'bg-emerald-950/60 border-emerald-800/60 text-emerald-300'
                  : 'bg-rose-950/60 border-rose-800/60 text-rose-300'
              }`}
            >
              {connectionStatus.ok ? (
                <CheckCircle2 className="w-4 h-4 shrink-0" />
              ) : (
                <AlertCircle className="w-4 h-4 shrink-0" />
              )}
              <span>{connectionStatus.message}</span>
            </div>
          )}
        </div>
      </Card>

      {/* Database Management Card */}
      <Card
        title="Persistent SOC Storage Management"
        subtitle="Manage SQLite incident storage and demonstration data"
      >
        <div className="space-y-4 max-w-xl">
          <p className="text-xs text-slate-400">
            TrafficShield persists security alerts, triage status, and analyst notes in an ACID-compliant SQLite
            database (<code className="text-cyan-300">trafficshield_dev.db</code>).
          </p>

          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant="secondary"
              onClick={onSeedDemo}
              loading={seeding}
              icon={<Database className="w-3.5 h-3.5" />}
            >
              Seed 5 Demonstration Alerts
            </Button>
          </div>
        </div>
      </Card>

      {/* Deployment & Environmental Ledger */}
      <Card
        title="Environmental & System Specifications"
        subtitle="Active software stack and dependencies"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs font-mono">
          <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800">
            <span className="text-slate-400 block mb-1">Backend Framework</span>
            <span className="text-slate-200 font-bold">Python 3.14 + Flask 3.x</span>
          </div>
          <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800">
            <span className="text-slate-400 block mb-1">Frontend Stack</span>
            <span className="text-cyan-300 font-bold">React 19 + TypeScript + Vite</span>
          </div>
          <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800">
            <span className="text-slate-400 block mb-1">ML Engine</span>
            <span className="text-emerald-300 font-bold">XGBoost 3.4.1 (Optuna Tuned)</span>
          </div>
          <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800">
            <span className="text-slate-400 block mb-1">Database Store</span>
            <span className="text-amber-300 font-bold">SQLite 3 (SQLAlchemy)</span>
          </div>
        </div>
      </Card>
    </div>
  );
};
