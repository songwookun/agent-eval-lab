"""GeminiAgent — google-genai + agent loop 자체 구현.

high-level SDK wrapper 없이 LLM 호출 → function call 파싱 → tool dispatch →
결과 feed → 반복을 직접 구현하고, LLM/tool span 을 직접 emit 한다.
"""

import os
import sys
import time
from datetime import datetime, timezone

from google import genai
from google.genai import errors, types
from opentelemetry.trace import Status, StatusCode
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from agent_eval_lab.core.protocols import Tool
from agent_eval_lab.core.types import Task, Trajectory, LLMStep, ToolStep
from agent_eval_lab.tracing.otel_setup import get_tracer


def _is_rate_limit(exc: BaseException) -> bool:
    """429(RESOURCE_EXHAUSTED) 만 재시도 대상. 다른 에러는 즉시 전파."""
    return isinstance(exc, errors.APIError) and (
        getattr(exc, "code", None) == 429 or getattr(exc, "status", None) == "RESOURCE_EXHAUSTED"
    )


def _log_retry(state) -> None:
    """재시도 진입 시 사용자에게 알림(콘솔 표를 안 깨도록 stderr)."""
    print(f"  ⏳ rate limit — {state.attempt_number}회차 재시도 대기 중...", file=sys.stderr)

_PRICE_IN = 0.30 / 1_000_000   # gemini-2.5-flash 입력 단가 (근사, W3 cost evaluator 정밀화)
_PRICE_OUT = 2.50 / 1_000_000  # 출력 단가
_DEFAULT_SYSTEM = (
    "너는 도구를 사용해 사용자 요청을 해결하는 에이전트다. "
    "필요한 도구를 호출하고 끝나면 한국어로 최종 답을 제시해라."
)


def _summarize_contents(contents) -> list[dict]:
    """genai Content 들을 가벼운 dict 로 직렬화 (LLMStep.prompt_messages 기록용)."""
    out = []
    for c in contents:
        parts = []
        for p in c.parts or []:
            if p.text:
                parts.append({"text": p.text})
            elif p.function_call:
                parts.append({
                    "function_call": {"name": p.function_call.name,
                                      "args": dict(p.function_call.args or {})}
                })
            elif p.function_response:
                parts.append({"function_response": {"name": p.function_response.name}})
        out.append({"role": c.role, "parts": parts})
    return out


class GeminiAgent:
    agent_id = "gemini-agent-v1"

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        max_steps: int = 10,
        temperature: float = 0.0,
        system_prompt: str = _DEFAULT_SYSTEM,
    ):
        self.model = model
        self.max_steps = max_steps
        self.temperature = temperature
        self.system_prompt = system_prompt
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._tracer = get_tracer("agent_eval_lab.agent")
        self._last_call_ms = 0  # 직전 성공한 generate_content 순수 시간(backoff 제외, cost 축용)

    def _build_genai_tools(self, tools: list[Tool]) -> list[types.Tool]:
        """우리 Tool → genai FunctionDeclaration. input_schema(JSON Schema) 그대로 투입."""
        declarations = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters_json_schema=t.input_schema,
            )
            for t in tools
        ]
        return [types.Tool(function_declarations=declarations)]

    @retry(
        retry=retry_if_exception(_is_rate_limit),
        wait=wait_exponential(multiplier=2, min=20, max=80),  # 무료 tier 분단위 리셋 커버
        stop=stop_after_attempt(5),
        before_sleep=_log_retry,
        reraise=True,  # 끝까지 429면 원래 예외를 그대로 → trajectory.error 로 잡힘
    )
    async def _generate(self, contents, config) -> types.GenerateContentResponse:
        """generate_content 호출만 분리 — 429 재시도를 span/latency 로직과 격리.

        성공한 호출의 순수 시간만 self._last_call_ms 에 남긴다(재시도 backoff sleep은
        이 함수 *밖*에서 tenacity 가 처리하므로 자동 제외 → cost 축 latency 오염 방지).
        """
        t = time.perf_counter()
        resp = await self._client.aio.models.generate_content(
            model=self.model, contents=contents, config=config
        )
        self._last_call_ms = int((time.perf_counter() - t) * 1000)
        return resp

    async def _call_llm(self, contents, genai_tools) -> tuple[types.GenerateContentResponse, LLMStep]:
        """LLM 1회 호출 + LLMStep/span 생성. AFC 끄고 우리가 loop 제어."""
        started = datetime.now(timezone.utc)
        config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            temperature=self.temperature,
            tools=genai_tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        with self._tracer.start_as_current_span("llm.generate") as span:
            response = await self._generate(contents, config)
            latency_ms = self._last_call_ms  # 순수 LLM 시간(backoff 제외) — _generate 가 측정
            usage = response.usage_metadata
            tokens_in = usage.prompt_token_count or 0
            tokens_out = usage.candidates_token_count or 0
            fcs = response.function_calls or []
            span.set_attribute("gen_ai.system", "gemini")
            span.set_attribute("gen_ai.request.model", self.model)
            span.set_attribute("gen_ai.usage.input_tokens", tokens_in)
            span.set_attribute("gen_ai.usage.output_tokens", tokens_out)
            step = LLMStep(
                span_id=format(span.get_span_context().span_id, "016x"),
                name=self.model,
                latency_ms=latency_ms,
                started_at=started,
                model=self.model,
                prompt_messages=_summarize_contents(contents),
                completion=response.text or "",
                tool_calls_requested=[
                    {"id": fc.id, "name": fc.name, "args": dict(fc.args or {})} for fc in fcs
                ],
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=tokens_in * _PRICE_IN + tokens_out * _PRICE_OUT,
                finish_reason="tool_use" if fcs else "stop",
            )
        return response, step

    async def _dispatch_tool(self, tools_by_name: dict[str, Tool], fc, index: int):
        """tool 1개 실행 + ToolStep/span + LLM 에 돌려줄 function_response part."""
        started = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        call_id = fc.id or f"{fc.name}_{index}"  # Gemini 는 id 를 안 주므로 합성
        args = dict(fc.args or {})
        with self._tracer.start_as_current_span(f"tool.{fc.name}") as span:
            span.set_attribute("gen_ai.tool.name", fc.name)
            span.set_attribute("gen_ai.tool.call.id", call_id)
            error = None
            try:
                tool = tools_by_name[fc.name]
                result = await tool.call(**args)
            except Exception as e:  # tool 깨져도 agent 는 안 죽음 → LLM 이 복구 시도
                result = {"error": str(e)}
                error = str(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
            latency_ms = int((time.perf_counter() - t0) * 1000)
            step = ToolStep(
                span_id=format(span.get_span_context().span_id, "016x"),
                name=fc.name,
                latency_ms=latency_ms,
                started_at=started,
                error=error,
                tool_name=fc.name,
                tool_args=args,
                tool_result=result,
                tool_call_id=call_id,
            )
            fr_part = types.Part.from_function_response(name=fc.name, response={"result": result})
        return step, fr_part

    async def run(self, task: Task, tools: list[Tool]) -> Trajectory:
        """agent loop: LLM 호출 → function call 파싱 → tool dispatch → 결과 feed → 반복."""
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        tools_by_name = {t.name: t for t in tools}
        genai_tools = self._build_genai_tools(tools)
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=task.prompt)])]
        steps: list = []
        final_output, error = "", None

        with self._tracer.start_as_current_span(f"agent.run:{task.id}") as root:
            root.set_attribute("agent.id", self.agent_id)
            root.set_attribute("task.id", task.id)
            try:
                for _ in range(self.max_steps):
                    response, llm_step = await self._call_llm(contents, genai_tools)
                    steps.append(llm_step)
                    fcs = response.function_calls or []
                    if not fcs:  # 텍스트 답 → 종료
                        final_output = response.text or ""
                        break
                    contents.append(response.candidates[0].content)  # model 의 function_call turn
                    fr_parts = []
                    for i, fc in enumerate(fcs):
                        tool_step, fr_part = await self._dispatch_tool(tools_by_name, fc, i)
                        steps.append(tool_step)
                        fr_parts.append(fr_part)
                    contents.append(types.Content(role="user", parts=fr_parts))  # tool 결과 feed
                else:  # break 없이 끝 = max_steps 초과 (무한루프 방어)
                    final_output = response.text or ""
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
