"""cost — 4축 평가: 비용·지연이 task 예산 안에 들었나 (Latency·비용 축).

설계(research 2026-06-14, A안 예산 게이트): observability(token/$/latency 기록) +
  예산 판정. score = min(1.0, cost_budget/실제$, timeout/순수latency) — 빡빡한 제약이 지배.
  예산 내면 1.0(cap), 초과하면 <1.0 → runaway loop/예산 초과를 *실제 실패*로 검출.
latency 는 LLMStep.latency_ms 합(순수 LLM 시간, 재시도 backoff 제외 — gemini_agent 가
  _generate 안에서 측정). wall-clock(backoff 포함)은 details 에만.
"""

from agent_eval_lab.core.types import EvalScore, LLMStep, Task, Trajectory


class CostEvaluator:
    name = "cost"
    threshold = 1.0  # 예산 내 필수 — score 는 cap 1.0 이라 <1.0 이면 예산 초과(fail)

    async def score(self, trajectory: Trajectory, task: Task) -> EvalScore:
        # agent 루프 자체가 죽었으면 예산 논할 의미 없음 → 0 (4개 evaluator 일관 가드)
        if trajectory.error:
            return EvalScore(
                task_id=task.id, metric=self.name, score=0.0, passed=False,
                reason=f"agent 실행 실패: {trajectory.error}",
            )

        # 순수 LLM 시간(backoff 제외) vs wall-clock(backoff 포함)
        pure_latency_ms = sum(
            s.latency_ms for s in trajectory.steps if isinstance(s, LLMStep)
        )
        wall_clock_ms = trajectory.total_latency_ms
        cost_usd = trajectory.total_cost_usd
        timeout_ms = task.timeout_s * 1000
        cost_budget = task.max_cost_usd

        # 예산 비율 — 각각 cap 1.0(예산 내), div 방어. 둘 중 빡빡한 게 score 지배.
        cost_ratio = min(1.0, cost_budget / cost_usd) if cost_usd > 0 else 1.0
        lat_ratio = min(1.0, timeout_ms / pure_latency_ms) if pure_latency_ms > 0 else 1.0
        score = min(cost_ratio, lat_ratio)
        over_budget = score < 1.0

        return EvalScore(
            task_id=task.id, metric=self.name, score=score, passed=score >= self.threshold,
            sub_scores={"cost_ratio": cost_ratio, "latency_ratio": lat_ratio},
            details={
                "total_cost_usd": cost_usd,
                "total_tokens_in": trajectory.total_tokens_in,
                "total_tokens_out": trajectory.total_tokens_out,
                "pure_latency_ms": pure_latency_ms,
                "wall_clock_ms": wall_clock_ms,
                "cost_budget_usd": cost_budget,
                "latency_budget_ms": timeout_ms,
                "over_budget": over_budget,
            },
            reason=(
                f"${cost_usd:.6f}/${cost_budget} | "
                f"{pure_latency_ms}ms/{timeout_ms}ms (wall {wall_clock_ms}ms) → {score:.2f}"
            ),
        )
