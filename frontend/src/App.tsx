import React, { useEffect, useState, useCallback } from 'react';
import { Sidebar, type NavTab } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import { TrafficAnalysisPage } from './pages/TrafficAnalysisPage';
import { LiveDetectionPage } from './pages/LiveDetectionPage';
import { AlertsPage } from './pages/AlertsPage';
import { FlowInspectorPage } from './pages/FlowInspectorPage';
import { ModelPerformancePage } from './pages/ModelPerformancePage';
import { ModelIntelligencePage } from './pages/ModelIntelligencePage';
import { MonitoringPage } from './pages/MonitoringPage';
import { ReportsPage } from './pages/ReportsPage';
import { SettingsPage } from './pages/SettingsPage';
import {
  api,
  getStoredToken,
  getStoredUser,
  setOnUnauthorizedCallback,
  type AuthUserInfo,
} from './services/api';
import type { AlertStats, ModelInfoResponse, SecurityAlert } from './types/api';
import { LoadingSpinner } from './components/common/LoadingSpinner';

export function App() {
  const [currentUser, setCurrentUser] = useState<AuthUserInfo | null>(getStoredUser());
  const [authChecking, setAuthChecking] = useState<boolean>(true);

  const [activeTab, setActiveTab] = useState<NavTab>('overview');
  const [collapsed, setCollapsed] = useState<boolean>(false);

  // Global Backend Status
  const [apiOnline, setApiOnline] = useState<boolean>(false);
  const [modelInfo, setModelInfo] = useState<ModelInfoResponse | null>(null);
  const [stats, setStats] = useState<AlertStats | null>(null);
  const [recentAlerts, setRecentAlerts] = useState<SecurityAlert[]>([]);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [seeding, setSeeding] = useState<boolean>(false);

  // Alerts Page State
  const [alertsList, setAlertsList] = useState<SecurityAlert[]>([]);
  const [totalAlerts, setTotalAlerts] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [alertsLoading, setAlertsLoading] = useState<boolean>(false);
  const [alertFilters, setAlertFilters] = useState<{
    status?: string;
    risk_level?: string;
    search?: string;
  }>({});

  // Selected Alert for Investigation Modal Drawer
  const [selectedAlert, setSelectedAlert] = useState<SecurityAlert | null>(null);

  // Set up unauthorized listener and verify active token session on startup
  useEffect(() => {
    setOnUnauthorizedCallback(() => {
      setCurrentUser(null);
    });

    const verifyActiveSession = async () => {
      const token = getStoredToken();
      if (!token) {
        setCurrentUser(null);
        setAuthChecking(false);
        return;
      }
      try {
        const me = await api.getMe();
        if (me) {
          setCurrentUser(me);
        } else {
          setCurrentUser(null);
        }
      } catch {
        setCurrentUser(null);
      } finally {
        setAuthChecking(false);
      }
    };

    verifyActiveSession();
  }, []);

  // Fetch Global Stats & Health
  const fetchGlobalData = useCallback(async () => {
    setRefreshing(true);
    try {
      await api.checkHealth();
      setApiOnline(true);
    } catch {
      setApiOnline(false);
    }

    try {
      const [info, st, recent] = await Promise.allSettled([
        api.getModelInfo(),
        api.getAlertStats(),
        api.listAlerts({ page: 1, per_page: 10 }),
      ]);

      if (info.status === 'fulfilled') setModelInfo(info.value);
      if (st.status === 'fulfilled') setStats(st.value);
      if (recent.status === 'fulfilled') {
        setRecentAlerts(recent.value.data);
      }
    } finally {
      setRefreshing(false);
    }
  }, []);

  // Fetch Paginated Alerts Table
  const fetchAlertsList = useCallback(
    async (page: number, filters = alertFilters) => {
      setAlertsLoading(true);
      try {
        const res = await api.listAlerts({
          page,
          per_page: 15,
          status: filters.status,
          risk_level: filters.risk_level,
          search: filters.search,
        });
        setAlertsList(res.data);
        setTotalAlerts(res.meta.pagination.total);
        setCurrentPage(page);
      } catch {
        setAlertsList([]);
        setTotalAlerts(0);
      } finally {
        setAlertsLoading(false);
      }
    },
    [alertFilters]
  );

  useEffect(() => {
    if (currentUser) {
      fetchGlobalData();
    }
  }, [currentUser, fetchGlobalData]);

  useEffect(() => {
    if (currentUser && (activeTab === 'alerts' || activeTab === 'overview')) {
      fetchAlertsList(currentPage);
    }
  }, [currentUser, activeTab, currentPage, fetchAlertsList]);

  const handleLogout = async () => {
    try {
      await api.logout();
    } finally {
      setCurrentUser(null);
    }
  };

  // Seed 5 Demonstration Alerts
  const handleSeedDemo = async () => {
    setSeeding(true);
    try {
      await api.seedDemoAlerts(true);
      await fetchGlobalData();
      await fetchAlertsList(1);
    } catch (err: unknown) {
      alert(`Failed to seed demo alerts: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSeeding(false);
    }
  };

  const handleAlertUpdated = (updated: SecurityAlert) => {
    setSelectedAlert(updated);
    setAlertsList((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
    setRecentAlerts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
    api.getAlertStats().then(setStats).catch(() => {});
  };

  // While checking auth token on page load, show lightweight tactical loader
  if (authChecking) {
    return (
      <div className="min-h-screen bg-[#07090e] text-slate-100 flex flex-col items-center justify-center bg-tactical-grid">
        <LoadingSpinner size="lg" />
        <p className="mt-4 text-xs font-mono tracking-widest text-slate-400 uppercase">
          Verifying Operator Credentials...
        </p>
      </div>
    );
  }

  // If not authenticated, render dedicated Login Portal
  if (!currentUser) {
    return (
      <LoginPage
        onLoginSuccess={(user) => {
          setCurrentUser(user);
        }}
      />
    );
  }

  return (
    <div className="min-h-screen bg-[#07090e] text-slate-100 flex flex-col bg-tactical-grid">
      {/* Sidebar Navigation */}
      <Sidebar
        activeTab={activeTab}
        onSelectTab={(tab) => {
          setActiveTab(tab);
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed(!collapsed)}
        unreadAlertCount={stats?.status_distribution.NEW ?? 0}
      />

      {/* Top Header */}
      <Header
        modelInfo={modelInfo}
        apiOnline={apiOnline}
        onRefresh={() => {
          fetchGlobalData();
          fetchAlertsList(currentPage);
        }}
        refreshing={refreshing}
        collapsed={collapsed}
        user={currentUser}
        onLogout={handleLogout}
      />

      {/* Main Content Viewport */}
      <main
        className={`flex-1 transition-all duration-200 mt-16 p-6 lg:p-8 ${
          collapsed ? 'ml-18' : 'ml-64'
        }`}
      >
        <div className="max-w-7xl mx-auto">
          {activeTab === 'overview' && (
            <OverviewPage
              stats={stats}
              recentAlerts={recentAlerts}
              modelInfo={modelInfo}
              onNavigateToAlerts={() => setActiveTab('alerts')}
              onNavigateToTraffic={() => setActiveTab('traffic')}
              onSelectAlert={(a) => {
                setSelectedAlert(a);
                setActiveTab('alerts');
              }}
              onSeedDemo={handleSeedDemo}
              seeding={seeding}
            />
          )}

          {activeTab === 'traffic' && (
            <TrafficAnalysisPage
              onAlertsPersisted={() => {
                fetchGlobalData();
                fetchAlertsList(1);
              }}
            />
          )}

          {activeTab === 'live' && <LiveDetectionPage />}

          {activeTab === 'alerts' && (
            <AlertsPage
              alerts={alertsList}
              totalAlerts={totalAlerts}
              currentPage={currentPage}
              perPage={15}
              loading={alertsLoading}
              onPageChange={(p) => fetchAlertsList(p)}
              onFilterChange={(f) => {
                setAlertFilters(f);
                fetchAlertsList(1, f);
              }}
              onAlertUpdated={handleAlertUpdated}
              selectedAlert={selectedAlert}
              onSelectAlert={setSelectedAlert}
            />
          )}

          {activeTab === 'monitoring' && <MonitoringPage />}

          {activeTab === 'inspector' && (
            <FlowInspectorPage
              onAlertPersisted={() => {
                fetchGlobalData();
                fetchAlertsList(1);
              }}
            />
          )}

          {activeTab === 'evaluation' && <ModelPerformancePage />}

          {activeTab === 'model' && <ModelIntelligencePage modelInfo={modelInfo} />}

          {activeTab === 'reports' && (
            <ReportsPage stats={stats} alerts={alertsList} modelInfo={modelInfo} />
          )}

          {activeTab === 'settings' && (
            <SettingsPage
              onRefreshData={() => {
                fetchGlobalData();
                fetchAlertsList(1);
              }}
              onSeedDemo={handleSeedDemo}
              seeding={seeding}
            />
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
