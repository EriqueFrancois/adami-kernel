// frontend/src/App.tsx
import React from 'react';
import { useState, useEffect, useRef } from 'react';
import { 
  Brain, Zap, Database, Settings, Package, AlertCircle 
} from 'lucide-react';

import Dashboard from './Dashboard';
import MemoryPanel from './MemoryPanel';
import SkillsPanel from './SkillsPanel';
import Market from './Market';
import { apiRoutes, WS_EVENTS_URL } from './api';
import { useLocale } from './i18n/useLocale';

function ErrorFallback() {
  const { t } = useLocale();
  return (
    <div className="min-h-screen bg-[#0f172a] flex items-center justify-center p-8">
      <div className="bg-slate-900 rounded-3xl p-8 max-w-md text-center border border-red-500/30">
        <AlertCircle className="w-12 h-12 text-red-400 mx-auto mb-4" />
        <h2 className="text-xl font-bold text-white mb-2">{t('console.app.errorTitle')}</h2>
        <p className="text-slate-400 mb-4">{t('console.app.errorBody')}</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="px-6 py-2 bg-purple-600 hover:bg-purple-500 rounded-xl"
        >
          {t('console.app.refresh')}
        </button>
      </div>
    </div>
  );
}

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean }> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('UI render error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return <ErrorFallback />;
    }
    return this.props.children;
  }
}

const Modal = ({ isOpen, onClose, title, children }: any) => {
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
      <div className="bg-slate-900 rounded-3xl w-[90%] max-w-2xl p-8 relative border border-slate-700">
        <button 
          onClick={onClose} 
          className="absolute top-6 right-6 text-slate-400 hover:text-white text-3xl leading-none"
        >
          ✕
        </button>
        <h3 className="text-2xl font-bold mb-6 text-white">{title}</h3>
        {children}
      </div>
    </div>
  );
};

interface DashboardData {
  status: string;
  dynamic_skills: number;
  reboot_count: number;
  memory_summary: string;
  proprioception: string;
  uptime: string;
  active_workflows?: number;
  active_workflow_list?: any[];
  /** Kernel ``effective_ui_default_locale()`` — drives frontend catalog selection. */
  ui_locale?: string;
  supported_locales?: string[];
}

interface EventLog {
  time: string;
  message: string;
  type: 'info' | 'success' | 'warning';
}

interface MemoryItem {
  domain: string;
  count: number;
  last_updated: string;
  payload_preview: string;
  full_payload?: any;
}

interface SkillItem {
  name: string;
  usage: number;
  status: 'active' | 'idle';
  last_used: string;
  type?: 'dynamic' | 'instinct';
}

interface WorkflowItem {
  workflow_id: string;
  status: string;
  current_node_id?: string;
  global_step_count: number;
  created_at: string;
}

interface TDDScore {
  skill_name: string;
  score: number;
  pass_rate: number;
  execution_time: number;
  peak_memory_mb: number;
  timestamp: string;
}

interface ReflexionLog {
  workflow_id: string;
  root_cause: string;
  suggested_action: string;
  confidence: number;
  timestamp: string;
}

// ====================== 【步骤6 新增】Agent Lightning 前端事件流 ======================
// Backend 已通过 WebSocket 推送 Agent Lightning 的 trace/reward 信号（tdd_scores、reflexion_logs、skill_creation_reward）
// 前端在此处实时展示 RL 进化指标，实现“人类可见的自进化”
// =================================================================================

function App() {
  const { t, setLocaleFromServer } = useLocale();
  const tRef = useRef(t);
  tRef.current = t;

  const [data, setData] = useState<DashboardData | null>(null);
  const [logs, setLogs] = useState<EventLog[]>([]);
  const [activeTab, setActiveTab] = useState<'dashboard' | 'memory' | 'skills' | 'market'>('dashboard');
  const [memoryData, setMemoryData] = useState<MemoryItem[]>([]);
  const [skillsData, setSkillsData] = useState<SkillItem[]>([]);
  const [filteredMemory, setFilteredMemory] = useState<MemoryItem[]>([]);
  const [filteredSkills, setFilteredSkills] = useState<SkillItem[]>([]);
  const [memorySearch, setMemorySearch] = useState('');
  const [skillSearch, setSkillSearch] = useState('');
  const [wsStatus, setWsStatus] = useState<'connected' | 'disconnected'>('disconnected');
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showMemoryModal, setShowMemoryModal] = useState(false);
  const [selectedSkillToDelete, setSelectedSkillToDelete] = useState<string | null>(null);
  const [selectedMemoryDetail, setSelectedMemoryDetail] = useState<MemoryItem | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [loadingError, setLoadingError] = useState(false);
  const [awakeningDeclaration, setAwakeningDeclaration] = useState<string>("");

  const [totalSkills, setTotalSkills] = useState(0);
  const [activeWorkflows, setActiveWorkflows] = useState<WorkflowItem[]>([]);
  const [tddScores, setTddScores] = useState<TDDScore[]>([]);
  const [reflexionLogs, setReflexionLogs] = useState<ReflexionLog[]>([]);

  const [memoryPage, setMemoryPage] = useState(1);
  const [skillsPage, setSkillsPage] = useState(1);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isConnectingRef = useRef(false);

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const connectWebSocket = () => {
    if (isConnectingRef.current || (wsRef.current && wsRef.current.readyState === WebSocket.OPEN)) return;
    isConnectingRef.current = true;
    if (wsRef.current) wsRef.current.close();

    const ws = new WebSocket(WS_EVENTS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      isConnectingRef.current = false;
      setWsStatus('connected');
      addLog(tRef.current('console.app.wsConnectedLog'), 'success');
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'ping') return;

        // ====================== 【步骤6 新增】Agent Lightning 事件解析 ======================
        if (msg.type === 'dashboard_update') {
          setTddScores(msg.tdd_scores || []);
          setReflexionLogs(msg.reflexion_logs || []);
          // RL reward 信号已在 backend 通过 trace 推送，前端实时展示
          const hasData = 
            (msg.active_workflows && msg.active_workflows.length > 0) ||
            (msg.tdd_scores && msg.tdd_scores.length > 0) ||
            (msg.reflexion_logs && msg.reflexion_logs.length > 0);
          if (hasData) addLog(msg.message || JSON.stringify(msg), 'info');
        } else {
          addLog(msg.message || JSON.stringify(msg), 'info');
        }
        // =================================================================================
      } catch {
        addLog(event.data, 'info');
      }
    };

    ws.onclose = () => {
      isConnectingRef.current = false;
      setWsStatus('disconnected');
      addLog(tRef.current('console.app.wsDisconnectedLog'), 'warning');
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
      isConnectingRef.current = false;
      addLog(tRef.current('console.app.wsErrorLog'), 'warning');
    };
  };

  const addLog = (message: string, type: 'info' | 'success' | 'warning' = 'info') => {
    const newLog = { time: new Date().toLocaleTimeString(), message, type };
    setLogs(prev => [newLog, ...prev].slice(0, 100));
  };

  useEffect(() => {
    const fetchDashboard = async () => {
      try {
        const res = await fetch(apiRoutes.dashboard());
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = (await res.json()) as DashboardData;
        setData(json);
        if (json.ui_locale) setLocaleFromServer(json.ui_locale);
        setLoadingError(false);

        const skillsRes = await fetch(apiRoutes.skills());
        const skillsList = await skillsRes.json();
        const realCount = Array.isArray(skillsList) ? skillsList.length : (json.dynamic_skills || 0);
        setTotalSkills(realCount);

        const workflowsRes = await fetch(apiRoutes.activeWorkflows());
        if (workflowsRes.ok) {
          const wfRaw = await workflowsRes.json();
          setActiveWorkflows(Array.isArray(wfRaw) ? wfRaw : []);
        }

        const rulesRes = await fetch(apiRoutes.memory('semantic_rules'));
        const rulesRaw = await rulesRes.json();
        const rules = Array.isArray(rulesRaw) ? rulesRaw : [];
        const lastRule = rules.find((r: any) => r?.domain === 'semantic_rules');
        if (lastRule && lastRule.full_payload && lastRule.full_payload.insight) {
          setAwakeningDeclaration(lastRule.full_payload.insight);
        }

        const tddRes = await fetch(apiRoutes.tddScores());
        if (tddRes.ok) {
          const tddRaw = await tddRes.json();
          setTddScores(Array.isArray(tddRaw) ? tddRaw : []);
        }
        
        const reflexRes = await fetch(apiRoutes.reflexionLogs());
        if (reflexRes.ok) {
          const reflexRaw = await reflexRes.json();
          setReflexionLogs(Array.isArray(reflexRaw) ? reflexRaw : []);
        }
      } catch (err) {
        console.error('Dashboard fetch failed', err);
        setLoadingError(true);
        showToast(t('console.app.toastBackendUnreachable'), 'error');
      }
    };
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 3000);
    return () => clearInterval(interval);
  }, []);

  const fetchMemory = async () => {
    try {
      const res = await fetch(apiRoutes.memory(memorySearch));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = await res.json();
      const parsed: MemoryItem[] = Array.isArray(raw) ? raw.map((item: any) => ({
        domain: item.domain || t('console.app.unknownDomain'),
        count: item.count || 0,
        last_updated: item.last_updated || t('console.app.memoryJustNow'),
        payload_preview: item.payload_preview || t('console.app.memoryPreviewPlaceholder'),
        full_payload: item.full_payload || {}
      })) : [];
      setMemoryData(parsed);
      setFilteredMemory(parsed);
      setMemoryPage(1);
    } catch (err) {
      console.error(err);
      setMemoryData([]);
      showToast(t('console.app.loadMemFail'), 'error');
    }
  };

  useEffect(() => {
    if (activeTab === 'memory') fetchMemory();
  }, [activeTab]);

  const fetchSkills = async () => {
    setSkillsLoading(true);
    try {
      const res = await fetch(apiRoutes.skills());
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      let raw = await res.json();
      if (!Array.isArray(raw)) raw = [];
      const parsed: SkillItem[] = raw.map((item: any) => ({
        name: item.name || 'unknown',
        usage: typeof item.usage === 'number' ? item.usage : 0,
        status: item.status === 'active' ? 'active' : 'idle',
        last_used: item.last_used || '未知',
        type: item.type === 'instinct' ? 'instinct' : 'dynamic',
      }));
      // “动态技能库”只展示可管理/可删除的动态技能（instinct 为永久固化，不提供删除）
      const dynamicOnly = parsed.filter((s) => s.type !== 'instinct');
      setSkillsData(dynamicOnly);
      setFilteredSkills(dynamicOnly);
      setSkillsPage(1);
    } catch (err) {
      console.error(err);
      setSkillsData([]);
      showToast(t('console.app.loadSkillsFail'), 'error');
    } finally {
      setSkillsLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'skills') fetchSkills();
  }, [activeTab]);

  const handleDeleteSkill = async () => {
    if (!selectedSkillToDelete) return;
    try {
      const res = await fetch(`${apiRoutes.skills()}/${selectedSkillToDelete}`, { method: 'DELETE' });
      let body: any = null;
      try {
        body = await res.json();
      } catch {
        // ignore
      }
      const status = body?.status;
      const msg = body?.message || body?.detail;

      if (res.ok && status === 'success') {
        showToast(msg || t('console.app.skillDeleted', { name: selectedSkillToDelete }), 'success');
        await fetchSkills();
      } else {
        showToast(msg || t('console.app.deleteFail'), 'error');
      }
    } catch {
      showToast(t('console.app.deleteNetError'), 'error');
    }
    setShowDeleteModal(false);
    setSelectedSkillToDelete(null);
  };

  useEffect(() => {
    if (memorySearch.trim() === '') setFilteredMemory(memoryData);
    else {
      const term = memorySearch.toLowerCase();
      setFilteredMemory(memoryData.filter(m => m.domain.toLowerCase().includes(term)));
    }
    setMemoryPage(1);
  }, [memorySearch, memoryData]);

  useEffect(() => {
    if (skillSearch.trim() === '') setFilteredSkills(skillsData);
    else {
      const term = skillSearch.toLowerCase();
      setFilteredSkills(skillsData.filter(s => s.name.toLowerCase().includes(term)));
    }
    setSkillsPage(1);
  }, [skillSearch, skillsData]);

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, []);

  const viewMemoryDetail = (memory: MemoryItem) => {
    setSelectedMemoryDetail(memory);
    setShowMemoryModal(true);
  };

  if (loadingError && !data) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#0f172a] text-white text-xl flex-col">
        ❌ {t('console.app.backendDownTitle')}<br />
        <span className="text-sm text-slate-400 mt-4">{t('console.app.backendDownHint')}</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#0f172a] text-white text-xl">
        {t('console.app.loading')}
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0f172a] text-white flex">
      {/* 侧边栏 */}
      <div className="w-72 bg-slate-950 border-r border-slate-800 p-6 flex flex-col">
        <div className="flex items-center gap-3 mb-12">
          <div className="w-11 h-11 bg-gradient-to-br from-purple-500 to-cyan-500 rounded-2xl flex items-center justify-center">
            <Brain className="w-7 h-7" />
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">AdamI</h1>
            <p className="text-xs text-slate-400">{t('console.app.rebootLine', { count: data.reboot_count })}</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1">
          {[
            { id: 'dashboard', label: t('console.app.navDashboard'), icon: Zap },
            { id: 'memory', label: t('console.app.navMemory'), icon: Database },
            { id: 'skills', label: t('console.app.navSkills'), icon: Settings },
            { id: 'market', label: t('console.app.navMarket'), icon: Package }
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id as any)}
              className={`w-full flex items-center gap-3 px-6 py-4 rounded-2xl text-left transition-all ${
                activeTab === id ? 'bg-white text-black shadow-xl' : 'hover:bg-slate-900 text-slate-400 hover:text-white'
              }`}
            >
              <Icon className="w-5 h-5" />
              <span className="font-medium">{label}</span>
            </button>
          ))}
        </nav>

        <div className="pt-6 border-t border-slate-800 text-xs text-slate-500">
          {t('console.app.wsLabel')}:{' '}
          <span className={wsStatus === 'connected' ? 'text-emerald-400' : 'text-red-400'}>
            {wsStatus === 'connected' ? t('console.app.wsConnected') : t('console.app.wsDisconnected')}
          </span>
        </div>
      </div>

      {/* 主内容区 */}
      <div className="flex-1 p-8 overflow-auto">
        <div className="flex items-center justify-between mb-8">
          <h2 className="text-3xl font-semibold tracking-tight">
            {activeTab === 'dashboard' && t('console.app.titleDashboard')}
            {activeTab === 'memory' && t('console.app.titleMemory')}
            {activeTab === 'skills' && t('console.app.titleSkills')}
            {activeTab === 'market' && t('console.app.titleMarket')}
          </h2>
          <div className={`px-5 py-2 rounded-3xl flex items-center gap-2 ${wsStatus === 'connected' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
            <div className={`w-2 h-2 rounded-full ${wsStatus === 'connected' ? 'bg-emerald-400 animate-pulse' : ''}`} />
            {wsStatus === 'connected' ? t('console.app.liveOnline') : t('console.app.reconnecting')}
          </div>
        </div>

        {activeTab === 'dashboard' && (
          <Dashboard
            data={data}
            logs={logs}
            totalSkills={totalSkills}
            activeWorkflows={activeWorkflows}
            tddScores={tddScores}
            reflexionLogs={reflexionLogs}
            awakeningDeclaration={awakeningDeclaration}
          />
        )}

        {activeTab === 'memory' && (
          <MemoryPanel
            memoryData={memoryData}
            filteredMemory={filteredMemory}
            memorySearch={memorySearch}
            memoryPage={memoryPage}
            setMemorySearch={setMemorySearch}
            setMemoryPage={setMemoryPage}
            viewMemoryDetail={viewMemoryDetail}
            loadingError={loadingError}
          />
        )}

        {activeTab === 'skills' && (
          <SkillsPanel
            skillsData={skillsData}
            filteredSkills={filteredSkills}
            skillSearch={skillSearch}
            skillsPage={skillsPage}
            skillsLoading={skillsLoading}
            setSkillSearch={setSkillSearch}
            setSkillsPage={setSkillsPage}
            fetchSkills={fetchSkills}
            onDeleteSkill={(name) => {
              setSelectedSkillToDelete(name);
              setShowDeleteModal(true);
            }}
          />
        )}

        {activeTab === 'market' && <Market />}
      </div>

      {/* Modals & Toast */}
      <Modal isOpen={showMemoryModal} onClose={() => setShowMemoryModal(false)} title={t('console.app.memoryDetailTitle')}>
        {selectedMemoryDetail && (
          <div className="space-y-6">
            <div className="font-mono text-2xl text-violet-400">{selectedMemoryDetail.domain}</div>
            <pre className="bg-black/60 p-6 rounded-2xl text-sm overflow-auto max-h-96">
              {typeof (selectedMemoryDetail.full_payload ?? selectedMemoryDetail) === 'string'
                ? (selectedMemoryDetail.full_payload ?? selectedMemoryDetail)
                : JSON.stringify(selectedMemoryDetail.full_payload || selectedMemoryDetail, null, 2)}
            </pre>
            <button type="button" onClick={() => setShowMemoryModal(false)} className="w-full py-4 bg-violet-600 hover:bg-violet-500 rounded-2xl font-medium">
              {t('console.app.close')}
            </button>
          </div>
        )}
      </Modal>

      <Modal isOpen={showDeleteModal} onClose={() => setShowDeleteModal(false)} title={t('console.app.deleteConfirmTitle')}>
        {selectedSkillToDelete && (
          <div className="text-center">
            <p className="text-xl mb-8">
              {t('console.app.deleteConfirmBody', { name: selectedSkillToDelete })}
            </p>
            <div className="flex gap-4">
              <button type="button" onClick={() => setShowDeleteModal(false)} className="flex-1 py-4 bg-slate-800 hover:bg-slate-700 rounded-2xl">
                {t('console.app.cancel')}
              </button>
              <button type="button" onClick={handleDeleteSkill} className="flex-1 py-4 bg-red-600 hover:bg-red-500 rounded-2xl font-medium">
                {t('console.app.confirmDelete')}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {toast && (
        <div className={`fixed bottom-8 right-8 px-8 py-4 rounded-2xl shadow-2xl text-white flex items-center gap-3 z-50 ${toast.type === 'success' ? 'bg-emerald-600' : 'bg-red-600'}`}>
          {toast.message}
        </div>
      )}
    </div>
  );
}

// 导出时用错误边界包裹
export default function AppWithErrorBoundary() {
  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  );
}

// frontend/src/App.tsx