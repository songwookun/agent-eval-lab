"""테스트용 객체 팩토리. 필수 필드를 기본값으로 깔고, 테스트가 신경 쓰는 것만 override.

패턴: `base | overrides` — dict 병합(겹치면 오른쪽 승). "이 테스트가 무엇에 관한지"만
인자로 드러나게 해서 보일러플레이트 제거. 기본값은 전부 "LLM 안 건드리는 결정적 케이스"로 수렴.
"""

from datetime import datetime, timezone

from agent_eval_lab.core.types import LLMStep, Task, Trajectory


def make_task(**overrides) -> Task:
    # expected_tools=[] → tool_call irrelevance 모드, ground_truth={} → judge 안 부름.
    # 둘 다 디폴트가 "키 없이 도는 케이스" → 결정성 보장.
    base = dict(
        id="t1", prompt="p", expected_tools=[],
        expected_min_steps=1, ground_truth={},
    )
    return Task(**(base | overrides))


def make_trajectory(**overrides) -> Trajectory:
    # now 를 한 번만 뽑아 started==ended (테스트엔 시간차 무의미).
    # timezone.utc 는 협상 불가 — types.py 규약(naive 금지). 규약 위반 데이터로 테스트 X.
    now = datetime.now(timezone.utc)
    base = dict(
        task_id="t1", agent_id="a", steps=[], final_output="",
        total_latency_ms=0, total_tokens_in=0, total_tokens_out=0,
        total_cost_usd=0.0, started_at=now, ended_at=now, error=None,
    )
    return Trajectory(**(base | overrides))


def make_llm_step(**overrides) -> LLMStep:
    # tool_call 채점의 유일한 재료 = tool_calls_requested(원소는 {"name": ...}).
    # step_type 은 LLMStep 이 자동 고정 → 생략. name(BaseStep)·model(LLMStep) 둘 다 필수.
    base = dict(
        span_id="s1", name="gemini-2.5-flash",
        latency_ms=0, started_at=datetime.now(timezone.utc),
        model="gemini-2.5-flash", prompt_messages=[],
        completion="", tool_calls_requested=[],
    )
    return LLMStep(**(base | overrides))
