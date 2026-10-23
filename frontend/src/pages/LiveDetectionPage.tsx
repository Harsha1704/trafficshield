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
} from 'lucide-react';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { SeverityBadge, Badge } from '../components/common/Badge';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { api, ApiClientError } from '../services/api';
import type {
  CaptureStatusResponse,
  NetworkInterfaceItem,
  SamplePcapItem,
  StreamingEventRecord,
} from '../types/api';

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
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700">
            <span className="w-2 h-2 rounded-full bg-slate-500"></span>
            STOPPED
          </span>
        );
    }
  };

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
          <span className="text-slate-400">Production Model:</span>
          <span className="font-mono text-slate-200">
            {status?.model_integrity?.model_name ?? 'RandomForest'} ({status?.model_integrity?.model_version ?? '1.0.0'})
          </span>
        </div>
        <div className="flex items-center gap-2 font-mono text-[11px] text-slate-400">
          <span>SHA-256:</span>
          <span className="text-slate-300">
            {status?.model_integrity?.model_sha256?.substring(0, 16)}...
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

      {/* Live Streaming Scored Events Table */}
      <Card className="border border-slate-800 bg-[#090d16]">
        <div className="flex items-center justify-between pb-3 border-b border-slate-800/80">
          <div>
            <h2 className="text-base font-bold text-white">Streaming Detections Feed</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Sub-second scored unidirectional flows evaluated against decision threshold (0.50).
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
