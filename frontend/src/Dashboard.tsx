import React from 'react';
import {
  Zap, Clock, Cpu, PlayCircle, TrendingUp, AlertCircle,
  MessageSquare
} from 'lucide-react';

import { useLocale } from './i18n/useLocale';

interface DashboardData {
  status: string;
  dynamic_skills: number;
  reboot_count: number;
  memory_summary: string;
  proprioception: string;
  uptime: string;
  active_workflows?: number;
  active_workflow_list?: any[];
}

interface EventLog {
  time: string;
  message: string;
  type: 'info' | 'success' | 'warning';
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

interface DashboardProps {
  data: DashboardData | null;
  logs: EventLog[];
  totalSkills: number;
  activeWorkflows: WorkflowItem[];
  tddScores: TDDScore[];
  reflexionLogs: ReflexionLog[];
  awakeningDeclaration: string;
}

const Dashboard: React.FC<DashboardProps> = ({
  data,
  logs,
  totalSkills,
  activeWorkflows,
  tddScores,
  reflexionLogs,
  awakeningDeclaration,
}) => {
  const { t } = useLocale();

  if (!data) {
    return <div className="text-center py-12 text-slate-400">{t('console.dashboard.loading')}</div>;
  }

  return (
    <div className="space-y-8">
      {/* 水平滚动统计卡片 */}
      <div className="flex gap-4 overflow-x-auto pb-6 snap-x snap-mandatory scrollbar-hide">
        <div className="bg-slate-900/90 backdrop-blur-xl border border-slate-700 rounded-3xl p-6 flex-shrink-0 w-60 snap-center">
          <div className="flex items-center gap-4">
            <Zap className="w-9 h-9 text-yellow-400" />
            <div>
              <div className="text-xs text-slate-400">{t('console.dashboard.dynamicSkillsLabel')}</div>
              <div className="text-4xl font-bold text-white mt-1">{totalSkills}</div>
              <div className="text-emerald-400 text-xs mt-1">{t('console.dashboard.dynamicSkillsSub', { count: totalSkills })}</div>
            </div>
          </div>
        </div>

        <div className="bg-slate-900/90 backdrop-blur-xl border border-slate-700 rounded-3xl p-6 flex-shrink-0 w-60 snap-center">
          <div className="flex items-center gap-4">
            <Clock className="w-9 h-9 text-purple-400" />
            <div>
              <div className="text-xs text-slate-400">{t('console.dashboard.rebootLabel')}</div>
              <div className="text-4xl font-bold text-white mt-1">{t('console.dashboard.rebootNumber', { count: data.reboot_count })}</div>
              <div className="text-purple-400 text-xs mt-1">{t('console.dashboard.rebootSoul')}</div>
            </div>
          </div>
        </div>

        <div className="bg-slate-900/90 backdrop-blur-xl border border-slate-700 rounded-3xl p-6 flex-shrink-0 w-60 snap-center">
          <div className="flex items-center gap-4">
            <Cpu className="w-9 h-9 text-cyan-400" />
            <div>
              <div className="text-xs text-slate-400">{t('console.dashboard.proprioceptionLabel')}</div>
              <div className="text-4xl font-bold text-white mt-1">{data.proprioception}</div>
              <div className="text-cyan-400 text-xs mt-1">{t('console.dashboard.proprioceptionHint')}</div>
            </div>
          </div>
        </div>

        <div className="bg-slate-900/90 backdrop-blur-xl border border-violet-400 rounded-3xl p-6 flex-shrink-0 w-60 snap-center">
          <div className="flex items-center gap-4">
            <PlayCircle className="w-9 h-9 text-violet-400" />
            <div>
              <div className="text-xs text-slate-400">{t('console.dashboard.activeWfLabel')}</div>
              <div className="text-4xl font-bold text-white mt-1">{activeWorkflows.length}</div>
              <div className="text-violet-400 text-xs mt-1">{t('console.dashboard.activeWfSub')}</div>
            </div>
          </div>
        </div>

        <div className="bg-slate-900/90 backdrop-blur-xl border border-emerald-400 rounded-3xl p-6 flex-shrink-0 w-60 snap-center">
          <div className="flex items-center gap-4">
            <TrendingUp className="w-9 h-9 text-emerald-400" />
            <div>
              <div className="text-xs text-slate-400">{t('console.dashboard.tddAvgLabel')}</div>
              <div className="text-4xl font-bold text-emerald-400 mt-1">
                {tddScores.length ? Math.round(tddScores.reduce((a, b) => a + b.score, 0) / tddScores.length * 100) : 0}%
              </div>
              <div className="text-emerald-400 text-xs mt-1">{t('console.dashboard.tddSkillsCount', { count: tddScores.length })}</div>
            </div>
          </div>
        </div>
      </div>

      {/* 苏醒宣言 */}
      <div className="bg-slate-900/90 backdrop-blur-xl border border-purple-500/30 rounded-3xl p-8">
        <div className="flex items-center gap-3 mb-4">
          <span className="text-purple-400">🌌</span>
          <div className="text-lg font-semibold">{t('console.dashboard.awakeningTitle', { count: data.reboot_count })}</div>
        </div>
        <p className="text-slate-300 italic text-base leading-relaxed">
          {awakeningDeclaration || t('console.dashboard.awakeningEmpty')}
        </p>
      </div>

      {/* TDD 技能得分卡 */}
      <div className="bg-slate-900/90 backdrop-blur-xl border border-emerald-500/30 rounded-3xl p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <TrendingUp className="w-6 h-6 text-emerald-400" />
            <span className="text-xl font-semibold">{t('console.dashboard.tddCardTitle')}</span>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {tddScores.slice(0, 8).map((item) => (
            <div key={item.skill_name} className="bg-black/40 border border-emerald-400/30 rounded-2xl p-5 hover:border-emerald-400 transition-all">
              <div className="text-emerald-400 text-sm font-medium">{item.skill_name}</div>
              <div className="mt-3 flex items-baseline">
                <span className="text-4xl font-bold">{Math.round(item.score * 100)}</span>
                <span className="text-emerald-400 text-xl ml-1">{t('console.dashboard.tddScoreUnit')}</span>
              </div>
              <div className="text-xs text-slate-400 mt-1 flex justify-between">
                <span>{t('console.dashboard.tddPassRate', { p: Math.round(item.pass_rate * 100) })}</span>
                <span>{t('console.dashboard.tddExecLine', { time: item.execution_time.toFixed(1), mem: item.peak_memory_mb.toFixed(0) })}</span>
              </div>
            </div>
          ))}
        </div>
        {tddScores.length === 0 && <p className="text-slate-400 text-center py-12">{t('console.dashboard.tddEmpty')}</p>}
      </div>

      {/* Reflexion 日志面板 */}
      <div className="bg-slate-900/90 backdrop-blur-xl border border-purple-500/30 rounded-3xl p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-6 h-6 text-purple-400" />
            <span className="text-xl font-semibold">{t('console.dashboard.reflexionTitle')}</span>
          </div>
        </div>
        <div className="space-y-4 max-h-80 overflow-auto">
          {reflexionLogs.slice(0, 6).map((log, i) => (
            <div key={i} className="bg-black/30 border border-purple-400/30 rounded-2xl p-5 flex gap-4">
              <div className="text-purple-400 font-mono text-xs w-20 shrink-0">{log.workflow_id}</div>
              <div className="flex-1">
                <div className="text-purple-300 text-sm"><strong>{t('console.dashboard.rootCause')}</strong>{log.root_cause}</div>
                <div className="text-slate-300 text-sm mt-1"><strong>{t('console.dashboard.suggestedAction')}</strong>{log.suggested_action}</div>
              </div>
              <div className="text-right">
                <div className="text-xs bg-purple-500/20 text-purple-300 px-3 py-1 rounded-full">{t('console.dashboard.confidencePct', { p: Math.round(log.confidence * 100) })}</div>
                <div className="text-xs text-slate-400 mt-4">{new Date(log.timestamp).toLocaleTimeString()}</div>
              </div>
            </div>
          ))}
          {reflexionLogs.length === 0 && <p className="text-slate-400 text-center py-12">{t('console.dashboard.reflexionEmpty')}</p>}
        </div>
      </div>

      {/* 活跃工作流列表 */}
      <div className="bg-slate-900/90 backdrop-blur-xl border border-slate-700 rounded-3xl p-6">
        <div className="flex items-center gap-3 mb-6">
          <PlayCircle className="w-6 h-6 text-violet-400" />
          <span className="text-xl font-semibold">{t('console.dashboard.activeWfSectionTitle')}</span>
        </div>
        {activeWorkflows.length > 0 ? (
          <div className="space-y-3 max-h-96 overflow-auto">
            {activeWorkflows.slice(0, 10).map((wf) => (
              <div key={wf.workflow_id} className="flex justify-between items-center bg-black/30 border border-violet-400/30 p-4 rounded-2xl">
                <div>
                  <span className="font-mono text-violet-300">{wf.workflow_id}</span>
                  <span className="ml-3 text-xs text-slate-400">{t('console.dashboard.wfStep', { n: wf.global_step_count })}</span>
                </div>
                <div className={`px-4 py-1 text-xs font-medium rounded-full ${
                  wf.status === 'RUNNING' ? 'bg-emerald-500/20 text-emerald-400' : 
                  wf.status === 'PAUSED' ? 'bg-amber-500/20 text-amber-400' : 'bg-slate-500/20 text-slate-400'
                }`}>
                  {wf.status}
                </div>
              </div>
            ))}
            {activeWorkflows.length > 10 && (
              <div className="text-center text-xs text-slate-400 py-3">
                {t('console.dashboard.wfShowFirst', { shown: 10, total: activeWorkflows.length })}
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-12 text-slate-400">{t('console.dashboard.workflowEmpty')}</div>
        )}
      </div>

      {/* 实时事件流 */}
      <div className="bg-slate-900/90 backdrop-blur-xl border border-slate-700 rounded-3xl p-6">
        <div className="flex items-center gap-3 mb-6">
          <MessageSquare className="w-6 h-6 text-blue-400" />
          <span className="text-xl font-semibold">{t('console.dashboard.eventStreamTitle')}</span>
        </div>
        <div className="h-64 overflow-y-auto font-mono text-sm bg-black/40 p-5 rounded-2xl space-y-2">
          {logs.length === 0 ? (
            <div className="text-slate-500 text-center py-10">{t('console.dashboard.eventStreamWaiting')}</div>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="flex gap-4 text-xs">
                <span className="text-slate-500 shrink-0 w-20">{log.time}</span>
                <span className={
                  log.type === 'success' ? 'text-emerald-400' : 
                  log.type === 'warning' ? 'text-orange-400' : 'text-slate-300'
                }>
                  {log.message}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;