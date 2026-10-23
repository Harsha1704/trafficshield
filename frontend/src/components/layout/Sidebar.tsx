import React from 'react';
import {
  LayoutDashboard,
  Activity,
  ShieldAlert,
  Search,
  Cpu,
  FileSpreadsheet,
  Settings,
  Shield,
  ChevronLeft,
  ChevronRight,
  Gauge,
  Radio,
} from 'lucide-react';

export type NavTab =
  | 'overview'
  | 'traffic'
  | 'live'
  | 'alerts'
  | 'monitoring'
  | 'inspector'
  | 'model'
  | 'reports'
  | 'settings';

interface SidebarProps {
  activeTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  unreadAlertCount?: number;
  activeDriftAlertCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onSelectTab,
  collapsed,
  onToggleCollapse,
  unreadAlertCount = 0,
  activeDriftAlertCount = 0,
}) => {
  const navItems = [
    { id: 'overview' as NavTab, label: 'Overview', icon: LayoutDashboard },
    { id: 'traffic' as NavTab, label: 'Traffic Analysis', icon: Activity },
    { id: 'live' as NavTab, label: 'Live Detection', icon: Radio },
    { id: 'alerts' as NavTab, label: 'Alerts & Triage', icon: ShieldAlert, badge: unreadAlertCount },
    { id: 'monitoring' as NavTab, label: 'Monitoring & Drift', icon: Gauge, badge: activeDriftAlertCount },
    { id: 'inspector' as NavTab, label: 'Flow Inspector', icon: Search },
    { id: 'model' as NavTab, label: 'Model Intelligence', icon: Cpu },
    { id: 'reports' as NavTab, label: 'Reports', icon: FileSpreadsheet },
    { id: 'settings' as NavTab, label: 'Settings', icon: Settings },
  ];

  return (
    <aside
      className={`fixed top-0 left-0 bottom-0 z-30 flex flex-col bg-[#070a11] border-r border-slate-800/80 transition-all duration-200 select-none ${
        collapsed ? 'w-18' : 'w-64'
      }`}
    >
      {/* Brand Header */}
      <div className="flex items-center justify-between h-16 px-4 border-b border-slate-800/80">
        <div className="flex items-center gap-3 overflow-hidden">
          <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-cyan-950/80 border border-cyan-500/40 text-cyan-400 shrink-0 shadow-lg shadow-cyan-950/50">
            <Shield className="w-5 h-5" />
          </div>
          {!collapsed && (
            <div className="flex flex-col">
              <span className="text-sm font-bold tracking-wider text-slate-100 font-mono">
                TRAFFIC<span className="text-cyan-400">SHIELD</span>
              </span>
              <span className="text-[10px] uppercase tracking-widest text-slate-400 font-mono">
                SOC Command Center
              </span>
            </div>
          )}
        </div>
        <button
          onClick={onToggleCollapse}
          className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 transition-colors"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelectTab(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium tracking-wide transition-all group ${
                isActive
                  ? 'bg-cyan-950/50 text-cyan-300 border border-cyan-500/40 shadow-sm shadow-cyan-950/60 font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60 border border-transparent'
              }`}
              title={collapsed ? item.label : undefined}
            >
              <Icon
                className={`w-4 h-4 shrink-0 transition-colors ${
                  isActive ? 'text-cyan-400' : 'text-slate-400 group-hover:text-slate-200'
                }`}
              />
              {!collapsed && (
                <span className="flex-1 text-left truncate">{item.label}</span>
              )}
              {!collapsed && item.badge && item.badge > 0 ? (
                <span className="px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-rose-500/20 text-rose-300 border border-rose-500/40">
                  {item.badge}
                </span>
              ) : null}
            </button>
          );
        })}
      </nav>

      {/* Observability Mode Pill */}
      <div className="p-3 border-t border-slate-800/80 bg-[#06080e]/60">
        {!collapsed ? (
          <div className="p-2.5 rounded-lg bg-slate-900/70 border border-slate-800 text-[11px] font-mono space-y-1">
            <div className="flex items-center justify-between text-slate-400">
              <span>Link Mode:</span>
              <span className="text-cyan-400 font-semibold">Unidirectional</span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <span>Zero-Return:</span>
              <span className="text-emerald-400">Strict Enforced</span>
            </div>
          </div>
        ) : (
          <div className="flex justify-center" title="Strict Unidirectional Enforced">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-md shadow-emerald-400/50" />
          </div>
        )}
      </div>
    </aside>
  );
};
