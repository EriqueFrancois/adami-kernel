export const API_BASE_URL = 'http://localhost:8000';

export const WS_EVENTS_URL = API_BASE_URL.replace(/^http/, 'ws') + '/ws/events';

export const apiRoutes = {
  dashboard: () => `${API_BASE_URL}/dashboard`,
  skills: () => `${API_BASE_URL}/api/skills`,
  activeWorkflows: () => `${API_BASE_URL}/api/workflows/active`,
  memory: (search: string) => `${API_BASE_URL}/api/memory?search=${encodeURIComponent(search)}`,
  tddScores: () => `${API_BASE_URL}/api/tdd_scores`,
  reflexionLogs: () => `${API_BASE_URL}/api/reflexion_logs`,

  marketSkills: () => `${API_BASE_URL}/market/skills`,
  marketRecommend: () => `${API_BASE_URL}/market/recommend`,
  marketSearch: (q: string) => `${API_BASE_URL}/market/search?q=${encodeURIComponent(q)}`,
  marketInstall: () => `${API_BASE_URL}/market/install`,
  marketUpload: () => `${API_BASE_URL}/market/upload`,
} as const;

