"""GroqAgent — groq SDK(OpenAI 호환) + agent loop 자체 구현.

GeminiAgent 와 *같은* Agent Protocol(agent_id + async run → Trajectory, 내부 OTel
span emit)을 채우되, API 방언만 OpenAI 호환(messages/tool_calls)으로 바꾼 어댑터.
→ "어떤 LLM 이든 어댑터로 받는다" 는 framework-agnostic 설계의 두 번째 실증.

비용: Groq 무료 티어만 사용(llama-3.3-70b-versatile). 한도 초과는 429 로 차단될 뿐
      과금되지 않는다. cost_usd 는 평가 점수용 가상 단가(실제 결제와 무관).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import groq
from groq import AsyncGroq
from opentelemetry.trace import Status, StatusCode
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from agent_eval_lab.core.protocols import Tool
from agent_eval_lab.core.types import Task, Trajectory, LLMStep, ToolStep
from agent_eval_lab.tracing.otel_setup import get_tracer


def _is_rate_limit(exc: BaseException) -> bool:
    """429 만 재시도 대상. Groq SDK 는 RateLimitError 로 표면화(Gemini 와 예외 타입만 다름)."""
    return isinstance(exc, groq.RateLimitError)


def _log_retry(state) -> None:
    """재시도 진입 알림(콘솔 표를 안 깨도록 stderr) — GeminiAgent 와 동일 UX."""
    print(f"  ⏳ Groq rate limit — {state.attempt_number}회차 재시도 대기 중...", file=sys.stderr)


# llama-3.3-70b-versatile 공개 단가 근사(USD/token). cost 축 일관성용 — 실제 결제 아님.
_PRICE_IN = 0.59 / 1_000_000
_PRICE_OUT = 0.79 / 1_000_000
_DEFAULT_SYSTEM = (
    "너는 도구를 사용해 사용자 요청을 해결하는 에이전트다. "
    "필요한 도구를 호출하고 끝나면 한국어로 최종 답을 제시해라."
)


class GroqAgent:
    agent_id = "groq-agent-v1"

    def __init__(
        self,
        model: str = "llama-3.3-70b-versatile",
        max_steps: int = 10,
        temperature: float = 0.0,
        system_prompt: str = _DEFAULT_SYSTEM,
    ):
        self.model = model
        self.max_steps = max_steps
        self.temperature = temperature
        self.system_prompt = system_prompt
        self._client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
        self._tracer = get_tracer("agent_eval_lab.agent")
        self._last_call_ms = 0  # 직전 성공한 호출 순수 시간(backoff 제외, cost 축용)

    def _build_groq_tools(self, tools: list[Tool]) -> list[dict]:
        """우리 Tool → OpenAI 호환 tools 포맷. input_schema(JSON Schema) 그대로 parameters 로."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    @retry(
        retry=retry_if_exception(_is_rate_limit),
        wait=wait_exponential(multiplier=2, min=5, max=40),  # 무료 분당 30 → 짧은 backoff 면 충분
        stop=stop_after_attempt(5),
        before_sleep=_log_retry,
        reraise=True,  # 끝까지 429면 원래 예외 전파 → trajectory.error 로 잡힘
    )
    async def _generate(self, messages, tools):
        """chat.completions 호출만 분리 — 429 재시도를 span/latency 로직과 격리.

        성공한 호출의 순수 시간만 self._last_call_ms 에 남긴다(backoff sleep 은 이 함수
        *밖*에서 tenacity 가 처리 → cost 축 latency 오염 방지). GeminiAgent._generate 와 동형.
        """
        t = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=self.temperature,
        )
        self._last_call_ms = int((time.perf_counter() - t) * 1000)
        return resp

    async def _call_llm(self, messages, groq_tools) -> tuple:
        """LLM 1회 호출 + LLMStep/span 생성. tool_calls 파싱이 Gemini 와의 핵심 차이."""
        started = datetime.now(timezone.utc)
        with self._tracer.start_as_current_span("llm.generate") as span:
            resp = await self._generate(messages, groq_tools)
            latency_ms = self._last_call_ms  # 순수 LLM 시간(backoff 제외)
            msg = resp.choices[0].message
            usage = resp.usage
            tokens_in = usage.prompt_tokens or 0
            tokens_out = usage.completion_tokens or 0
            tool_calls = msg.tool_calls or []
            span.set_attribute("gen_ai.system", "groq")
            span.set_attribute("gen_ai.request.model", self.model)
            span.set_attribute("gen_ai.usage.input_tokens", tokens_in)
            span.set_attribute("gen_ai.usage.output_tokens", tokens_out)
            step = LLMStep(
                span_id=format(span.get_span_context().span_id, "016x"),
                name=self.model,
                latency_ms=latency_ms,
                started_at=started,
                model=self.model,
                prompt_messages=list(messages),  # 이미 dict 라 스냅샷만(Gemini 는 직렬화 필요했음)
                completion=msg.content or "",
                tool_calls_requested=[
                    {"id": tc.id, "name": tc.function.name,
                     "args": _safe_json(tc.function.arguments)}
                    for tc in tool_calls
                ],
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=tokens_in * _PRICE_IN + tokens_out * _PRICE_OUT,
                finish_reason="tool_use" if tool_calls else "stop",
            )
        return msg, tool_calls, step

    async def _dispatch_tool(self, tools_by_name: dict[str, Tool], tc, index: int):
        """tool 1개 실행 + ToolStep/span + LLM 에 돌려줄 {role:'tool'} 메시지."""
        started = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        name = tc.function.name
        call_id = tc.id or f"{name}_{index}"
        args = _safe_json(tc.function.arguments)
        with self._tracer.start_as_current_span(f"tool.{name}") as span:
            span.set_attribute("gen_ai.tool.name", name)
            span.set_attribute("gen_ai.tool.call.id", call_id)
            error = None
            try:
                tool = tools_by_name[name]
                result = await tool.call(**args)
            except Exception as e:  # tool 깨져도 agent 는 안 죽음 → LLM 이 복구 시도
                result = {"error": str(e)}
                error = str(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
            latency_ms = int((time.perf_counter() - t0) * 1000)
            step = ToolStep(
                span_id=format(span.get_span_context().span_id, "016x"),
                name=name,
                latency_ms=latency_ms,
                started_at=started,
                error=error,
                tool_name=name,
                tool_args=args,
                tool_result=result,
                tool_call_id=call_id,
            )
            tool_msg = {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result)}
        return step, tool_msg

    async def run(self, task: Task, tools: list[Tool]) -> Trajectory:
        """agent loop: LLM 호출 → tool_calls 파싱 → tool dispatch → 결과 feed → 반복."""
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        tools_by_name = {t.name: t for t in tools}
        groq_tools = self._build_groq_tools(tools)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task.prompt},
        ]
        steps: list = []
        final_output, error = "", None

        with self._tracer.start_as_current_span(f"agent.run:{task.id}") as root:
            root.set_attribute("agent.id", self.agent_id)
            root.set_attribute("task.id", task.id)
            try:
                for _ in range(self.max_steps):
                    msg, tool_calls, llm_step = await self._call_llm(messages, groq_tools)
                    steps.append(llm_step)
                    if not tool_calls:  # 텍스트 답 → 종료
                        final_output = msg.content or ""
                        break
                    # assistant 의 tool_calls turn 을 대화에 누적(다음 호출이 문맥으로 봄)
                    messages.append({
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {"id": tc.id, "type": "function",
                             "function": {"name": tc.function.name,
                                          "arguments": tc.function.arguments}}
                            for tc in tool_calls
                        ],
                    })
                    for i, tc in enumerate(tool_calls):
                        tool_step, tool_msg = await self._dispatch_tool(tools_by_name, tc, i)
                        steps.append(tool_step)
                        messages.append(tool_msg)  # 각 tool 결과를 개별 메시지로 feed
                else:  # break 없이 끝 = max_steps 초과 (무한루프 방어)
                    final_output = msg.content or ""
                    error = f"max_steps({self.max_steps}) 도달"
            except Exception as e:  # loop 자체가 터지면
                error = str(e)
                root.set_status(Status(StatusCode.ERROR, str(e)))

        ended_at = datetime.now(timezone.utc)
        llm_steps = [s for s in steps if isinstance(s, LLMStep)]
        return Trajectory(
            task_id=task.id,
            agent_id=self.agent_id,
            steps=steps,
            final_output=final_output,
            total_latency_ms=int((time.perf_counter() - t0) * 1000),
            total_tokens_in=sum(s.tokens_in for s in llm_steps),
            total_tokens_out=sum(s.tokens_out for s in llm_steps),
            total_cost_usd=sum(s.cost_usd for s in llm_steps),
            started_at=started_at,
            ended_at=ended_at,
            error=error,
        )


def _safe_json(raw: str) -> dict:
    """tool args 는 OpenAI 방언에서 JSON *문자열* → dict. 빈/깨진 값은 {} 로 graceful."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
