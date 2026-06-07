"""핵심 데이터 모델. 평가/저장/조회가 전부 이걸 받고 뱉는다.

규약: 모든 datetime 필드(started_at/ended_at)는 UTC-aware 여야 한다.
      생성부에서 datetime.now(timezone.utc) 사용. naive(로컬) datetime 금지.
      이유: 저장·비교·trace 정렬 시 타임존 모호성 제거.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ─── Task: 평가 대상 ─────────────────────────────────────
@dataclass(frozen=True)
class Task:
    id: str                              # "weather_01"
    prompt: str                          # agent 에게 줄 instruction
    expected_tools: list[str]            # ["get_weather", "calc"]
    expected_min_steps: int              # 최적 step 수 (trajectory 효율 baseline)
    ground_truth: dict[str, Any]         # judge/assert 가 참조할 정답 힌트
    metadata: dict[str, Any] = field(default_factory=dict)
    timeout_s: int = 60                  # task 최대 실행 시간
    max_cost_usd: float = 0.10           # task 최대 비용 (초과 시 중단)


# ─── Trajectory step 모델 ────────────────────────────────
# 설계 결정: LLMStep / ToolStep 분리 (discriminated union), 모두 kw_only.
# kw_only 근거: 부모(기본값 있는 error) + 자식(기본값 없는 필드) 상속 시
#   "non-default follows default" TypeError 회피 (STUDY.md 참고)
class StepType(str, Enum):
    LLM = "llm"
    TOOL = "tool"


@dataclass(kw_only=True)
class BaseStep:
    span_id: str                         # OTel span id
    name: str                            # tool 이름 or model 이름
    step_type: StepType                  # discriminator
    latency_ms: int
    started_at: datetime
    error: str | None = None


@dataclass(kw_only=True)
class LLMStep(BaseStep):
    step_type: StepType = StepType.LLM   # 자동 고정 (호출부가 안 넘김)
    model: str                           # "gemini-2.5-flash"
    prompt_messages: list[dict]          # role별 message 배열
    completion: str                      # LLM 텍스트 출력
    tool_calls_requested: list[dict]     # LLM이 요청한 tool calls (id 포함)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    finish_reason: str | None = None     # "stop"|"tool_use"|"max_tokens"


@dataclass(kw_only=True)
class ToolStep(BaseStep):
    step_type: StepType = StepType.TOOL  # 자동 고정 (호출부가 안 넘김)
    tool_name: str                       # "get_weather"
    tool_args: dict[str, Any]            # {"city": "Tokyo"}
    tool_result: Any                     # tool마다 타입 다름
    tool_call_id: str                    # LLMStep의 tool call id와 매칭


Step = LLMStep | ToolStep                # 타입 alias (Trajectory.steps 용)


# ─── Trajectory: agent 1회 실행 결과 ─────────────────────
@dataclass
class Trajectory:
    task_id: str                         # 어느 Task를 풀었나
    agent_id: str                        # "gemini-agent-v1"
    steps: list[Step]                    # LLMStep/ToolStep 섞임 (시간순)
    final_output: str                    # agent 최종 답변
    total_latency_ms: int
    total_tokens_in: int                 # sum of LLMStep.tokens_in
    total_tokens_out: int                # sum of LLMStep.tokens_out
    total_cost_usd: float                # sum of LLMStep.cost_usd
    started_at: datetime
    ended_at: datetime
    error: str | None = None             # agent 루프 자체가 죽으면 여기


# ─── EvalScore: 평가 결과 (axis 1개당 1개) ───────────────
# 설계 결정: sub_scores 1급 필드 — 최종 score만으론 근거 소실 (STUDY.md)
@dataclass
class EvalScore:
    task_id: str                         # 어느 task의 점수
    metric: str                          # "task_success"|"tool_call"|...
    score: float                         # 0.0~1.0 최종 점수
    sub_scores: dict[str, float] = field(default_factory=dict)
    passed: bool = False                 # threshold 통과 여부
    reason: str = ""                     # judge 설명/계산 근거
    details: dict[str, Any] = field(default_factory=dict)


# ─── RunConfig: 재현성 snapshot (frozen 박제) ────────────
# 설계 결정: frozen + 비밀키 금지 (env는 whitelist만) (STUDY.md)
@dataclass(frozen=True)
class RunConfig:
    # LLM 설정
    model: str                           # "gemini-2.5-flash"
    temperature: float
    max_steps: int
    # prompt / agent 버전
    system_prompt_hash: str              # SHA256 (본문은 별도 저장)
    agent_version: str                   # "gemini-agent-v1"
    suite_version: str                   # "suite_v1.0"
    # 환경 추적
    git_sha: str | None = None
    env: dict[str, str] = field(default_factory=dict)  # whitelist만! 비밀 X
    # escape hatch
    extra: dict[str, Any] = field(default_factory=dict)


# ─── RunResult: 한 번 평가 돌린 전체 묶음 ────────────────
@dataclass
class RunResult:
    run_id: str                          # uuid
    agent_id: str
    suite_id: str                        # "suite_v1"
    config: RunConfig                    # 재현성 snapshot
    trajectories: list[Trajectory]       # task당 1개
    scores: list[EvalScore]              # task × metric 만큼
    started_at: datetime
    ended_at: datetime
