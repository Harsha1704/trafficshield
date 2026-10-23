import React from 'react';
import { ShieldAlert } from 'lucide-react';

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon = <ShieldAlert className="w-10 h-10 text-slate-500" />,
  title,
  description,
  action,
}) => {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center rounded-xl border border-dashed border-slate-800 bg-slate-900/20">
      <div className="p-3 mb-4 rounded-xl bg-slate-900 border border-slate-800 text-slate-400">
        {icon}
      </div>
      <h4 className="text-sm font-semibold text-slate-200 tracking-wide uppercase">{title}</h4>
      <p className="mt-1 text-xs text-slate-400 max-w-sm">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
};

export const LoadingSpinner: React.FC<{ message?: string }> = ({ message = 'Processing...' }) => {
  return (
    <div className="flex flex-col items-center justify-center p-8 gap-3">
      <div className="w-8 h-8 rounded-full border-2 border-cyan-500/20 border-t-cyan-400 animate-spin" />
      <span className="text-xs text-slate-400 font-mono tracking-wide">{message}</span>
    </div>
  );
};
