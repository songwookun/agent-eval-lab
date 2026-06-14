"""tool_call — 2축 평가: 에이전트가 "올바른 tool 을 올바르게 불렀나" (행동/action 축).

설계(research 2026-06-14, BFCL 대조):
  채점 대상 = LLMStep.tool_calls_requested (모델이 *요청*한 호출). 실행된 ToolStep 아님 —
             tool 행동(모델 책임)과 tool 실패(환경)를 격리.
  multiset(Counter) F1 = score. set 아님(combo_02 처럼 같은 tool 을 2번 부르는 경우 보존).
  expected_tools 가 비면 irrelevance 모드(안 부르는 게 정답, BFCL IrrelAcc 경량판).
관심사 분리: 결과(outcome)는 task_success 담당, 여기선 행동(action)만.
인자/순서 매칭은 ground_truth 옵션 필드로 phase(v1 미구현, 데이터는 args 까지 보존됨).
"""

from collections import Counter

from agent_eval_lab.core.types import EvalScore, LLMStep, Task, Trajectory


class ToolCallEvaluator:
    name = "tool_call"
    threshold = 1.0  # tool 행동은 엄격 — 정확히 맞아야 통과(task_success 0.8 과 대비)

    @staticmethod
    def _extract_actual_tool_names(trajectory: Trajectory) -> list[str]:
        """LLMStep 들이 *요청*한 tool 이름을 시간순 flatten. 중복 보존(multiset 용)."""
        names: list[str] = []
        for step in trajectory.steps:
            if isinstance(step, LLMStep):  # ToolStep 제외 — 모델 행동만 본다
                names.extend(call["name"] for call in step.tool_calls_requested)
        return names

    async def score(self, trajectory: Trajectory, task: Task) -> EvalScore:
        # agent 루프 자체가 죽었으면 채점 의미 없음 → 즉시 0 (task_success 와 동일 가드)
        if trajectory.error:
            return EvalScore(
                task_id=task.id, metric=self.name, score=0.0, passed=False,
                reason=f"agent 실행 실패: {trajectory.error}",
            )

        actual = Counter(self._extract_actual_tool_names(trajectory))
        expected = Counter(task.expected_tools)

        # irrelevance 모드 — tool 이 불필요(expected 비었음): 안 부르면 1.0, 부르면 환각 0.0
        if not expected:
            called = sum(actual.values())
            score = 1.0 if called == 0 else 0.0
            return EvalScore(
                task_id=task.id, metric=self.name, score=score, passed=score == 1.0,
                sub_scores={"irrelevance": score},
                reason="tool 불필요 — abstain 성공" if score else f"불필요한데 {called}개 호출",
            )

        # multiset F1 — precision(헛호출 페널티) + recall(누락 페널티)
        matched = sum((actual & expected).values())  # Counter 교집합 = min(count) 합
        precision = matched / sum(actual.values()) if actual else 0.0
        recall = matched / sum(expected.values())  # expected 는 여기서 항상 ≥1
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        return EvalScore(
            task_id=task.id, metric=self.name, score=f1, passed=f1 >= self.threshold,
            sub_scores={"precision": precision, "recall": recall, "f1": f1},
            reason=(
                f"expected={dict(expected)} actual={dict(actual)} "
                f"→ P{precision:.2f}/R{recall:.2f}/F1{f1:.2f}"
            ),
        )
