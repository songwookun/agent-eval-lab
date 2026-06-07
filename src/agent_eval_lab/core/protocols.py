"""Protocol 정의. 구현체가 이 시그니처만 맞추면 plugin 처럼 끼울 수 있다.

설계: 구조적 타이핑(Protocol) — 상속 강제 없이 외부 SDK 객체도 덕타이핑으로 수용.
      async-first (STUDY.md "Protocol 의 Sync vs Async 선택" 참고).

주의: @runtime_checkable 의 isinstance 는 *멤버 존재* 만 검사하고
      메서드 시그니처(인자/타입)는 검사하지 않는다.
      registry 등에서 isinstance 통과를 "완전한 계약 충족" 으로 과신하지 말 것.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # 타입 힌트 전용 import — 런타임엔 로드 안 됨 (순환 import 차단 + 비용 0)
    from agent_eval_lab.core.types import Task, Trajectory, EvalScore


@runtime_checkable
class Tool(Protocol):
    name: str                                       # LLM Function Calling 매칭 키
    description: str                                # LLM 이 "언제 쓸지" 판단하는 설명
    input_schema: dict                              # JSON Schema (LLM 에 전달)

    async def call(self, **kwargs) -> Any: ...      # 실제 실행 (결과 타입은 tool 마다 다름)


@runtime_checkable
class Agent(Protocol):
    agent_id: str                                   # "gemini-agent-v1" (Trajectory/RunResult 연결)

    async def run(self, task: Task, tools: list[Tool]) -> Trajectory: ...
    # tools 를 인자 주입 → 같은 agent 를 다른 tool 셋으로 비교 평가 가능.
    # 구현 계약: run 내부에서 OTel span 직접 emit (LLM step 1 + tool step n).
    #   auto-instrumentation 은 tool 호출을 안 잡으므로 직접 emit 필수.


@runtime_checkable
class Evaluator(Protocol):
    name: str                                       # metric 이름 → EvalScore.metric
    threshold: float                                # pass/fail 기준선 → EvalScore.passed

    async def score(self, trajectory: Trajectory, task: Task) -> EvalScore: ...
    # pure (부수효과 0): 입력 같으면 출력 같음 → 재현/테스트 쉬움.
    # async: LLM-as-judge 가 내부에서 async LLM 호출.
