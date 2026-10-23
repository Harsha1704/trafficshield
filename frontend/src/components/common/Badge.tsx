import React from 'react';
import type { RiskLevel, AlertStatus } from '../../types/api';

interface BadgeProps {
  children: React.ReactNode;
  className?: string;
  variant?: 'cyan' | 'indigo' | 'slate' | 'danger' | 'warning' | 'emerald' | 'default';
}

export const Badge: React.FC<BadgeProps> = ({ children, className = '', variant = 'default' }) => {
  let variantClass = 'bg-slate-800 text-slate-300 border-slate-700';
  if (variant === 'cyan') variantClass = 'bg-cyan-950/60 text-cyan-300 border-cyan-800/60';
  if (variant === 'indigo') variantClass = 'bg-indigo-950/60 text-indigo-300 border-indigo-800/60';
  if (variant === 'slate') variantClass = 'bg-slate-900/80 text-slate-400 border-slate-800';
  if (variant === 'danger') variantClass = 'bg-rose-950/70 text-rose-300 border-rose-800/70';
  if (variant === 'warning') variantClass = 'bg-amber-950/70 text-amber-300 border-amber-800/70';
  if (variant === 'emerald') variantClass = 'bg-emerald-950/70 text-emerald-300 border-emerald-800/70';

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border font-mono tracking-tight ${variantClass} ${className}`}>
      {children}
    </span>
  );
};

export const SeverityBadge: React.FC<{ severity: RiskLevel | string }> = ({ severity }) => {
  const sev = severity.toUpperCase();
  let badgeClass = 'badge-low';
  let dotColor = 'bg-emerald-400';

  if (sev === 'CRITICAL') {
    badgeClass = 'badge-critical';
    dotColor = 'bg-rose-500 animate-pulse';
  } else if (sev === 'HIGH') {
    badgeClass = 'badge-high';
    dotColor = 'bg-orange-400';
  } else if (sev === 'MEDIUM') {
    badgeClass = 'badge-medium';
    dotColor = 'bg-amber-400';
  }

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded text-xs font-semibold font-mono tracking-wider ${badgeClass}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      {sev}
    </span>
  );
};

export const StatusBadge: React.FC<{ status: AlertStatus | string }> = ({ status }) => {
  const st = status.toUpperCase();
  let statusClass = 'status-new';

  if (st === 'INVESTIGATING') statusClass = 'status-investigating';
  else if (st === 'RESOLVED') statusClass = 'status-resolved';
  else if (st === 'FALSE_POSITIVE') statusClass = 'status-false_positive';

  const label = st === 'FALSE_POSITIVE' ? 'FALSE POSITIVE' : st;

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium font-mono ${statusClass}`}>
      {label}
    </span>
  );
};
