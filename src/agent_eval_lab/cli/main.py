"""typer 진입점 — agent 실행 CLI.

W1: run 커맨드로 task 1개 실행 + trajectory 출력 + (옵션) 콘솔 span.
"""

import asyncio

import typer
from dotenv import load_dotenv

from agent_eval_lab.agents.gemini_agent import GeminiAgent
from agent_eval_lab.core.types import StepType, Task, Trajectory
from agent_eval_lab.tools.registry import default_registry
from agent_eval_lab.tracing.otel_setup import setup_tracing

app = typer.Typer(help="AI Agent 평가/관측 CLI")


@app.callback()
def _root() -> None:
    """서브커맨드 구조 강제 (단일 커맨드가 루트로 흡수되는 것 방지)."""


def _print_trajectory(tr: Trajectory) -> None:
    typer.echo("─" * 50)
    for i, s in enumerate(tr.steps, 1):
        if s.step_type == StepType.TOOL:
            typer.echo(f"  {i}. [tool] {s.tool_name}({s.tool_args}) -> {s.tool_result}")
        else:
            tc = [c["name"] for c in s.tool_calls_requested]
            typer.echo(f"  {i}. [llm ] tool요청={tc or '없음'} | {s.tokens_in}/{s.tokens_out}tok")
    typer.echo("─" * 50)
    typer.echo(f"최종: {tr.final_output}")
    typer.echo(
        f"토큰 {tr.total_tokens_in}/{tr.total_tokens_out} | "
        f"${tr.total_cost_usd:.6f} | {tr.total_latency_ms}ms"
    )
    if tr.error:
        typer.echo(f"에러: {tr.error}")


@app.command()
def run(
    prompt: str = typer.Option("도쿄의 섭씨 온도에 100을 곱한 값을 계산해줘", help="agent 에게 줄 지시"),
    console: bool = typer.Option(True, help="OTel span 을 콘솔에 출력"),
):
    """agent 를 task 1개로 실행하고 trajectory 를 출력."""
    load_dotenv()
    setup_tracing(console=console)
    agent = GeminiAgent()
    task = Task(
        id="cli_adhoc",
        prompt=prompt,
        expected_tools=[],
        expected_min_steps=1,
        ground_truth={},
    )
    tr = asyncio.run(agent.run(task, default_registry().all_tools()))
    _print_trajectory(tr)


def main() -> None:
    app()
