import { Download, Star, Github } from 'lucide-react';

import { useLocale } from './i18n/useLocale';

interface SkillItem {
  name: string;
  type: 'dynamic' | 'instinct';
  status?: string;
  source: string;
  installed_at?: string;
  repo_url?: string;
  stars?: number;
  score?: number;
  description?: string;
  confidence?: number;
  reason?: string;
  error?: string;
}

interface SkillCardProps {
  skill: SkillItem;
  onInstall: (skillName: string, repoUrl?: string) => void;
  installing?: string | null;
  installedNames?: Set<string>;   // 全局已安装检测
}

const SkillCard = ({ skill, onInstall, installing, installedNames = new Set() }: SkillCardProps) => {
  const { t } = useLocale();
  const isInstalling = installing === skill.name;
  const isInstalled =
    installedNames.has(skill.name.toUpperCase()) ||
    skill.status?.toLowerCase() === 'active' ||
    skill.status === 'permanent';

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-3xl p-8 hover:border-violet-400 transition-all group">
      <div className="flex justify-between items-start mb-6">
        <div className="flex-1 min-w-0">
          <div className="text-2xl font-mono font-bold text-white tracking-tight truncate" title={skill.name}>
            {skill.name}
          </div>
          
          <div className="flex items-center gap-3 mt-3">
            <span className={`px-4 py-1 text-xs font-medium rounded-full ${
              skill.type === 'instinct' 
                ? 'bg-purple-900/80 text-purple-300' 
                : 'bg-emerald-900/80 text-emerald-300'
            }`}>
              {skill.type === 'instinct' ? t('console.skillCard.typeInstinct') : t('console.skillCard.typeDynamic')}
            </span>
            
            {skill.stars && (
              <span className="flex items-center gap-1 text-amber-400 text-sm">
                <Star className="w-4 h-4" /> {skill.stars}
              </span>
            )}
            
            {skill.repo_url && (
              <span className="flex items-center gap-1 text-amber-400 text-xs">
                <Github className="w-4 h-4" /> GitHub
              </span>
            )}
          </div>
        </div>

        <div className={`px-5 py-1 text-xs font-medium rounded-full ${
          isInstalled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-violet-500/20 text-violet-400'
        }`}>
          {isInstalled ? t('console.skillCard.badgeInstalled') : t('console.skillCard.badgeRecommend')}
        </div>
      </div>

      {(skill.description || skill.reason) && (
        <p className="text-slate-400 text-sm line-clamp-3 mb-8">
          {skill.reason || skill.description}
        </p>
      )}
      {skill.error && (
        <p className="text-amber-300 text-xs mb-6">
          {skill.error}
        </p>
      )}

      <button
        onClick={() => !isInstalled && onInstall(skill.name, skill.repo_url)}
        disabled={isInstalling || isInstalled || !!skill.error}
        className={`w-full py-4 rounded-2xl font-medium transition flex items-center justify-center gap-3 ${
          isInstalled 
            ? 'bg-emerald-600/30 text-emerald-400 cursor-not-allowed' 
            : 'bg-violet-600 hover:bg-violet-500 disabled:bg-slate-700'
        }`}
      >
        {isInstalling ? (
          <>
            <div className="w-4 h-4 border-2 border-white/30 border-t-white animate-spin rounded-full" />
            {t('console.skillCard.installing')}
          </>
        ) : isInstalled ? (
          <>
            ✅ {t('console.skillCard.installed')}
          </>
        ) : (
          <>
            <Download className="w-5 h-5" />
            {t('console.skillCard.installMelt')}
          </>
        )}
      </button>
    </div>
  );
};

export default SkillCard;