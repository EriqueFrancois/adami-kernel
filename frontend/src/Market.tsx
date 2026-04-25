/* src/adami-kernel/frontend/src/Market.tsx */
import { useState, useEffect } from 'react';
import { 
  Package, Search, Star, RefreshCw, 
  Brain, Github, Loader2, Upload,
  ChevronLeft, ChevronRight, AlertCircle
} from 'lucide-react';

import SkillCard from './SkillCard';
import { apiRoutes } from './api';
import { useLocale } from './i18n/useLocale';

// ====================== 【本次修复】严格对齐后端 Pydantic 模型 ======================
interface InstallResponse {
  status: 'success' | 'error';
  message?: string;
  error?: string;
  data?: {
    skill_name: string;
    version?: string;
    installed_version?: string;
    installed_at?: string;
  };
}

interface SkillItem {
  name: string;
  type: 'dynamic' | 'instinct';
  status: string;
  source: string;
  installed_at?: string;
  repo_url?: string;
  stars?: number;
  score?: number;
  description?: string;
  version?: string;           // 新增：后端返回版本号
  installed_version?: string; // 新增：已安装版本
  error?: string;             // 新增：错误信息
}

interface Recommendation {
  // 新版后端字段（推荐）：skill_name + title
  skill_name?: string;
  title?: string;
  // 兼容旧版后端字段：name 可能是中文标题（会导致 UI 把中文当“技能名”）
  name?: string;
  confidence: number;
  reason: string;
  category: string;
  repo_url?: string;
}
// =================================================================================

const Market = () => {
  const { t } = useLocale();
  const [activeTab, setActiveTab] = useState<'all' | 'recommend' | 'github' | 'upload'>('all');
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [githubResults, setGithubResults] = useState<SkillItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<'name' | 'stars' | 'confidence'>('name');
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 8;

  // 加载与错误状态
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  // 上传模态框状态
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadName, setUploadName] = useState('');
  const [uploadDesc, setUploadDesc] = useState('');
  const [uploadCode, setUploadCode] = useState('');
  const [uploading, setUploading] = useState(false);

  // Toast 自动消失
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  // 通用 fetch 错误处理函数
  const handleFetchError = (err: any, defaultMsg: string) => {
    console.error(defaultMsg, err);
    setError(defaultMsg);
    setToast({ message: defaultMsg, type: 'error' });
  };

  const safeJson = async (res: Response) => {
    try {
      return await res.json();
    } catch (err) {
      const text = await res.text().catch(() => '');
      console.error('Response is not JSON', { status: res.status, statusText: res.statusText, text, err });
      return null;
    }
  };

  // 获取技能列表（全部）
  const fetchSkills = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(apiRoutes.marketSkills());
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const data = await safeJson(res);
      if (!Array.isArray(data)) {
        console.error('Unexpected /market/skills payload (expected array)', data);
        setToast({ message: t('console.market.toastBadJsonSkills'), type: 'error' });
        setSkills([]);
      } else {
        setSkills(data);
      }
      setCurrentPage(1);
    } catch (err) {
      handleFetchError(err, t('console.market.fetchListFail'));
      setSkills([]);
    } finally {
      setLoading(false);
    }
  };

  // 获取推荐列表
  const fetchRecommendations = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(apiRoutes.marketRecommend());
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const data = await safeJson(res);
      if (!Array.isArray(data)) {
        console.error('Unexpected /market/recommend payload (expected array)', data);
        setToast({ message: t('console.market.toastBadJsonRecommend'), type: 'error' });
        setRecommendations([]);
      } else {
        setRecommendations(data as Recommendation[]);
      }
    } catch (err) {
      handleFetchError(err, t('console.market.fetchRecommendFail'));
      setRecommendations([]);
    } finally {
      setLoading(false);
    }
  };

  // GitHub 搜索
  const searchGitHub = async () => {
    if (!searchQuery.trim()) {
      setToast({ message: t('console.market.toastNeedSearchQuery'), type: 'error' });
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(apiRoutes.marketSearch(searchQuery));
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const data = await safeJson(res);
      if (!Array.isArray(data)) {
        console.error('Unexpected /market/search payload (expected array)', data);
        setToast({ message: t('console.market.toastBadJsonSearch'), type: 'error' });
        setGithubResults([]);
        return;
      }
      const sortedData = [...data].sort((a, b) => (b.stars || 0) - (a.stars || 0));
      // 后端 search 会返回 installed: boolean（若 repo.name 已安装）
      const normalized = sortedData.map((r: any) => ({
        ...r,
        type: r.type === 'instinct' ? 'instinct' : 'dynamic',
        status: r.installed ? 'active' : (r.status || 'idle'),
      }));
      setGithubResults(normalized);
      setCurrentPage(1);
      if (sortedData.length === 0) {
        setToast({ message: t('console.market.toastNoGithubResults'), type: 'error' });
      }
    } catch (err) {
      handleFetchError(err, t('console.market.githubSearchFail'));
      setGithubResults([]);
    } finally {
      setLoading(false);
    }
  };

  // ====================== 【本次核心修复】安装逻辑 - 严格字段映射 ======================
  const handleInstall = async (name: string, repoUrl?: string) => {
    setInstalling(name);
    try {
      const payload = repoUrl 
        ? { skill_name: name, source: "github", repo_url: repoUrl }
        : { skill_name: name, source: "local" };

      const res = await fetch(apiRoutes.marketInstall(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      
      const result = (await safeJson(res)) as InstallResponse | null;
      if (!result) {
        setToast({ message: t('console.market.toastBadJsonInstall'), type: 'error' });
        return;
      }

      // 严格字段映射 + 默认值
      if (result.status === 'success') {
        const installedName = result.data?.skill_name || name;
        const successMsg =
          result.message ||
          (result.data?.skill_name
            ? t('console.market.installSuccessMelt', { name: installedName })
            : t('console.market.installSuccess', { name: installedName }));
        setToast({ message: successMsg, type: 'success' });
        await fetchSkills();
        if (activeTab === 'recommend') await fetchRecommendations();
        if (activeTab === 'github') await searchGitHub();
      } else {
        const errMsg = result.error || result.message || t('console.market.installFail');
        setToast({ message: errMsg, type: 'error' });
      }
    } catch (err) {
      console.error('安装失败:', err);
      setToast({ message: t('console.market.netError'), type: 'error' });
    } finally {
      setInstalling(null);
    }
  };
  // =================================================================================

  // 自定义上传
  const handleUpload = async () => {
    if (!uploadName.trim() || !uploadCode.trim()) {
      setToast({ message: t('console.market.toastNameCodeRequired'), type: 'error' });
      return;
    }

    setUploading(true);
    try {
      const payload = {
        skill_name: uploadName.trim(),
        description: uploadDesc.trim() || t('console.market.uploadDescDefault'),
        code: uploadCode
      };

      const res = await fetch(apiRoutes.marketUpload(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const result = await safeJson(res);
      if (!result || typeof result !== 'object') {
        setToast({ message: t('console.market.toastBadJsonUpload'), type: 'error' });
        return;
      }

      if (result.status === 'success') {
        setToast({ message: t('console.market.uploadSuccess', { name: uploadName }), type: 'success' });
        setShowUploadModal(false);
        setUploadName('');
        setUploadDesc('');
        setUploadCode('');
        await fetchSkills();
        if (activeTab === 'recommend') await fetchRecommendations();
      } else {
        setToast({ message: result.message || result.error || t('console.market.uploadFail'), type: 'error' });
      }
    } catch (err) {
      console.error('上传失败:', err);
      setToast({ message: t('console.market.netError'), type: 'error' });
    } finally {
      setUploading(false);
    }
  };

  // 切换标签时自动刷新相关数据
  useEffect(() => {
    if (activeTab === 'recommend') {
      fetchRecommendations();
    } else if (activeTab === 'all') {
      if (skills.length === 0 && !loading) {
        fetchSkills();
      }
    }
  }, [activeTab]);

  // 初始加载
  useEffect(() => {
    fetchSkills();
    fetchRecommendations();
  }, []);

  const getSortedAndPaginatedItems = (items: any[]) => {
    let sorted = [...items];
    if (activeTab === 'github') {
      sorted.sort((a, b) => (b.stars || 0) - (a.stars || 0));
    } else if (sortBy === 'name') {
      sorted.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortBy === 'stars') {
      sorted.sort((a, b) => (b.stars || 0) - (a.stars || 0));
    } else if (sortBy === 'confidence') {
      sorted.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    }

    const start = (currentPage - 1) * itemsPerPage;
    return sorted.slice(start, start + itemsPerPage);
  };

  const isValidSkillName = (s: string) => /^[A-Z][A-Z0-9_]*$/.test(s);

  const currentItems = activeTab === 'all'
    ? getSortedAndPaginatedItems(skills)
    : activeTab === 'recommend'
      ? getSortedAndPaginatedItems(
          recommendations.map((r) => {
            const rawName = (r.skill_name || r.name || '').trim();
            const rawTitle = (r.title || r.name || '').trim();
            const skillName = isValidSkillName(rawName)
              ? rawName
              : (rawName ? rawName.replace(/\s+/g, '_').toUpperCase() : 'META_CORTEX_REC');
            const safeToInstall = isValidSkillName(skillName);

            return {
              name: safeToInstall ? skillName : `RECOMMENDATION_${Math.random().toString(16).slice(2, 8).toUpperCase()}`,
            type: 'dynamic',
            status: safeToInstall ? 'active' : 'idle',
            source: 'metacortex',
            repo_url: r.repo_url,
            description: rawTitle || r.reason,
            confidence: r.confidence,
            reason: r.reason,
            category: r.category,
            // 标记不可安装（供卡片文案提示：reason/description 展示）
            error: safeToInstall ? undefined : t('console.market.recoMissingSkillName'),
          };
        })
        )
      : getSortedAndPaginatedItems(githubResults);

  const totalPages = Math.ceil(
    (activeTab === 'all'
      ? skills.length
      : activeTab === 'recommend'
        ? recommendations.length
        : githubResults.length) / itemsPerPage
  );

  const showSkeleton = () => {
    if (activeTab === 'all') return loading && skills.length === 0;
    if (activeTab === 'recommend') return loading && recommendations.length === 0;
    if (activeTab === 'github') return loading && githubResults.length === 0;
    return false;
  };

  return (
    <div className="min-h-screen bg-[#0f172a] text-white p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-4">
          <Brain className="w-9 h-9 text-purple-400" />
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{t('console.app.titleMarket')}</h1>
            <p className="text-slate-400 text-sm">
              {t('console.market.headerSubtitle', { count: skills.length })}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="relative w-96">
            <Search className="absolute left-4 top-3.5 text-slate-400" />
            <input
              type="text"
              placeholder={t('console.market.searchPlaceholder')}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && activeTab === 'github' && searchGitHub()}
              className="w-full bg-slate-900 border border-slate-700 rounded-3xl pl-11 py-3 text-sm focus:outline-none focus:border-purple-500"
            />
          </div>
          <button 
            onClick={() => activeTab === 'github' ? searchGitHub() : fetchSkills()}
            className="px-6 py-3 bg-purple-600 hover:bg-purple-500 rounded-3xl flex items-center gap-2 text-sm font-medium"
          >
            <RefreshCw className="w-4 h-4" /> {t('console.market.refresh')}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-8 border-b border-slate-800 pb-1">
        {[
          { key: 'all', labelKey: 'console.market.tabAll' as const, icon: Package },
          { key: 'recommend', labelKey: 'console.market.tabRecommend' as const, icon: Star },
          { key: 'github', labelKey: 'console.market.tabGithub' as const, icon: Github },
          { key: 'upload', labelKey: 'console.market.tabUpload' as const, icon: Upload },
        ].map(tab => (
          <button
            key={tab.key}
            onClick={() => { 
              setActiveTab(tab.key as any); 
              if (tab.key === 'upload') {
                setShowUploadModal(true);
              } else {
                setCurrentPage(1); 
              }
            }}
            className={`px-6 py-2.5 rounded-3xl flex items-center gap-2 text-sm transition-all ${
              activeTab === tab.key 
                ? 'bg-white text-black shadow-xl' 
                : 'bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {t(tab.labelKey)}
          </button>
        ))}
      </div>

      {/* 排序控件 */}
      <div className="flex justify-end mb-6">
        <select 
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as any)}
          className="bg-slate-900 border border-slate-700 rounded-2xl px-5 py-2 text-sm focus:outline-none focus:border-purple-500"
        >
          <option value="name">{t('console.market.sortName')}</option>
          <option value="stars">{t('console.market.sortStars')}</option>
          <option value="confidence">{t('console.market.sortConfidence')}</option>
        </select>
      </div>

      {/* 内容区域 */}
      <div className="space-y-4">
        {/* 错误提示 */}
        {error && (
          <div className="bg-red-900/30 border border-red-500/50 rounded-2xl p-6 text-red-300 text-center flex items-center justify-center gap-3">
            <AlertCircle className="w-5 h-5" />
            {error}
          </div>
        )}

        {/* 骨架屏 */}
        {showSkeleton() && (
          <div className="space-y-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="bg-slate-800/50 animate-pulse h-40 rounded-2xl"></div>
            ))}
          </div>
        )}

        {/* 数据列表 */}
        {!showSkeleton() && currentItems.length > 0 ? (
          currentItems.map((item) => (
            <SkillCard 
              key={item.name}
              skill={item}
              onInstall={handleInstall}
              installing={installing}
              installedNames={new Set(skills.map(s => s.name.toUpperCase()))}
            />
          ))
        ) : !showSkeleton() && !error && (
          <div className="text-center py-20 text-slate-500">
            {activeTab === 'github' && searchQuery ? t('console.market.noGithubMatches') : t('console.market.noData')}
          </div>
        )}
      </div>

      {/* 分页控件 */}
      {totalPages > 1 && !showSkeleton() && !error && (
        <div className="flex justify-center items-center gap-4 mt-10">
          <button 
            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            disabled={currentPage === 1}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 rounded-xl flex items-center gap-2 transition"
          >
            <ChevronLeft className="w-4 h-4" />
            {t('console.market.prev')}
          </button>
          <span className="text-slate-400 font-mono">
            {t('console.market.page', { current: currentPage, total: totalPages })}
          </span>
          <button 
            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
            disabled={currentPage === totalPages}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 rounded-xl flex items-center gap-2 transition"
          >
            {t('console.market.next')}
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-8 right-8 px-8 py-4 rounded-3xl shadow-2xl flex items-center gap-3 z-50 ${toast.type === 'success' ? 'bg-emerald-600' : 'bg-red-600'}`}>
          {toast.message}
        </div>
      )}

      {/* 自定义上传弹窗 */}
      {showUploadModal && (
        <div className="fixed inset-0 bg-black/90 flex items-center justify-center z-[100]">
          <div className="bg-slate-900 rounded-3xl w-[90%] max-w-3xl p-10 border border-slate-700 max-h-[90vh] overflow-auto">
            <div className="flex justify-between items-center mb-8">
              <div>
                <h3 className="text-3xl font-bold">{t('console.market.uploadTitle')}</h3>
                <p className="text-slate-400 mt-1">{t('console.market.uploadSubtitle')}</p>
              </div>
              <button 
                onClick={() => setShowUploadModal(false)} 
                className="text-4xl leading-none text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <input
              type="text"
              placeholder={t('console.market.uploadNamePh')}
              value={uploadName}
              onChange={(e) => setUploadName(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-2xl px-6 py-4 text-lg mb-4"
            />

            <textarea
              placeholder={t('console.market.uploadDescPh')}
              value={uploadDesc}
              onChange={(e) => setUploadDesc(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-2xl px-6 py-4 h-20 mb-6"
            />

            <textarea
              placeholder={t('console.market.uploadCodePh')}
              value={uploadCode}
              onChange={(e) => setUploadCode(e.target.value)}
              className="w-full bg-[#0a0f1c] border border-slate-700 rounded-2xl px-6 py-5 font-mono text-sm h-96 resize-y"
            />

            <div className="flex gap-4 mt-10">
              <button 
                onClick={() => setShowUploadModal(false)}
                className="flex-1 py-5 bg-slate-800 hover:bg-slate-700 rounded-3xl text-lg"
              >
                {t('console.market.cancel')}
              </button>
              <button 
                onClick={handleUpload}
                disabled={uploading || !uploadName.trim() || !uploadCode.trim()}
                className="flex-1 py-5 bg-violet-600 hover:bg-violet-500 disabled:bg-slate-700 rounded-3xl text-lg font-medium flex items-center justify-center gap-3"
              >
                {uploading ? (
                  <>
                    <Loader2 className="w-6 h-6 animate-spin" />
                    {t('console.market.uploading')}
                  </>
                ) : (
                  t('console.market.submitMelt')
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Market;