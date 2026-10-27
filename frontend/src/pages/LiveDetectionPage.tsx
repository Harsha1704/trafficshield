import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Radio,
  Play,
  Square,
  Pause,
  RotateCcw,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Layers,
  Activity,
  Zap,
  Clock,
  ShieldCheck,
  ShieldAlert,
  HardDrive,
  Network,
  Info,
  TrendingUp,
} from 'lucide-react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from 'recharts';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { SeverityBadge, Badge } from '../components/common/Badge';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { api, ApiClientError } from '../services/api';
import type {
  CaptureStatusResponse,
  IntervalTelemetryItem,
  NetworkInterfaceItem,
  SamplePcapItem,
  StreamingEventRecord,
} from '../types/api';

function formatBytes(bytes: number): string {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

export const LiveDetectionPage: React.FC = () => {
  // Capture session status
  const [status, setStatus] = useState<CaptureStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Configuration options
  const [mode, setMode] = useState<'PCAP' | 'LIVE'>('PCAP');
  const [interfaces, setInterfaces] = useState<NetworkInterfaceItem[]>([]);
  const [selectedInterface, setSelectedInterface] = useState<string>('');
  const [driverAvailable, setDriverAvailable] = useState<boolean>(false);
  const [driverMessage, setDriverMessage] = useState<string>('');

  const [samplePcaps, setSamplePcaps] = useState<SamplePcapItem[]>([]);
  const [selectedPcap, setSelectedPcap] = useState<string>('');
  const [speedMultiplier, setSpeedMultiplier] = useState<number>(2.0);

  const pollingRef = useRef<number | null>(null);

  // Fetch interfaces and sample PCAPs on mount
  useEffect(() => {
    async function loadPrerequisites() {
      try {
        const [ifaceData, pcapsData, initialStatus] = await Promise.all([
          api.getInterfaces(),
          api.getSamplePcaps(),
          api.getCaptureStatus(),
        ]);

        setInterfaces(ifaceData.interfaces || []);
        setDriverAvailable(ifaceData.driver_available);
        setDriverMessage(ifaceData.driver_status);
        if (ifaceData.interfaces && ifaceData.interfaces.length > 0) {
          setSelectedInterface(ifaceData.interfaces[0].name);
        }

        setSamplePcaps(pcapsData || []);
        if (pcapsData && pcapsData.length > 0) {
          setSelectedPcap(pcapsData[0].path);
        }

        setStatus(initialStatus);
      } catch (err: any) {
        console.error('Failed to load capture initial data:', err);
      } finally {
        setLoading(false);
      }
    }

    loadPrerequisites();
  }, []);

  // Poll status periodically (1s when active, 3s when stopped)
  const pollStatus = useCallback(async () => {
    try {
      const data = await api.getCaptureStatus();
      setStatus(data);
    } catch {
      // Ignore background transient errors
    }
  }, []);

  useEffect(() => {
    const isSessionActive =
      status?.worker_state === 'RUNNING' ||
      status?.worker_state === 'STARTING' ||
      status?.worker_state === 'PAUSED';

    const intervalMs = isSessionActive ? 1000 : 3000;
    pollingRef.current = window.setInterval(pollStatus, intervalMs);

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [status?.worker_state, pollStatus]);

  // Actions
  const handleStartReplay = async () => {
    if (!selectedPcap) {
      setErrorBanner('Please select or specify a valid PCAP capture file.');
      return;
    }
    setErrorBanner(null);
    setActionLoading(true);
    try {
      const newStatus = await api.startPcapReplay({
        pcap_path: selectedPcap,
        speed_multiplier: speedMultiplier,
      });
      setStatus(newStatus);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to start PCAP replay.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleStartLive = async () => {
    if (!selectedInterface) {
      setErrorBanner('Please select an authorized network interface.');
      return;
    }
    setErrorBanner(null);
    setActionLoading(true);
    try {
      const newStatus = await api.startLiveCapture({
        interface: selectedInterface,
      });
      setStatus(newStatus);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to start live interface capture.');
    } finally {
      setActionLoading(false);
    }
  };

  const handlePause = async () => {
    setActionLoading(true);
    try {
      const newStatus = await api.pauseCapture();
      setStatus(newStatus);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to pause session.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleResume = async () => {
    setActionLoading(true);
    try {
      const newStatus = await api.resumeCapture();
      setStatus(newStatus);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to resume session.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleStop = async () => {
    setActionLoading(true);
    try {
      const newStatus = await api.stopCapture();
      setStatus(newStatus);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to stop session.');
    } finally {
      setActionLoading(false);
    }
  };

  const isRunning = status?.worker_state === 'RUNNING';
  const isPaused = status?.worker_state === 'PAUSED';
  const isStarting = status?.worker_state === 'STARTING';
  const isActive = isRunning || isPaused || isStarting;

  const renderStateBadge = (state?: string) => {
    switch (state) {
      case 'RUNNING':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
            RUNNING
          </span>
        );
      case 'PAUSED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
            <span className="w-2 h-2 rounded-full bg-amber-400"></span>
            PAUSED
          </span>
        );
      case 'STARTING':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-cyan-400"></span>
            STARTING
          </span>
        );
      case 'DEGRADED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-yellow-500/10 text-yellow-400 border border-yellow-500/30">
            <span className="w-2 h-2 rounded-full bg-yellow-400"></span>
            DEGRADED
          </span>
        );
      case 'FAILED':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/30">
            <span className="w-2 h-2 rounded-full bg-red-400"></span>
            FAILED
          </span>
        );
      default:
        if (status?.session_summary?.is_historical) {
          return (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-300 border border-indigo-500/30">
              <span className="w-2 h-2 rounded-full bg-indigo-400"></span>
              HISTORICAL
            </span>
          );
        }
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700">
            <span className="w-2 h-2 rounded-full bg-slate-500"></span>
            STOPPED
          </span>
        );
    }
  };

  const chartData = (status?.intervals || []).slice(-12).map((item) => {
    const timeStr = item.timestamp.includes('T')
      ? item.timestamp.split('T')[1].substring(0, 8)
      : item.timestamp.substring(11, 19);
    const flowsPerSec = item.interval_seconds > 0 ? Number((item.flows_scored / item.interval_seconds).toFixed(2)) : 0;
    const anomPerSec = item.interval_seconds > 0 ? Number((item.anomalies_detected / item.interval_seconds).toFixed(2)) : 0;
    return {
      time: timeStr,
      mbps: Number(item.throughput_mbps.toFixed(4)),
      flowsPerSec,
      anomPerSec,
      packets: item.packets_captured,
      drops: item.drops,
    };
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[500px]">
        <LoadingSpinner message="Connecting to capture worker..." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-800/80 pb-5">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-white tracking-tight">
              Live Network Detection & PCAP Replay
            </h1>
            {renderStateBadge(status?.worker_state)}
          </div>
          <p className="text-slate-400 text-sm mt-1">
            Real-time packet capture, stateful unidirectional flow reconstruction and streaming ML inference.
          </p>
        </div>

        {/* Global Provenance Tag */}
        <div className="flex items-center gap-2">
          <Badge
            variant={status?.capture_mode === 'LIVE_CAPTURE' ? 'danger' : 'cyan'}
          >
            {status?.capture_mode === 'LIVE_CAPTURE'
              ? 'PASSIVE LIVE CAPTURE'
              : status?.capture_mode === 'PCAP_REPLAY'
              ? 'OFFLINE PCAP REPLAY'
              : 'IDLE / NO SOURCE'}
          </Badge>
        </div>
      </div>

      {/* Error Alert Banner */}
      {errorBanner && (
        <div className="p-4 rounded-lg bg-red-950/40 border border-red-500/40 text-red-200 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-400 mt-0.5 shrink-0" />
          <div className="text-sm">
            <p className="font-semibold">Capture Operation Error</p>
            <p className="text-red-300 mt-0.5">{errorBanner}</p>
          </div>
        </div>
      )}

      {/* Control Card & Mode Selector */}
      <Card className="border border-slate-800 bg-[#090d16]/90">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-800/80">
          <div className="flex items-center gap-2 bg-slate-900/80 p-1 rounded-lg border border-slate-800">
            <button
              onClick={() => !isActive && setMode('PCAP')}
              disabled={isActive}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                mode === 'PCAP'
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                  : 'text-slate-400 hover:text-white'
              } ${isActive ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              Offline PCAP Replay
            </button>
            <button
              onClick={() => !isActive && setMode('LIVE')}
              disabled={isActive}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                mode === 'LIVE'
                  ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30'
                  : 'text-slate-400 hover:text-white'
              } ${isActive ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              Passive Live Interface
            </button>
          </div>

          {/* Action Control Buttons */}
          <div className="flex items-center gap-2">
            {!isActive ? (
              <Button
                variant="primary"
                size="sm"
                onClick={mode === 'PCAP' ? handleStartReplay : handleStartLive}
                disabled={actionLoading || (mode === 'LIVE' && !driverAvailable)}
              >
                <Play className="w-4 h-4 mr-1.5" />
                {actionLoading ? 'Starting...' : `Start ${mode === 'PCAP' ? 'Replay' : 'Capture'}`}
              </Button>
            ) : (
              <>
                {isRunning ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handlePause}
                    disabled={actionLoading}
                  >
                    <Pause className="w-4 h-4 mr-1.5" />
                    Pause
                  </Button>
                ) : isPaused ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleResume}
                    disabled={actionLoading}
                  >
                    <Play className="w-4 h-4 mr-1.5" />
                    Resume
                  </Button>
                ) : null}

                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleStop}
                  disabled={actionLoading}
                >
                  <Square className="w-4 h-4 mr-1.5" />
                  Stop Session
                </Button>
              </>
            )}
          </div>
        </div>

        {/* Mode Specific Inputs */}
        <div className="mt-4">
          {mode === 'PCAP' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                  Select PCAP Replay File
                </label>
                {samplePcaps.length > 0 ? (
                  <select
                    value={selectedPcap}
                    onChange={(e) => setSelectedPcap(e.target.value)}
                    disabled={isActive}
                    className="w-full px-3 py-2 text-sm bg-slate-900 border border-slate-700/80 rounded-md text-white focus:outline-none focus:border-cyan-500 disabled:opacity-50"
                  >
                    {samplePcaps.map((p) => (
                      <option key={p.path} value={p.path}>
                        {p.filename} ({Math.round(p.size_bytes / 1024)} KB)
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={selectedPcap}
                    onChange={(e) => setSelectedPcap(e.target.value)}
                    disabled={isActive}
                    placeholder="e.g. data/captures/network_scan.pcap"
                    className="w-full px-3 py-2 text-sm bg-slate-900 border border-slate-700/80 rounded-md text-white focus:outline-none focus:border-cyan-500 disabled:opacity-50"
                  />
                )}
                <p className="text-[11px] text-slate-500 mt-1">
                  Validated against standard PCAP/PCAPNG format headers. Payloads are discarded immediately.
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                  Replay Speed Multiplier: {speedMultiplier === 0 ? 'Max (Unthrottled)' : `${speedMultiplier}x`}
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="0"
                    max="10"
                    step="0.5"
                    value={speedMultiplier}
                    onChange={(e) => setSpeedMultiplier(parseFloat(e.target.value))}
                    disabled={isActive}
                    className="w-full accent-cyan-400 disabled:opacity-50"
                  />
                  <span className="text-xs text-slate-400 font-mono w-14 text-right">
                    {speedMultiplier === 0 ? 'MAX' : `${speedMultiplier}x`}
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 mt-1">
                  Controls inter-packet pacing delay. 1.0x matches real-world recorded intervals.
                </p>
              </div>
            </div>
          ) : (
            <div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                    Authorized Network Interface
                  </label>
                  <select
                    value={selectedInterface}
                    onChange={(e) => setSelectedInterface(e.target.value)}
                    disabled={isActive || !driverAvailable}
                    className="w-full px-3 py-2 text-sm bg-slate-900 border border-slate-700/80 rounded-md text-white focus:outline-none focus:border-indigo-500 disabled:opacity-50"
                  >
                    {interfaces.map((iface) => (
                      <option key={iface.name} value={iface.name}>
                        {iface.name} {iface.ipv4_addresses.length ? `(${iface.ipv4_addresses[0]})` : ''}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                    BPF Capture Filter
                  </label>
                  <input
                    type="text"
                    disabled
                    value="ip (IPv4 network traffic)"
                    className="w-full px-3 py-2 text-sm bg-slate-900/50 border border-slate-800 rounded-md text-slate-400 cursor-not-allowed"
                  />
                </div>
              </div>

              {!driverAvailable && (
                <div className="mt-3 p-3 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-start gap-2">
                  <Info className="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
                  <div>
                    <span className="font-semibold">Driver Limitation: </span>
                    {driverMessage}
                    <div className="mt-1 text-slate-400">
                      Offline PCAP Replay mode is 100% operational without kernel drivers.
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </Card>

      {/* Operational Telemetry Bento Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="border border-slate-800 bg-[#090d16]">
          <div className="flex items-center justify-between text-slate-400 text-xs uppercase tracking-wider font-semibold">
            <span>Packets Observed</span>
            <Network className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-white font-mono">
            {status?.packets_observed.toLocaleString() ?? 0}
          </div>
          <div className="mt-1 text-xs text-slate-400 flex items-center justify-between">
            <span>Dropped: {status?.packets_dropped ?? 0}</span>
            <span>Uptime: {status?.uptime_seconds ?? 0}s</span>
          </div>
        </Card>

        <Card className="border border-slate-800 bg-[#090d16]">
          <div className="flex items-center justify-between text-slate-400 text-xs uppercase tracking-wider font-semibold">
            <span>Flow Reconstruction</span>
            <Layers className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-white font-mono">
            {status?.flows_completed.toLocaleString() ?? 0}
          </div>
          <div className="mt-1 text-xs text-slate-400 flex items-center justify-between">
            <span>Active: {status?.active_flows_count ?? 0}</span>
            <span>Created: {status?.flows_created ?? 0}</span>
          </div>
        </Card>

        <Card className="border border-slate-800 bg-[#090d16]">
          <div className="flex items-center justify-between text-slate-400 text-xs uppercase tracking-wider font-semibold">
            <span>Anomalies Detected</span>
            <ShieldAlert className="w-4 h-4 text-rose-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-rose-400 font-mono">
            {status?.anomalies_detected.toLocaleString() ?? 0}
          </div>
          <div className="mt-1 text-xs text-slate-400 flex items-center justify-between">
            <span>Scored: {status?.flows_scored ?? 0}</span>
            <span>Alerts: {status?.alerts_persisted ?? 0}</span>
          </div>
        </Card>

        <Card className="border border-slate-800 bg-[#090d16]">
          <div className="flex items-center justify-between text-slate-400 text-xs uppercase tracking-wider font-semibold">
            <span>Inference Latency</span>
            <Zap className="w-4 h-4 text-amber-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-white font-mono">
            {status?.mean_inference_latency_ms ?? 0} <span className="text-sm font-normal text-slate-400">ms</span>
          </div>
          <div className="mt-1 text-xs text-slate-400 flex items-center justify-between">
            <span>Queue Depth: {status?.queue_depth ?? 0}</span>
            <span className="text-emerald-400">SLA &lt; 35ms</span>
          </div>
        </Card>
      </div>

      {/* Model & Provenance Integrity Ribbon */}
      <div className="p-3.5 rounded-lg bg-slate-900/60 border border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-cyan-400" />
          <span className="text-slate-400">Model:</span>
          <span className="font-mono text-slate-200">
            {status?.model_integrity?.model_name ?? 'OptunaTuned_XGBoost'} (v{status?.model_integrity?.model_version ?? '1.0.0'})
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-slate-400">Contract:</span>
          <span className="font-mono px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[10px]">
            13 Frozen Features
          </span>
          <span className="text-slate-400 ml-2">Gate:</span>
          <span className="font-mono px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[10px]">
            Threshold 0.50
          </span>
        </div>
        <div className="flex items-center gap-2 font-mono text-[11px] text-slate-400">
          <span>Detector SHA:</span>
          <span className="text-slate-300">
            {status?.model_integrity?.model_sha256?.substring(0, 12)}...
          </span>
          <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[10px]">
            VERIFIED
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-slate-400">Target:</span>
          <span className="font-semibold text-slate-200">
            {status?.selected_target || 'None Selected'}
          </span>
        </div>
      </div>

      {/* Live Telemetry & Anomaly Correlation Hub */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Rolling Live Traffic & Anomaly Correlation Chart */}
        <Card
          className="lg:col-span-2 border border-slate-800 bg-[#090d16]"
          title="Live Traffic & Anomaly Correlation Stream (Rolling Timeline)"
          subtitle="Real-time post-BPF captured throughput (Mbps) correlated with model scoring rate and anomaly flags/sec"
        >
          {chartData.length === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-xs font-mono text-slate-500">
              <Activity className="w-8 h-8 text-slate-600 mb-2 animate-pulse" />
              <span>No telemetry intervals recorded yet.</span>
              <span className="text-[11px] text-slate-600 mt-0.5">Start capture to observe incoming throughput and anomaly correlation.</span>
            </div>
          ) : (
            <div className="h-64 w-full font-mono text-xs mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="time" stroke="#64748b" fontSize={10} tickLine={false} />
                  <YAxis
                    yAxisId="left"
                    orientation="left"
                    stroke="#06b6d4"
                    fontSize={10}
                    tickLine={false}
                    unit=" Mbps"
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    stroke="#a855f7"
                    fontSize={10}
                    tickLine={false}
                    unit="/s"
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#090d16',
                      borderColor: '#1e293b',
                      borderRadius: '8px',
                      color: '#f8fafc',
                      fontSize: '11px',
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '8px' }} />
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="mbps"
                    name="Captured Throughput (Mbps)"
                    stroke="#06b6d4"
                    strokeWidth={2}
                    dot={{ r: 2 }}
                    activeDot={{ r: 4 }}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="flowsPerSec"
                    name="Scored Flows / sec"
                    stroke="#a855f7"
                    strokeWidth={2}
                    dot={{ r: 2 }}
                    activeDot={{ r: 4 }}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="anomPerSec"
                    name="Anomaly Flags / sec"
                    stroke="#f43f5e"
                    strokeWidth={2}
                    dot={{ r: 2 }}
                    activeDot={{ r: 4 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        {/* Capture Session Summary Card */}
        <Card
          className="border border-slate-800 bg-[#090d16]"
          title="Capture Session Summary"
          subtitle="Cumulative session totals and SLA latency percentiles"
          badge={
            <Badge variant={status?.session_summary?.is_historical ? 'indigo' : isActive ? 'emerald' : 'slate'}>
              {status?.session_summary?.is_historical ? 'HISTORICAL' : isActive ? 'ACTIVE' : 'IDLE'}
            </Badge>
          }
        >
          <div className="space-y-2.5 text-xs font-mono mt-1">
            <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
              <span className="text-slate-400">Session Span:</span>
              <span className="text-slate-200">
                {status?.session_summary?.start_time
                  ? `${status.session_summary.start_time.substring(11, 19)} UTC`
                  : 'N/A'}{' '}
                &rarr;{' '}
                {status?.session_summary?.end_time
                  ? `${status.session_summary.end_time.substring(11, 19)} UTC`
                  : isActive
                  ? 'Live'
                  : 'N/A'}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
              <span className="text-slate-400">Total Packets / Bytes:</span>
              <span className="text-white font-semibold">
                {(status?.session_summary?.total_packets ?? status?.packets_observed ?? 0).toLocaleString()} pkts /{' '}
                {formatBytes(status?.session_summary?.total_bytes ?? status?.bytes_observed ?? 0)}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
              <span className="text-slate-400">Flows Scored:</span>
              <span className="text-cyan-300 font-semibold">
                {(status?.session_summary?.total_flows_scored ?? status?.flows_scored ?? 0).toLocaleString()}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
              <span className="text-slate-400">Total Anomalies:</span>
              <span className="text-rose-400 font-bold">
                {(status?.session_summary?.total_anomalies ?? status?.anomalies_detected ?? 0).toLocaleString()}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 border-b border-slate-800/60">
              <span className="text-slate-400">Alerts Persisted / Dedup:</span>
              <span className="text-slate-200">
                <span className="text-cyan-300 font-semibold">
                  {status?.session_summary?.total_alerts_persisted ?? status?.alerts_persisted ?? 0}
                </span>{' '}
                /{' '}
                <span className="text-slate-400">
                  {status?.session_summary?.total_alerts_deduplicated ?? status?.alerts_deduplicated ?? 0}
                </span>
              </span>
            </div>
            <div className="py-1 border-b border-slate-800/60">
              <div className="flex items-center justify-between mb-1">
                <span className="text-slate-400">Latency Percentiles:</span>
                <span className="text-amber-300 font-semibold">
                  Mean {(status?.session_summary?.mean_inference_latency_ms ?? status?.mean_inference_latency_ms ?? 0).toFixed(1)} ms
                </span>
              </div>
              <div className="grid grid-cols-3 gap-1 text-[11px] text-center">
                <div className="p-1 rounded bg-slate-900 border border-slate-800">
                  <div className="text-slate-500">p50</div>
                  <div className="text-slate-300 font-bold">{status?.session_summary?.latency_p50_ms ?? status?.latency_p50_ms ?? 0}ms</div>
                </div>
                <div className="p-1 rounded bg-slate-900 border border-slate-800">
                  <div className="text-slate-500">p95</div>
                  <div className="text-slate-300 font-bold">{status?.session_summary?.latency_p95_ms ?? status?.latency_p95_ms ?? 0}ms</div>
                </div>
                <div className="p-1 rounded bg-slate-900 border border-slate-800">
                  <div className="text-slate-500">p99</div>
                  <div className="text-amber-400 font-bold">{status?.session_summary?.latency_p99_ms ?? status?.latency_p99_ms ?? 0}ms</div>
                </div>
              </div>
            </div>
            <div className="flex items-center justify-between pt-1 text-[11px]">
              <span className="text-slate-400">Drops / Errors:</span>
              <span className="text-slate-300">
                Drops: <span className="font-semibold">{status?.session_summary?.total_drops ?? status?.packets_dropped ?? 0}</span> |{' '}
                Errors: <span className="font-semibold text-rose-400">{status?.session_summary?.total_errors ?? 0}</span>
              </span>
            </div>
          </div>
        </Card>
      </div>

      {/* 5-Second Interval Telemetry Ledger */}
      <Card
        className="border border-slate-800 bg-[#090d16]"
        title="Aligned 5-Second Interval Telemetry Ledger"
        subtitle="Counter differences per aligned 5-second UTC interval — strictly decoupling interval deltas from cumulative totals"
      >
        {status?.intervals && status.intervals.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider font-mono text-[11px]">
                  <th className="py-2.5 px-3">Timestamp (UTC)</th>
                  <th className="py-2.5 px-3">Captured Packets</th>
                  <th className="py-2.5 px-3">Captured Mbps</th>
                  <th className="py-2.5 px-3">New Flows</th>
                  <th className="py-2.5 px-3">Scored Flows</th>
                  <th className="py-2.5 px-3">New Anomalies</th>
                  <th className="py-2.5 px-3">New Alerts</th>
                  <th className="py-2.5 px-3">Drops</th>
                  <th className="py-2.5 px-3">Errors</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono text-xs">
                {status.intervals
                  .slice()
                  .reverse()
                  .slice(0, 15)
                  .map((interval: IntervalTelemetryItem, idx: number) => {
                    const timePart = interval.timestamp.includes('T')
                      ? interval.timestamp.split('T')[1].substring(0, 8)
                      : interval.timestamp.substring(11, 19);
                    return (
                      <tr
                        key={`${interval.timestamp}-${idx}`}
                        className={`hover:bg-slate-800/30 transition-colors ${
                          interval.anomalies_detected > 0 ? 'bg-rose-950/10' : ''
                        }`}
                      >
                        <td className="py-2 px-3 text-cyan-300 font-semibold whitespace-nowrap">
                          {timePart} UTC
                        </td>
                        <td className="py-2 px-3 text-slate-200">
                          {interval.packets_captured.toLocaleString()}
                        </td>
                        <td className="py-2 px-3 font-semibold text-white">
                          {interval.throughput_mbps.toFixed(4)} <span className="text-[10px] text-slate-500 font-normal">Mbps</span>
                        </td>
                        <td className="py-2 px-3 text-slate-300">
                          {interval.flows_created}
                        </td>
                        <td className="py-2 px-3 text-indigo-300 font-semibold">
                          {interval.flows_scored}
                        </td>
                        <td className="py-2 px-3">
                          {interval.anomalies_detected > 0 ? (
                            <span className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold border border-rose-500/30">
                              +{interval.anomalies_detected}
                            </span>
                          ) : (
                            <span className="text-slate-500">0</span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-slate-300">
                          <span className="text-cyan-300 font-semibold">+{interval.alerts_persisted}</span>
                          {interval.alerts_deduplicated > 0 && (
                            <span className="text-slate-500 text-[10px] ml-1">({interval.alerts_deduplicated} dedup)</span>
                          )}
                        </td>
                        <td className="py-2 px-3">
                          {interval.drops > 0 ? (
                            <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-semibold">
                              {interval.drops}
                            </span>
                          ) : (
                            <span className="text-slate-500">0</span>
                          )}
                        </td>
                        <td className="py-2 px-3">
                          {interval.errors > 0 ? (
                            <span className="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 font-semibold">
                              {interval.errors}
                            </span>
                          ) : (
                            <span className="text-slate-500">0</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-8 text-center text-slate-500 text-xs font-mono">
            No interval slices recorded yet. Interval metrics will stream every 5 seconds once capture is initiated.
          </div>
        )}
      </Card>

      {/* Network Protocol & Hardware Throughput Demarcation */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Post-BPF vs Task Manager Discrepancy Card */}
        <Card className="border border-slate-800 bg-[#090d16]">
          <div className="flex items-center gap-2 pb-2 border-b border-slate-800/80 text-xs font-semibold text-cyan-300 uppercase tracking-wider">
            <Info className="w-4 h-4 text-cyan-400 shrink-0" />
            <span>Post-BPF Throughput vs. Windows Task Manager</span>
          </div>
          <div className="mt-3 text-xs text-slate-300 space-y-2 leading-relaxed">
            <p>
              <strong>Measurement Demarcation:</strong> Windows Task Manager Wi-Fi throughput reflects the total raw physical network adapter payload across all hardware queues.
            </p>
            <p className="text-slate-400 text-[11px]">
              In contrast, TrafficShield measures only packets that pass the kernel capture filter (<code className="text-cyan-300">ip</code>) and reach user space. Task Manager counters incorporate non-IPv4 traffic (ARP, link-local IPv6, LLDP), host OS tunnels, multicast discovery, and retransmitted frames that do not form valid IPv4 flows.
            </p>
            <div className="p-2 rounded bg-slate-900/80 border border-slate-800 text-[11px] text-cyan-300/90 font-mono">
              Captured Throughput (Mbps) = (Interval IPv4 Bytes &times; 8) / (5.0s &times; 1,000,000)
            </div>
          </div>
        </Card>

        {/* Link-Local Multicast Out-of-Distribution Diagnostics */}
        <Card className="border border-slate-800 bg-[#090d16]">
          <div className="flex items-center gap-2 pb-2 border-b border-slate-800/80 text-xs font-semibold text-amber-300 uppercase tracking-wider">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
            <span>Multicast Out-of-Distribution Diagnosis (mDNS / SSDP)</span>
          </div>
          <div className="mt-3 text-xs text-slate-300 space-y-2 leading-relaxed">
            <p>
              <strong>Why Background LAN Broadcasts Trigger Anomalies:</strong> Protocols like mDNS (<code className="text-amber-300">224.0.0.251:5353</code>) and SSDP (<code className="text-amber-300">239.255.255.250:1900</code>) exhibit statistical properties outside the UNSW-NB15 benchmark training distribution.
            </p>
            <ul className="text-slate-400 text-[11px] list-disc list-inside space-y-1">
              <li><strong>RFC 6762 Multicast TTL:</strong> Mandates <code className="text-slate-300">sttl=255</code> to restrict packets to the local link. In the benchmark training set, <code className="text-slate-300">sttl &ge; 254</code> indicates synthetic attack tools.</li>
              <li><strong>Zero Window &amp; Burst Load:</strong> UDP transport lacks flow control (<code className="text-slate-300">swin=0</code>), and microsecond durations cause elevated instantaneous <code className="text-slate-300">sload</code>.</li>
            </ul>
          </div>
        </Card>
      </div>

      {/* 4-Tier Security Triage Framework Banner */}
      <div className="p-4 rounded-lg bg-slate-900/80 border border-slate-800 text-xs">
        <h4 className="font-semibold text-slate-200 uppercase tracking-wider text-[11px] mb-2 flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-rose-400" />
          Strict 4-Tier Anomaly Triage Framework
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-[11px]">
          <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
            <div className="font-bold text-rose-300 mb-1">1. Model Anomaly</div>
            <p className="text-slate-400">Statistical pattern deviation exceeding threshold (&tau;=0.50). Identifies out-of-distribution traffic profile.</p>
          </div>
          <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
            <div className="font-bold text-amber-300 mb-1">2. Benign False Positive</div>
            <p className="text-slate-400">Harmless protocol (e.g. mDNS/SSDP) exhibiting high TTL or burst rate not seen in unicast training data.</p>
          </div>
          <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
            <div className="font-bold text-emerald-300 mb-1">3. Confirmed Attack</div>
            <p className="text-slate-400">Analyst-verified malicious intrusion or denial-of-service, supported by ground truth and forensic corroboration.</p>
          </div>
          <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
            <div className="font-bold text-slate-300 mb-1">4. Uninvestigated Event</div>
            <p className="text-slate-400">Candidate scored flow queued for security operations triage and disposition verification.</p>
          </div>
        </div>
      </div>

      {/* Tiered Drop Demarcation & Lifecycle Breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Tiered Drops Card */}
        <Card className="border border-slate-800 bg-[#090d16]">
          <div className="flex items-center justify-between text-slate-400 text-xs uppercase tracking-wider font-semibold pb-2 border-b border-slate-800/80">
            <span>Tiered Drop Demarcation</span>
            <Activity className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="mt-3 space-y-2.5 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Tier 1 Kernel Drops:</span>
              <span className="font-mono font-semibold">
                {status?.native_kernel_drops_available ? (
                  <span className="text-white">{status.native_kernel_drops ?? 0}</span>
                ) : (
                  <Badge variant="slate">
                    {status?.kernel_drop_status?.includes('UNSUPPORTED') ? 'Unsupported' : 'Unavailable'}
                  </Badge>
                )}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Tier 2 Ingestion Drops:</span>
              <span className="font-mono font-semibold text-white">
                {status?.packets_dropped ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Tier 3 Flow Queue Drops:</span>
              <span className="font-mono font-semibold text-white">
                {status?.flows_queue_dropped ?? 0}
              </span>
            </div>
            <div className="pt-2 border-t border-slate-800/60 text-[11px] text-slate-500">
              <span>Driver Status: {status?.kernel_drop_status || 'Unavailable'}</span>
            </div>
          </div>
        </Card>

        {/* Terminal Flow Outcomes Card */}
        <Card className="border border-slate-800 bg-[#090d16]">
          <div className="flex items-center justify-between text-slate-400 text-xs uppercase tracking-wider font-semibold pb-2 border-b border-slate-800/80">
            <span>Terminal Flow Outcomes</span>
            <Layers className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="mt-3 space-y-2.5 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Flows Scored:</span>
              <span className="font-mono font-semibold text-emerald-400">
                {status?.flows_scored ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Incompatible Rejected:</span>
              <span className="font-mono font-semibold text-slate-300">
                {status?.incompatible_flows_rejected ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Validation / Infer Failures:</span>
              <span className="font-mono font-semibold text-rose-400">
                {(status?.validation_errors ?? 0) + (status?.inference_failures ?? 0)}
              </span>
            </div>
            <div className="pt-2 border-t border-slate-800/60 text-[11px] text-slate-500 flex justify-between">
              <span>Unprocessed Flows:</span>
              <span className="font-mono text-slate-400">{status?.unprocessed_flows ?? 0}</span>
            </div>
          </div>
        </Card>

        {/* Alert Persistence Lifecycle Card */}
        <Card className="border border-slate-800 bg-[#090d16]">
          <div className="flex items-center justify-between text-slate-400 text-xs uppercase tracking-wider font-semibold pb-2 border-b border-slate-800/80">
            <span>Alert Persistence Lifecycle</span>
            <ShieldAlert className="w-4 h-4 text-rose-400" />
          </div>
          <div className="mt-3 space-y-2.5 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Anomalies Detected:</span>
              <span className="font-mono font-semibold text-rose-400">
                {status?.anomalies_detected ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Alerts Persisted:</span>
              <span className="font-mono font-semibold text-cyan-300">
                {status?.alerts_persisted ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Alerts Deduplicated:</span>
              <span className="font-mono font-semibold text-slate-300">
                {status?.alerts_deduplicated ?? 0}
              </span>
            </div>
            <div className="pt-2 border-t border-slate-800/60 text-[11px] text-slate-500 flex justify-between">
              <span>Persistence Failures:</span>
              <span className="font-mono text-slate-400">{status?.persistence_failures ?? 0}</span>
            </div>
          </div>
        </Card>
      </div>

      {/* Live Streaming Scored Events Table */}
      <Card className="border border-slate-800 bg-[#090d16]">
        <div className="flex items-center justify-between pb-3 border-b border-slate-800/80">
          <div>
            <h2 className="text-base font-bold text-white">Streaming Detections Feed</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Sub-second scored unidirectional flows evaluated against decision threshold (0.50). Detections represent statistical pattern anomalies requiring investigation, not verified attacks.
            </p>
          </div>
          <span className="text-xs font-mono text-slate-400">
            Showing {status?.recent_events?.length ?? 0} recent flows
          </span>
        </div>

        {status?.recent_events && status.recent_events.length > 0 ? (
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider">
                  <th className="py-2.5 px-3">Timestamp</th>
                  <th className="py-2.5 px-3">Flow 5-Tuple</th>
                  <th className="py-2.5 px-3">Score</th>
                  <th className="py-2.5 px-3">Verdict</th>
                  <th className="py-2.5 px-3">Risk Level</th>
                  <th className="py-2.5 px-3">Latency</th>
                  <th className="py-2.5 px-3">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {status.recent_events
                  .slice()
                  .reverse()
                  .map((ev: StreamingEventRecord) => (
                    <tr
                      key={ev.event_id}
                      className={`hover:bg-slate-800/30 transition-colors ${
                        ev.is_anomaly ? 'bg-rose-950/15' : ''
                      }`}
                    >
                      <td className="py-2 px-3 text-slate-300 whitespace-nowrap">
                        {ev.timestamp.substring(11, 19)}
                      </td>
                      <td className="py-2 px-3 text-slate-200">
                        <span className="text-cyan-300">{ev.src_ip}:{ev.src_port}</span>
                        <span className="text-slate-500 mx-1">&rarr;</span>
                        <span className="text-indigo-300">{ev.dst_ip}:{ev.dst_port}</span>
                        <span className="ml-1.5 px-1 py-0.5 rounded bg-slate-800 text-slate-400 text-[10px]">
                          {ev.protocol}
                        </span>
                      </td>
                      <td className="py-2 px-3 font-semibold text-white">
                        {ev.anomaly_score.toFixed(4)}
                      </td>
                      <td className="py-2 px-3">
                        {ev.is_anomaly ? (
                          <span className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold border border-rose-500/30">
                            ANOMALY
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                            BENIGN
                          </span>
                        )}
                      </td>
                      <td className="py-2 px-3">
                        <SeverityBadge severity={ev.risk_level} />
                      </td>
                      <td className="py-2 px-3 text-slate-400 whitespace-nowrap">
                        {ev.inference_latency_ms} ms
                      </td>
                      <td className="py-2 px-3 text-[11px] text-slate-400">
                        <span className="px-1.5 py-0.5 rounded bg-slate-800/80 border border-slate-700">
                          {ev.source_provenance}
                        </span>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-12 text-center text-slate-500 text-sm">
            <Radio className="w-8 h-8 text-slate-600 mx-auto mb-2 animate-pulse" />
            <p className="font-medium text-slate-400">No Streaming Events Active</p>
            <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
              Select a PCAP capture file or authorized interface above and click Start to begin live flow scoring.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
};
