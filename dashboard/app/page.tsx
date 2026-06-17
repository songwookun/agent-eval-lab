import Link from "next/link";
import { listRuns, type RunSummary } from "@/lib/api";

export const dynamic = "force-dynamic"; // 항상 최신 데이터(빌드 시 prerender X)

function pct(n: number | null) {
  return n == null ? "—" : `${(n * 100).toFixed(1)}%`;
}

function AgentBadge({ id }: { id: string | null }) {
  const isGemini = id?.includes("gemini");
  const color = isGemini ? "bg-blue-500/20 text-blue-300" : "bg-orange-500/20 text-orange-300";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${color}`}>{id ?? "?"}</span>;
}

export default async function Home() {
  let runs: RunSummary[] = [];
  let error: string | null = null;
  try {
    runs = await listRuns(50);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl font-bold">agent-eval-lab</h1>
      <p className="mt-1 text-sm text-zinc-400">평가 run 목록 — 4축 점수 · 모델 교차비교</p>

      {error && (
        <div className="mt-6 rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          API 연결 실패: {error}
          <div className="mt-1 text-zinc-400">
            FastAPI 서버를 먼저 띄우세요: <code className="text-zinc-200">uv run agent-eval-lab serve</code>
          </div>
        </div>
      )}

      {!error && runs.length === 0 && (
        <p className="mt-6 text-zinc-400">
          저장된 run 이 없습니다. <code>agent-eval-lab run</code> 으로 평가를 돌리세요.
        </p>
      )}

      {runs.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-zinc-800">
          <table className="w-full border-collapse text-[15px]">
            <thead className="bg-zinc-900/60 text-left text-xs uppercase tracking-wider text-zinc-500">
              <tr className="border-b border-zinc-700">
                <th className="px-6 py-5 font-medium">RUN</th>
                <th className="px-6 py-5 font-medium">AGENT</th>
                <th className="px-6 py-5 font-medium">SUITE</th>
                <th className="px-6 py-5 text-right font-medium">평균</th>
                <th className="px-6 py-5 text-right font-medium">통과</th>
                <th className="px-6 py-5 text-right font-medium">시각</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className="border-b border-zinc-800 last:border-0 hover:bg-zinc-800/50">
                  <td className="whitespace-nowrap px-6 py-5">
                    <Link href={`/runs/${r.run_id}`} className="font-mono text-emerald-400 hover:underline">
                      {r.run_id.slice(0, 12)}
                    </Link>
                  </td>
                  <td className="whitespace-nowrap px-6 py-5">
                    <AgentBadge id={r.agent_id} />
                  </td>
                  <td className="whitespace-nowrap px-6 py-5 text-zinc-300">{r.suite_id}</td>
                  <td className="whitespace-nowrap px-6 py-5 text-right font-medium tabular-nums">
                    {pct(r.avg_score)}
                  </td>
                  <td className="whitespace-nowrap px-6 py-5 text-right text-zinc-300 tabular-nums">
                    {r.n_passed ?? 0}/{r.n_scores}
                  </td>
                  <td className="whitespace-nowrap px-6 py-5 text-right text-zinc-500 tabular-nums">
                    {r.started_at.slice(0, 19).replace("T", " ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
