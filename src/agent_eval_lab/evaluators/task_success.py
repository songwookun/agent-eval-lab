"""task_success — 1축 평가: 에이전트가 task 를 "성공"했나.

설계(research 2026-06-11): ground_truth 는 두 갈래.
  checks  = 결정적 게이트(τ-bench outcome 의 경량판). 전부 통과해야 성공.
  rubric  = LLM-as-judge 품질 채점. checks 통과 후(또는 checks 없을 때) 실행.
관심사 분리: tool 호출 "행동" 정확도는 W3 tool_call evaluator 담당, 여기선 결과만.
"""

import json
import os
from typing import Any

from google import genai
from google.genai import types

from agent_eval_lab.core.types import EvalScore, Task, Trajectory
from agent_eval_lab.tools.file_ops import _WORKSPACE  # 동일 sandbox base 보장(단일 진실)


class TaskSuccessEvaluator:
    name = "task_success"
    threshold = 0.8

    def __init__(self, judge_model: str = "gemini-2.5-flash"):
        self.judge_model = judge_model
        self._client: genai.Client | None = None  # judge 필요할 때만 생성(키 없어도 checks-only 동작)

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return self._client

    def _run_check(self, check: dict[str, Any], trajectory: Trajectory) -> bool:
        """결정적 check 1개 → 통과 여부. type 별 분기."""
        ctype = check["type"]
        if ctype == "final_contains":
            return check["value"] in trajectory.final_output
        if ctype == "file_exists":
            return (_WORKSPACE / check["path"]).exists()
        if ctype == "file_contains":
            p = _WORKSPACE / check["path"]
            return p.exists() and check["value"] in p.read_text(encoding="utf-8")
        raise ValueError(f"알 수 없는 check type: {ctype}")

    async def _judge(self, rubric: str, final_output: str, prompt: str) -> tuple[float, str]:
        """LLM-as-judge: rubric 기준 0.0~1.0 채점. JSON 강제로 파싱 안정화."""
        judge_prompt = (
            "너는 엄정한 평가자다. 아래 기준으로 에이전트 답변을 0.0~1.0 으로 채점해라.\n"
            f"[평가 기준]\n{rubric}\n\n"
            f"[원래 질문]\n{prompt}\n\n"
            f"[에이전트 답변]\n{final_output}\n\n"
            'JSON 으로만 답해라: {"score": <0.0~1.0 실수>, "reason": "<한 문장 근거>"}'
        )
        response = await self._get_client().aio.models.generate_content(
            model=self.judge_model,
            contents=judge_prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",  # 모델이 순수 JSON 만 뱉도록 강제
            ),
        )
        data = json.loads(response.text)
        score = max(0.0, min(1.0, float(data["score"])))  # 범위 clamp(모델이 1.5 같은 거 줄 수 있음)
        return score, str(data.get("reason", ""))

    async def score(self, trajectory: Trajectory, task: Task) -> EvalScore:
        gt = task.ground_truth
        checks = gt.get("checks", [])
        rubric = gt.get("rubric")
        sub_scores: dict[str, float] = {}

        # agent 루프 자체가 죽었으면 평가 의미 없음 → 즉시 0
        if trajectory.error:
            return EvalScore(
                task_id=task.id, metric=self.name, score=0.0, passed=False,
                reason=f"agent 실행 실패: {trajectory.error}",
            )

        reasons: list[str] = []

        # 1) 결정적 게이트 — 하나라도 실패하면 judge 까지 안 가고 그 비율을 점수로
        if checks:
            results = [self._run_check(c, trajectory) for c in checks]
            det = sum(results) / len(results)
            sub_scores["deterministic"] = det
            if det < 1.0:
                failed = [c for c, ok in zip(checks, results) if not ok]
                return EvalScore(
                    task_id=task.id, metric=self.name, score=det, passed=False,
                    sub_scores=sub_scores, reason=f"결정적 체크 실패: {failed}",
                )
            reasons.append(f"결정적 체크 {len(checks)}개 전부 통과")

        # 2) 품질 채점 — rubric 있으면 judge 가 최종 점수, 없으면 게이트 결과(1.0)
        if rubric:
            try:
                jscore, jreason = await self._judge(rubric, trajectory.final_output, task.prompt)
            except Exception as e:  # judge 자체가 깨져도(429 등) evaluator 는 예외를 안 던진다
                return EvalScore(
                    task_id=task.id, metric=self.name, score=0.0, passed=False,
                    sub_scores=sub_scores, reason=f"judge 호출 실패: {e}",
                )
            sub_scores["judge"] = jscore
            reasons.append(f"judge={jscore:.2f}: {jreason}")
            final = jscore
        elif checks:
            final = sub_scores["deterministic"]  # = 1.0
        else:
            final = 1.0  # 검증 기준이 없고 에러도 없음 → 통과 처리
            reasons.append("검증 기준(checks/rubric) 없음 — error 없어 통과 처리")

        return EvalScore(
            task_id=task.id, metric=self.name, score=final,
            passed=final >= self.threshold, sub_scores=sub_scores,
            reason="; ".join(reasons),
        )
