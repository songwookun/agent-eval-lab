"""trajectory — 3축 평가: 에이전트가 "낭비 없이" 풀었나 (경로 효율 축).

설계(research 2026-06-14): ratio 효율 = min(1.0, optimal/actual).
  actual  = ToolStep 수 (expected_min_steps 의 의미 = "최적 도구 호출 수").
  optimal = task.expected_min_steps.
  과(過)-step 만 페널티, 부족-step 은 1.0(적게 쓰고 풀면 효율적 — 실패는 다른 축이 잡음).
관심사 분리: 결과는 task_success, 도구 종류는 tool_call, 여기선 *횟수* 군더더기만.
Reference-trajectory 매칭(golden step 시퀀스)은 저작 비용 커서 W-next 보류.
"""

from agent_eval_lab.core.types import EvalScore, LLMStep, Task, ToolStep, Trajectory


class TrajectoryEvaluator:
    name = "trajectory_efficiency"
    threshold = 0.7  # 약간의 군더더기 허용, 2배 이상 루프(≤0.5)는 탈락(tool_call 1.0 과 대비)

    async def score(self, trajectory: Trajectory, task: Task) -> EvalScore:
        # agent 루프 자체가 죽었으면 효율 논할 의미 없음 → 0 (3개 evaluator 일관 가드)
        if trajectory.error:
            return EvalScore(
                task_id=task.id, metric=self.name, score=0.0, passed=False,
                reason=f"agent 실행 실패: {trajectory.error}",
            )

        actual = sum(1 for s in trajectory.steps if isinstance(s, ToolStep))
        llm_steps = sum(1 for s in trajectory.steps if isinstance(s, LLMStep))
        optimal = task.expected_min_steps

        if actual == 0:
            efficiency = 1.0  # 도구 미사용 = 낭비 0 (실패라서 0이면 task_success/tool_call 이 0점)
        else:
            efficiency = min(1.0, optimal / actual)  # 과-step 만 페널티, 부족-step 은 cap 1.0

        redundant = max(0, actual - optimal)
        return EvalScore(
            task_id=task.id, metric=self.name, score=efficiency,
            passed=efficiency >= self.threshold,
            sub_scores={"efficiency": efficiency},
            details={
                "optimal": optimal, "actual_tool_steps": actual,
                "llm_steps": llm_steps, "redundant": redundant,
            },
            reason=f"optimal={optimal} actual={actual} redundant={redundant} → {efficiency:.2f}",
        )
