import React from 'react';

interface CardProps {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  badge?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}

export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  badge,
  action,
  children,
  className = '',
  bodyClassName = 'p-5',
}) => {
  return (
    <div className={`glass-panel rounded-xl shadow-lg shadow-black/40 border border-slate-800/80 transition-colors ${className}`}>
      {(title || subtitle || action || badge) && (
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800/70">
          <div>
            <div className="flex items-center gap-2.5">
              {typeof title === 'string' ? (
                <h3 className="text-sm font-semibold tracking-wide text-slate-100 uppercase">{title}</h3>
              ) : (
                title
              )}
              {badge}
            </div>
            {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
          </div>
          {action && <div className="flex items-center gap-2">{action}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  );
};
