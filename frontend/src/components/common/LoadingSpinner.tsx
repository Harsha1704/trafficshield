import React from 'react';

export const LoadingSpinner: React.FC<{ message?: string }> = ({ message = 'Processing...' }) => {
  return (
    <div className="flex flex-col items-center justify-center p-8 gap-3">
      <div className="w-8 h-8 rounded-full border-2 border-cyan-500/20 border-t-cyan-400 animate-spin" />
      <span className="text-xs text-slate-400 font-mono tracking-wide">{message}</span>
    </div>
  );
};
