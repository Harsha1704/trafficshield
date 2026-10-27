import React, { useState } from 'react';
import { Shield, Lock, User, AlertCircle, ArrowRight, ShieldCheck, CheckCircle2 } from 'lucide-react';
import { api, ApiClientError, type AuthUserInfo } from '../services/api';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

interface LoginPageProps {
  onLoginSuccess: (user: AuthUserInfo) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const isDev = import.meta.env.DEV;
  const [username, setUsername] = useState<string>(isDev ? 'analyst' : '');
  const [password, setPassword] = useState<string>(isDev ? 'AnalystPass123!' : '');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password.trim()) {
      setError('Please enter both username and password.');
      return;
    }

    setLoading(true);
    try {
      const res = await api.login({
        username: username.trim(),
        password: password.trim(),
      });
      onLoginSuccess(res.user);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message || 'Authentication failed. Please check credentials.');
      } else {
        setError(err instanceof Error ? err.message : 'Authentication service unreachable.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleFillAnalyst = () => {
    setUsername('analyst');
    setPassword('AnalystPass123!');
    setError(null);
  };

  const handleFillAdmin = () => {
    setUsername('admin');
    setPassword('AdminPass123!');
    setError(null);
  };

  return (
    <div className="min-h-screen bg-[#07090e] text-slate-100 flex flex-col justify-center items-center px-4 bg-tactical-grid relative">
      {/* Subtle background glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

      <div className="w-full max-w-md relative z-10">
        {/* Branding Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-cyan-950/60 border border-cyan-800/60 text-cyan-400 mb-4 shadow-lg shadow-cyan-950/50">
            <Shield className="w-8 h-8" />
          </div>
          <h1 className="text-2xl font-black tracking-wider text-slate-100 font-mono">
            TRAFFIC<span className="text-cyan-400">SHIELD</span>
          </h1>
          <p className="text-xs uppercase tracking-widest text-slate-400 font-mono mt-1">
            Unidirectional IP Traffic Anomaly Detection & SOC Console
          </p>
        </div>

        {/* Login Card */}
        <div className="bg-[#0b0f19]/90 border border-slate-800 rounded-2xl p-6 sm:p-8 backdrop-blur-md shadow-2xl shadow-black/80">
          <div className="flex items-center justify-between border-b border-slate-800/80 pb-4 mb-6">
            <div>
              <h2 className="text-base font-bold text-slate-200">SOC Operator Authentication</h2>
              <p className="text-xs text-slate-400 font-mono mt-0.5">Role-based access to detection & telemetry</p>
            </div>
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-950/60 border border-emerald-800/60 text-emerald-400 text-xs font-mono">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>RBAC ACTIVE</span>
            </div>
          </div>

          {error && (
            <div className="mb-5 p-3 rounded-xl bg-rose-950/50 border border-rose-800/70 text-rose-300 text-xs font-mono flex items-start gap-2.5">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-mono text-slate-400 uppercase tracking-wider mb-1.5">
                Username / Identifier
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                  <User className="w-4 h-4" />
                </div>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="analyst or admin"
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-slate-900/80 border border-slate-700/80 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 focus:outline-none transition-colors font-mono"
                  disabled={loading}
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 uppercase tracking-wider mb-1.5">
                Authentication Secret
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-slate-900/80 border border-slate-700/80 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 focus:outline-none transition-colors font-mono"
                  disabled={loading}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full mt-2 py-3 px-4 rounded-xl bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white font-semibold text-sm shadow-lg shadow-cyan-900/30 flex items-center justify-center gap-2 transition-all disabled:opacity-50 cursor-pointer"
            >
              {loading ? (
                <>
                  <LoadingSpinner size="sm" />
                  <span>Verifying Credentials...</span>
                </>
              ) : (
                <>
                  <span>Authenticate Operator</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {/* Quick-fill credentials for evaluators (development mode only) */}
          {isDev && (
            <div className="mt-6 pt-5 border-t border-slate-800/80">
              <span className="block text-[11px] font-mono uppercase tracking-wider text-slate-400 mb-2.5">
                Demonstration & Evaluation Accounts (Dev Mode):
              </span>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={handleFillAnalyst}
                  className="p-2.5 rounded-lg bg-slate-900/90 border border-slate-800 hover:border-cyan-500/60 text-left transition-colors cursor-pointer group"
                >
                  <div className="flex items-center justify-between text-xs font-semibold text-slate-200 group-hover:text-cyan-400">
                    <span>Analyst</span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-950/80 border border-emerald-800/60 text-emerald-400">
                      ANALYST
                    </span>
                  </div>
                  <div className="text-[11px] font-mono text-slate-400 mt-1">analyst</div>
                </button>

                <button
                  type="button"
                  onClick={handleFillAdmin}
                  className="p-2.5 rounded-lg bg-slate-900/90 border border-slate-800 hover:border-indigo-500/60 text-left transition-colors cursor-pointer group"
                >
                  <div className="flex items-center justify-between text-xs font-semibold text-slate-200 group-hover:text-indigo-400">
                    <span>Administrator</span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-indigo-950/80 border border-indigo-800/60 text-indigo-400">
                      ADMIN
                    </span>
                  </div>
                  <div className="text-[11px] font-mono text-slate-400 mt-1">admin</div>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer info */}
        <div className="text-center mt-6 text-xs font-mono text-slate-400 flex items-center justify-center gap-2">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
          <span>FROZEN MODEL READY (XGBoost 13-Features, τ=0.50)</span>
        </div>
      </div>
    </div>
  );
};
