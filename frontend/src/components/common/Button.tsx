import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'outline';
  size?: 'sm' | 'md' | 'lg';
  icon?: React.ReactNode;
  loading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  icon,
  loading = false,
  className = '',
  disabled,
  ...props
}) => {
  const base = 'inline-flex items-center justify-center font-medium transition-all rounded-lg focus:outline-none focus:ring-2 focus:ring-cyan-500/50 disabled:opacity-50 disabled:cursor-not-allowed select-none';

  let sizeClass = 'px-3.5 py-1.5 text-sm gap-2';
  if (size === 'sm') sizeClass = 'px-2.5 py-1 text-xs gap-1.5';
  if (size === 'lg') sizeClass = 'px-5 py-2.5 text-base gap-2.5';

  let variantClass = '';
  switch (variant) {
    case 'primary':
      variantClass = 'bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold shadow-md shadow-cyan-500/20 active:translate-y-px';
      break;
    case 'secondary':
      variantClass = 'bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700/80 active:translate-y-px';
      break;
    case 'danger':
      variantClass = 'bg-rose-600/90 hover:bg-rose-600 text-white font-medium border border-rose-500/40 active:translate-y-px';
      break;
    case 'outline':
      variantClass = 'border border-cyan-500/30 hover:border-cyan-400/70 text-cyan-400 hover:bg-cyan-950/30 active:translate-y-px';
      break;
    case 'ghost':
      variantClass = 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60';
      break;
  }

  return (
    <button
      className={`${base} ${sizeClass} ${variantClass} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
};
