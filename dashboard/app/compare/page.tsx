import Link from "next/link";
import { compareBySuite, type CompareRow } from "@/lib/api";

export const dynamic = "force-dynamic";

const AXES = ["task_success", "tool_call", "trajectory_efficiency", "cost"];
const AXIS_LABEL: Record<string, string> = {
  task_success: "Task 성공률",
  tool_call: "Tool-call 정확도",
  trajectory_efficiency: "Trajectory 효율",
  cost: "비용·지연",
};

function agentColor(id: string | null) {
  if (id?.includes("gemini")) return { bar: "bg-blue-500", text: "text-blue-300" };
  if (id?.includes("groq")) return { bar: "bg-orange-500", text: "text-orange-300" };
  return { bar: "bg-zinc-500", text: "text-zinc-300" };
}

export default async function ComparePage() {
  const suiteId = "suite_v1";
  let rows: CompareRow[] = [];
  let error: string | null = null;
  try {
    rows = await compareBySuite(suiteId);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <Link href="/" className="text-sm text-emerald-400 hover:underline">← 목록</Link>
      <h1 className="mt-4 text-2xl font-bold">모델 비교</h1>
      <p className="mt-1 text-sm text-zinc-400">
        suite <span className="text-zinc-200">{suiteId}</span> — agent별 최신 run 의 4축 점수
      </p>

      {error && (
        <div className="mt-6 rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          API 연결 실패: {error}
        </div>
      )}

      {!error && rows.length < 1 && (
        <p className="mt-6 text-zinc-400">비교할 run 이 없습니다.</p>
      )}

      {rows.length > 0 && (
        <>
          {/* 범례 */}
          <div className="mt-6 flex flex-wrap gap-4 text-sm">
            {rows.map((r) => {
              const c = agentColor(r.agent_id);
              return (
                <div key={r.run_id} className="flex items-center gap-2">
                  <span className={`h-3 w-3 rounded-sm ${c.bar}`} />
                  <span className={c.text}>{r.agent_id}</span>
                  <span className="text-zinc-500">({r.model})</span>
                </div>
              );
            })}
          </div>

          {/* 축별 그룹 바 차트 */}
          <div className="mt-8 space-y-8">
            {AXES.map((axis) => (
              <section key={axis}>
                <h2 className="text-sm font-semibold text-zinc-300">
                  {AXIS_LABEL[axis] ?? axis}{" "}
                  <span className="font-normal text-zinc-500">({axis})</span>
                </h2>
                <div className="mt-3 space-y-2.5">
                  {rows.map((r) => {
                    const v = r.axes[axis] ?? 0;
                    const c = agentColor(r.agent_id);
                    return (
                      <div key={r.run_id} className="flex items-center gap-3">
                        <span className={`w-32 shrink-0 text-right text-xs ${c.text}`}>
                          {r.agent_id?.replace("-agent-v1", "")}
                        </span>
                        <div className="h-6 flex-1 overflow-hidden rounded bg-zinc-800">
                          <div
                            className={`flex h-full items-center justify-end rounded px-2 ${c.bar}`}
                            style={{ width: `${Math.max(v * 100, 6)}%` }}
                          >
                            <span className="text-xs font-semibold text-white tabular-nums">
                              {(v * 100).toFixed(0)}%
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
