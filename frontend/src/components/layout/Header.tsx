import React, { useEffect, useState } from 'react';
import { RefreshCw, Activity, Cpu, Wifi, WifiOff, Shield, LogOut, UserCheck } from 'lucide-react';
import type { ModelInfoResponse } from '../../types/api';
import type { AuthUserInfo } from '../../services/api';

interface HeaderProps {
  modelInfo: ModelInfoResponse | null;
  apiOnline: boolean;
  onRefresh: () => void;
  refreshing: boolean;
  collapsed: boolean;
  user?: AuthUserInfo | null;
  onLogout?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  modelInfo,
  apiOnline,
  onRefresh,
  refreshing,
  collapsed,
  user,
  onLogout,
}) => {
  const [timeUtc, setTimeUtc] = useState<string>('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeUtc(now.toUTCString().replace('GMT', 'UTC'));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header
      className={`fixed top-0 right-0 z-20 h-16 bg-[#070a11]/90 backdrop-blur-md border-b border-slate-800/80 transition-all duration-200 flex items-center justify-between px-6 ${
        collapsed ? 'left-18' : 'left-64'
      }`}
    >
      {/* Left: Operational Status */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          {apiOnline ? (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-mono font-medium bg-emerald-950/60 text-emerald-400 border border-emerald-800/60">
              <Wifi className="w-3.5 h-3.5" />
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              API ONLINE
            </span>
          ) : (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-mono font-medium bg-rose-950/60 text-rose-400 border border-rose-800/60">
              <WifiOff className="w-3.5 h-3.5" />
              DISCONNECTED
            </span>
          )}
        </div>

        {modelInfo && (
          <div className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded-md bg-slate-900 border border-slate-800 text-xs font-mono text-slate-300">
            <Cpu className="w-3.5 h-3.5 text-cyan-400" />
            <span>{modelInfo.model_name}</span>
            <span className="text-slate-500">|</span>
            <span className="text-cyan-300">v{modelInfo.model_version}</span>
            <span className="text-slate-500">|</span>
            <span className="text-amber-400">τ={modelInfo.decision_threshold}</span>
          </div>
        )}
      </div>

      {/* Right: User Status, Clock & Actions */}
      <div className="flex items-center gap-3 sm:gap-4">
        {/* User Session / Role Status */}
        {user ? (
          <div className="flex items-center gap-2 text-xs font-mono px-2.5 py-1 rounded-md bg-slate-900 border border-slate-800 text-slate-300">
            <UserCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span className="hidden md:inline text-slate-400">{user.username}</span>
            <span className="text-slate-600 hidden md:inline">|</span>
            <span className="text-slate-400">ROLE:</span>
            <span className={`font-semibold ${user.role === 'admin' ? 'text-indigo-400' : 'text-emerald-400'}`}>
              {user.role.toUpperCase()}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs font-mono px-2.5 py-1 rounded-md bg-rose-950/60 border border-rose-800 text-rose-400">
            <Shield className="w-3.5 h-3.5" />
            <span>UNAUTHENTICATED</span>
          </div>
        )}

        <div className="hidden md:flex items-center gap-2 text-xs font-mono text-slate-400 bg-slate-900/80 px-3 py-1 rounded-md border border-slate-800">
          <Activity className="w-3.5 h-3.5 text-cyan-500 animate-pulse" />
          <span>{timeUtc || 'INITIALIZING CLOCK...'}</span>
        </div>

        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="p-1.5 rounded-lg text-slate-400 hover:text-cyan-400 hover:bg-slate-800/70 border border-slate-800 transition-colors disabled:opacity-50 cursor-pointer"
          title="Refresh SOC Status & Metrics"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-cyan-400' : ''}`} />
        </button>

        {onLogout && user && (
          <button
            onClick={onLogout}
            className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-950/40 border border-slate-800 hover:border-rose-800 transition-colors cursor-pointer"
            title="Terminate Active SOC Session (Logout)"
          >
            <LogOut className="w-4 h-4" />
          </button>
        )}
      </div>
    </header>
  );
};
