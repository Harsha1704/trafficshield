import React from 'react';

export const LoadingSpinner: React.FC<{
  message?: string;
  size?: 'sm' | 'md' | 'lg';
}> = ({ message, size = 'md' }) => {
  const sizeClasses = {
    sm: 'w-4 h-4 border-2',
    md: 'w-8 h-8 border-2',
    lg: 'w-12 h-12 border-3',
  }[size];

  return (
    <div className={`flex flex-col items-center justify-center ${message ? 'p-8 gap-3' : 'p-1'}`}>
      <div className={`${sizeClasses} rounded-full border-cyan-500/20 border-t-cyan-400 animate-spin`} />
      {message && <span className="text-xs text-slate-400 font-mono tracking-wide">{message}</span>}
    </div>
  );
};
