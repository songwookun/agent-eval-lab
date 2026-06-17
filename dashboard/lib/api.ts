// FastAPI 조회 API 클라이언트 — 타입 + fetch 래퍼.
// server component 에서 호출(노드→로컬 API, CORS 무관). dev 라 항상 최신(no-store).

const API_BASE = process.env.API_BASE ?? "http://127.0.0.1:8000";

export type RunSummary = {
  run_id: string;
  agent_id: string | null;
  suite_id: string;
  model: string | null;
  started_at: string;
  n_scores: number;
  avg_score: number | null;
  n_passed: number | null;
};

export type ScoreOut = {
  task_id: string;
  metric: string;
  score: number;
  sub_scores: Record<string, number>;
  passed: boolean;
  reason: string | null;
  details: Record<string, unknown>;
};

export type RunDetail = {
  run_id: string;
  agent_id: string | null;
  suite_id: string;
  config: Record<string, unknown>;
  scores: ScoreOut[];
  started_at: string;
  ended_at: string | null;
};

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export const listRuns = (limit = 20) => getJSON<RunSummary[]>(`/runs?limit=${limit}`);
export const getRun = (runId: string) => getJSON<RunDetail>(`/runs/${runId}`);
