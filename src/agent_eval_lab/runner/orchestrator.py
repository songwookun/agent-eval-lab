"""Runner — suite 전체를 돌려 RunResult 한 묶음으로 조립.

흐름(code_design 5절): task 마다 agent.run → 각 evaluator.score → 누적 → RunResult.
async: agent.run / evaluator.score 가 모두 async(LLM 호출) 이므로 await 체인.
RunConfig 는 재현성 snapshot — 모델/온도/프롬프트해시/버전/git_sha 를 박제한다.
"""

import hashlib
import os
import uuid
from datetime import datetime, timezone

from agent_eval_lab.core.protocols import Agent, Evaluator, Tool
from agent_eval_lab.core.types import (
    EvalScore, RunConfig, RunResult, Task, Trajectory,
)

# RunConfig.env 에 담을 환경변수 whitelist — 비밀키는 절대 포함 금지(STUDY 재현성 철학).
_ENV_WHITELIST = ("GEMINI_MODEL",)


class Runner:
    def __init__(
        self,
        agent: Agent,
        evaluators: list[Evaluator],
        tools: list[Tool],
        suite: list[Task],
        suite_id: str,
        suite_version: str,
        git_sha: str | None = None,
    ):
        self.agent = agent
        self.evaluators = evaluators
        self.tools = tools
        self.suite = suite
        self.suite_id = suite_id
        self.suite_version = suite_version
        self.git_sha = git_sha

    def _build_config(self) -> RunConfig:
        """agent 속성에서 재현성 snapshot 을 뜬다. 비밀 제외, whitelist env 만."""
        # 일부 속성은 Agent Protocol 의 계약이 아님(GeminiAgent 구현 디테일) → getattr 로 안전 접근.
        sys_prompt = getattr(self.agent, "system_prompt", "")
        return RunConfig(
            model=getattr(self.agent, "model", "unknown"),
            temperature=getattr(self.agent, "temperature", 0.0),
            max_steps=getattr(self.agent, "max_steps", 0),
            system_prompt_hash=hashlib.sha256(sys_prompt.encode("utf-8")).hexdigest(),
            agent_version=self.agent.agent_id,
            suite_version=self.suite_version,
            git_sha=self.git_sha,
            env={k: os.environ[k] for k in _ENV_WHITELIST if k in os.environ},
        )

    async def run_all(self) -> RunResult:
        """suite 의 모든 task 를 순차 실행(span 트리 가독성 우선) → RunResult."""
        started_at = datetime.now(timezone.utc)
        trajectories: list[Trajectory] = []
        scores: list[EvalScore] = []
        for task in self.suite:
            tr = await self.agent.run(task, self.tools)
            trajectories.append(tr)
            for ev in self.evaluators:
                try:
                    scores.append(await ev.score(tr, task))
                except Exception as e:  # 한 evaluator/​task 실패가 전체 run 을 죽이지 않게(이중 안전망)
                    scores.append(EvalScore(
                        task_id=task.id, metric=getattr(ev, "name", "unknown"),
                        score=0.0, passed=False, reason=f"evaluator 실패: {e}",
                    ))
        ended_at = datetime.now(timezone.utc)
        return RunResult(
            run_id=uuid.uuid4().hex,
            agent_id=self.agent.agent_id,
            suite_id=self.suite_id,
            config=self._build_config(),
            trajectories=trajectories,
            scores=scores,
            started_at=started_at,
            ended_at=ended_at,
        )
