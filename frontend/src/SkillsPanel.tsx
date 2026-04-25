import React from 'react';
import { Settings, RefreshCw, Search, PlayCircle, Eye, Trash2, ChevronLeft, ChevronRight } from 'lucide-react';

import { useLocale } from './i18n/useLocale';

interface SkillItem {
  name: string;
  usage: number;
  status: 'active' | 'idle';
  last_used: string;
}

interface SkillsPanelProps {
  skillsData: SkillItem[];
  filteredSkills: SkillItem[];
  skillSearch: string;
  skillsPage: number;
  skillsLoading: boolean;
  setSkillSearch: (value: string) => void;
  setSkillsPage: (page: number) => void;
  fetchSkills: () => Promise<void>;
  onDeleteSkill: (skillName: string) => void;   // App.tsx 处理 modal
}

const SkillsPanel: React.FC<SkillsPanelProps> = ({
  skillsData,
  filteredSkills,
  skillSearch,
  skillsPage,
  skillsLoading,
  setSkillSearch,
  setSkillsPage,
  fetchSkills,
  onDeleteSkill,
}) => {
  const { t } = useLocale();
  const itemsPerPage = 10;
  const totalSkillsPages = Math.ceil(filteredSkills.length / itemsPerPage);
  const paginatedSkills = filteredSkills.slice(
    (skillsPage - 1) * itemsPerPage,
    skillsPage * itemsPerPage
  );

  return (
    <div className="bg-slate-900/90 backdrop-blur-xl border border-slate-700 rounded-3xl p-8">
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-4">
          <Settings className="w-9 h-9 text-amber-400" />
          <div>
            <h2 className="text-3xl font-bold">{t('console.skills.title')}</h2>
            <p className="text-slate-400">
              {t('console.skills.subtitle', { count: skillsData.length })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button 
            onClick={fetchSkills}
            className="flex items-center gap-2 px-5 py-2 bg-slate-800 hover:bg-slate-700 rounded-2xl text-sm"
          >
            <RefreshCw className="w-4 h-4" /> {t('console.skills.refreshList')}
          </button>
          <div className="relative w-80">
            <Search className="absolute left-4 top-3.5 text-slate-400" />
            <input
              type="text"
              placeholder={t('console.skills.searchPlaceholder')}
              value={skillSearch}
              onChange={(e) => setSkillSearch(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-2xl pl-11 py-3 text-sm focus:outline-none focus:border-amber-500"
            />
          </div>
        </div>
      </div>

      {/* 骨架屏 */}
      {skillsLoading && (
        <div className="space-y-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="bg-slate-800/50 animate-pulse h-24 rounded-2xl"></div>
          ))}
        </div>
      )}

      {/* 数据列表 */}
      {!skillsLoading && filteredSkills.length > 0 ? (
        <>
          <div className="space-y-4">
            {paginatedSkills.map((skill) => (
              <div key={skill.name} className="flex items-center justify-between bg-black/30 border border-slate-700 hover:border-amber-400/50 p-6 rounded-2xl transition-all group">
                <div className="flex items-center gap-5">
                  <PlayCircle className="w-6 h-6 text-emerald-400" />
                  <div>
                    <div className="font-mono text-lg text-white truncate max-w-md" title={skill.name}>{skill.name}</div>
                    <div className="text-xs text-slate-400">{t('console.skills.usageLine', { usage: skill.usage, last: skill.last_used })}</div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <span className={`px-5 py-1.5 rounded-full text-xs ${skill.status === 'active' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-500/20 text-slate-400'}`}>
                    {skill.status === 'active' ? t('console.skills.statusActive') : t('console.skills.statusIdle')}
                  </span>

                  <button 
                    onClick={() => alert(t('console.skills.viewSourceAlert', { name: skill.name }))}
                    className="p-3 hover:bg-slate-800 rounded-xl"
                  >
                    <Eye className="w-5 h-5" />
                  </button>
                  <button 
                    onClick={() => onDeleteSkill(skill.name)} 
                    className="p-3 hover:bg-red-900/30 text-red-400 rounded-xl"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* 分页控件 */}
          {totalSkillsPages > 1 && (
            <div className="flex justify-center items-center gap-4 mt-8">
              <button
                onClick={() => setSkillsPage(Math.max(1, skillsPage - 1))}
                disabled={skillsPage === 1}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 rounded-xl flex items-center gap-2 transition"
              >
                <ChevronLeft className="w-4 h-4" />
                {t('console.skills.prev')}
              </button>
              <span className="text-slate-400 font-mono">
                {t('console.skills.page', { current: skillsPage, total: totalSkillsPages })}
              </span>
              <button
                onClick={() => setSkillsPage(Math.min(totalSkillsPages, skillsPage + 1))}
                disabled={skillsPage === totalSkillsPages}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 rounded-xl flex items-center gap-2 transition"
              >
                {t('console.skills.next')}
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </>
      ) : !skillsLoading && (
        <div className="text-center py-20 text-slate-500">{t('console.skills.noMatch')}</div>
      )}
    </div>
  );
};

export default SkillsPanel;