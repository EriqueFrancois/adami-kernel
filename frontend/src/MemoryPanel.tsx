import React from 'react';
import { Database, Search, ChevronLeft, ChevronRight } from 'lucide-react';

import { useLocale } from './i18n/useLocale';

interface MemoryItem {
  domain: string;
  count: number;
  last_updated: string;
  payload_preview: string;
  full_payload?: any;
}

interface MemoryPanelProps {
  memoryData: MemoryItem[];
  filteredMemory: MemoryItem[];
  memorySearch: string;
  memoryPage: number;
  setMemorySearch: (value: string) => void;
  setMemoryPage: (page: number) => void;
  viewMemoryDetail: (memory: MemoryItem) => void;
  loadingError?: boolean;
}

const MemoryPanel: React.FC<MemoryPanelProps> = ({
  memoryData,
  filteredMemory,
  memorySearch,
  memoryPage,
  setMemorySearch,
  setMemoryPage,
  viewMemoryDetail,
  loadingError = false,
}) => {
  const { t } = useLocale();
  const itemsPerPage = 10;
  const totalMemoryPages = Math.ceil(filteredMemory.length / itemsPerPage);
  const paginatedMemory = filteredMemory.slice(
    (memoryPage - 1) * itemsPerPage,
    memoryPage * itemsPerPage
  );

  // 骨架屏判断
  const showSkeleton = memoryData.length === 0 && !loadingError;

  return (
    <div className="bg-slate-900/90 backdrop-blur-xl border border-slate-700 rounded-3xl p-8">
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-4">
          <Database className="w-9 h-9 text-violet-400" />
          <div>
            <h2 className="text-3xl font-bold">{t('console.memory.title')}</h2>
            <p className="text-slate-400">{t('console.memory.subtitle')}</p>
          </div>
        </div>
        <div className="relative w-80">
          <Search className="absolute left-4 top-3.5 text-slate-400" />
          <input
            type="text"
            placeholder={t('console.memory.searchPlaceholder')}
            value={memorySearch}
            onChange={(e) => setMemorySearch(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-2xl pl-11 py-3 text-sm focus:outline-none focus:border-purple-500"
          />
        </div>
      </div>

      {/* 骨架屏 */}
      {showSkeleton && (
        <div className="space-y-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="bg-slate-800/50 animate-pulse h-24 rounded-2xl"></div>
          ))}
        </div>
      )}

      {/* 数据列表 */}
      {!showSkeleton && filteredMemory.length > 0 ? (
        <>
          <div className="space-y-4">
            {paginatedMemory.map((mem) => (
              <div
                key={mem.domain}
                onClick={() => viewMemoryDetail(mem)}
                className="bg-black/30 border border-slate-700 hover:border-violet-400 p-6 rounded-2xl cursor-pointer transition-all group flex items-center justify-between"
              >
                <div>
                  <div className="font-mono text-xl text-white truncate max-w-md" title={mem.domain}>{mem.domain}</div>
                  <div className="text-xs text-slate-400 mt-1">{t('console.memory.updated', { time: mem.last_updated })}</div>
                </div>
                <div className="flex items-center gap-6">
                  <div className="text-emerald-400 text-lg font-medium">{t('console.memory.countBadge', { n: mem.count })}</div>
                  <div className="text-violet-400 text-xs group-hover:underline">{t('console.memory.viewDetail')}</div>
                </div>
              </div>
            ))}
          </div>

          {/* 分页控件 */}
          {totalMemoryPages > 1 && (
            <div className="flex justify-center items-center gap-4 mt-8">
              <button
                onClick={() => setMemoryPage(Math.max(1, memoryPage - 1))}
                disabled={memoryPage === 1}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 rounded-xl flex items-center gap-2 transition"
              >
                <ChevronLeft className="w-4 h-4" />
                {t('console.memory.prev')}
              </button>
              <span className="text-slate-400 font-mono">
                {t('console.memory.page', { current: memoryPage, total: totalMemoryPages })}
              </span>
              <button
                onClick={() => setMemoryPage(Math.min(totalMemoryPages, memoryPage + 1))}
                disabled={memoryPage === totalMemoryPages}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 rounded-xl flex items-center gap-2 transition"
              >
                {t('console.memory.next')}
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </>
      ) : !showSkeleton && !loadingError && (
        <div className="text-center py-20 text-slate-500">
          📭 {t('console.memory.emptyTitle')}<br />
          <span className="text-sm mt-2 block">{t('console.memory.emptyHint')}</span>
        </div>
      )}
    </div>
  );
};

export default MemoryPanel;