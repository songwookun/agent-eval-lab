import Link from "next/link";
import { getRun, type RunDetail, type ScoreOut } from "@/lib/api";

export const dynamic = "force-dynamic";

const AXIS_ORDER = ["task_success", "tool_call", "trajectory_efficiency", "cost"];

function groupByMetric(scores: ScoreOut[]): Record<string, ScoreOut[]> {
  const m: Record<string, ScoreOut[]> = {};
  for (const s of scores) (m[s.metric] ??= []).push(s);
  return m;
}

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params; // Next 16: params 는 Promise → await 필수

  let run: RunDetail | null = null;
  let error: string | null = null;
  try {
    run = await getRun(runId);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error || !run) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <Link href="/" className="text-sm text-emerald-400 hover:underline">← 목록</Link>
        <div className="mt-6 rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          run 조회 실패: {error ?? "없음"}
        </div>
      </main>
    );
  }

  const byMetric = groupByMetric(run.scores);
  const metrics = [
    ...AXIS_ORDER.filter((m) => m in byMetric),
    ...Object.keys(byMetric).filter((m) => !AXIS_ORDER.includes(m)),
  ];

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <Link href="/" className="text-sm text-emerald-400 hover:underline">← 목록</Link>

      <h1 className="mt-4 font-mono text-xl font-bold">{run.run_id.slice(0, 16)}</h1>
      <p className="mt-1 text-sm text-zinc-400">
        suite <span className="text-zinc-200">{run.suite_id}</span> · model{" "}
        <span className="text-zinc-200">{String(run.config.model ?? "?")}</span> · agent{" "}
        <span className="text-zinc-200">{run.agent_id ?? "?"}</span>
      </p>

      {/* 축별 요약 카드 */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {metrics.map((m) => {
          const rows = byMetric[m];
          const avg = rows.reduce((a, r) => a + r.score, 0) / rows.length;
          const passed = rows.filter((r) => r.passed).length;
          return (
            <div key={m} className="rounded-lg border border-zinc-700 bg-zinc-800/40 p-3">
              <div className="text-xs text-zinc-400">{m}</div>
              <div className="mt-1 text-2xl font-bold">{(avg * 100).toFixed(0)}%</div>
              <div className="text-xs text-zinc-500">{passed}/{rows.length} 통과</div>
            </div>
          );
        })}
      </div>

      {/* 축별 task 점수 상세 */}
      {metrics.map((m) => (
        <section key={m} className="mt-8">
          <h2 className="text-sm font-semibold text-zinc-300">{m}</h2>
          <div className="mt-2 overflow-x-auto rounded-lg border border-zinc-800">
            <table className="w-full border-collapse text-[15px]">
              <tbody>
                {byMetric[m].map((s) => (
                  <tr key={`${m}-${s.task_id}`} className="border-b border-zinc-800 last:border-0">
                    <td className="whitespace-nowrap px-6 py-3.5 font-mono text-zinc-400">{s.task_id}</td>
                    <td className="w-16 px-6 py-3.5 text-right font-medium tabular-nums">{s.score.toFixed(2)}</td>
                    <td className="w-10 px-3 py-3.5 text-center">{s.passed ? "✅" : "❌"}</td>
                    <td className="px-6 py-3.5 text-zinc-500">{s.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </main>
  );
}
