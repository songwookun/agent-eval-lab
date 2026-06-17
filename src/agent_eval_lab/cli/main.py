"""typer 진입점 — agent 실행/평가 CLI.

W1: run-once (단일 prompt adhoc 실행 + trajectory 출력).
W2: run (suite 평가 → 표 + SQLite 저장) / report (저장된 run) / list-runs (목록).
"""

import asyncio
import subprocess

import typer
from dotenv import load_dotenv

from agent_eval_lab.agents.gemini_agent import GeminiAgent
from agent_eval_lab.agents.groq_agent import GroqAgent
from agent_eval_lab.core.types import StepType, Task, Trajectory
from agent_eval_lab.evaluators.task_success import TaskSuccessEvaluator
from agent_eval_lab.evaluators.tool_call import ToolCallEvaluator
from agent_eval_lab.evaluators.trajectory import TrajectoryEvaluator
from agent_eval_lab.evaluators.cost import CostEvaluator
from agent_eval_lab.runner.orchestrator import Runner
from agent_eval_lab.storage.repository import get_run, init_db, list_runs, save_run
from agent_eval_lab.tasks.loader import load_suite
from agent_eval_lab.tools.registry import default_registry
from agent_eval_lab.tracing.otel_setup import setup_tracing

app = typer.Typer(help="AI Agent 평가/관측 CLI")


@app.callback()
def _root() -> None:
    """서브커맨드 구조 강제 (단일 커맨드가 루트로 흡수되는 것 방지)."""


def _git_sha() -> str | None:
    """현재 commit short SHA. git 없거나 repo 아니면 None(재현성 best-effort)."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def _build_agent(name: str):
    """--agent 이름 → Agent 구현체. 같은 suite 를 여러 LLM 으로 교차 평가하는 진입점."""
    agents = {"gemini": GeminiAgent, "groq": GroqAgent}
    if name not in agents:
        raise typer.BadParameter(f"지원 agent: {list(agents)} (받음: {name!r})")
    return agents[name]()


def _print_payload(p: dict) -> None:
    """저장된 run payload(dict)를 점수 표로 출력. run/report 공용."""
    cfg = p["config"]
    typer.echo("=" * 64)
    typer.echo(f"run_id: {p['run_id']}")
    typer.echo(
        f"suite : {p['suite_id']} (v{cfg['suite_version']}) | "
        f"model: {cfg['model']} | git: {cfg['git_sha']}"
    )
    typer.echo("-" * 64)
    typer.echo(f"{'TASK':<12}{'METRIC':<16}{'SCORE':>6}  PASS")
    scores = p["scores"]
    for s in scores:
        mark = "✅" if s["passed"] else "❌"
        typer.echo(f"{s['task_id']:<12}{s['metric']:<16}{s['score']:>6.2f}  {mark}")
    n = len(scores)
    passed = sum(1 for s in scores if s["passed"])
    avg = sum(s["score"] for s in scores) / n if n else 0.0

    # 축(metric)별 분리 집계 — 4축이 섞인 전체 평균만으론 어느 축이 약한지 안 보임
    typer.echo("-" * 64)
    typer.echo("[축별 요약]")
    by_metric: dict[str, list[dict]] = {}
    for s in scores:  # 첫 등장 순서 보존(dict 삽입순)
        by_metric.setdefault(s["metric"], []).append(s)
    for metric, rows in by_metric.items():
        m_avg = sum(r["score"] for r in rows) / len(rows)
        m_pass = sum(1 for r in rows if r["passed"])
        typer.echo(f"  {metric:<20}avg {m_avg:.2f}  {m_pass:>2}/{len(rows)}")

    typer.echo("-" * 64)
    typer.echo(f"전체 평균 {avg:.2f} | 통과 {passed}/{n}")
    for s in scores:  # 실패한 것만 사유 노출
        if not s["passed"]:
            typer.echo(f"  ✗ {s['task_id']}: {s['reason']}")


@app.command()
def run(
    suite: str = typer.Option("suite_v1", help="suite 이름 또는 .json 경로"),
    out: str = typer.Option("eval.db", help="결과 저장 SQLite 경로"),
    agent: str = typer.Option("gemini", help="평가할 agent: gemini | groq"),
    console: bool = typer.Option(False, help="OTel span 을 콘솔에 출력"),
):
    """suite 전체를 평가 실행 → 점수 표 출력 + SQLite 저장."""
    load_dotenv()
    setup_tracing(console=console)
    version, tasks = load_suite(suite)
    runner = Runner(
        agent=_build_agent(agent),
        evaluators=[
            TaskSuccessEvaluator(), ToolCallEvaluator(),
            TrajectoryEvaluator(), CostEvaluator(),
        ],
        tools=default_registry().all_tools(),
        suite=tasks,
        suite_id=suite,
        suite_version=version,
        git_sha=_git_sha(),
    )
    typer.echo(f"suite '{suite}' ({len(tasks)} tasks) 실행 중...")
    result = asyncio.run(runner.run_all())
    init_db(out)
    save_run(result, out)
    _print_payload(get_run(result.run_id, out))  # 저장본을 다시 읽어 출력(get_run 동시 검증)
    typer.echo(f"\n저장됨: {out} (run_id={result.run_id})")


@app.command()
def report(
    run_id: str,
    out: str = typer.Option("eval.db", help="조회할 SQLite 경로"),
):
    """저장된 run 의 점수 표를 다시 출력."""
    p = get_run(run_id, out)
    if p is None:
        typer.echo(f"run 없음: {run_id}")
        raise typer.Exit(1)
    _print_payload(p)


@app.command(name="list-runs")
def list_runs_cmd(
    limit: int = typer.Option(20, help="최근 N개"),
    out: str = typer.Option("eval.db", help="조회할 SQLite 경로"),
):
    """최근 run 목록(평균/통과 집계)."""
    rows = list_runs(limit, out)
    if not rows:
        typer.echo("저장된 run 없음")
        return
    typer.echo(f"{'RUN_ID':<34}{'SUITE':<12}{'AVG':>5}{'PASS':>8}  STARTED")
    for r in rows:
        avg = r["avg_score"] or 0.0
        passed = int(r["n_passed"] or 0)
        typer.echo(
            f"{r['run_id']:<34}{r['suite_id']:<12}{avg:>5.2f}"
            f"{passed:>4}/{r['n_scores']:<3}  {r['started_at']}"
        )


# ─── W1 자산: 단일 prompt adhoc 실행 (trajectory 디버깅용) ───
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


@app.command(name="run-once")
def run_once(
    prompt: str = typer.Option("도쿄의 섭씨 온도에 100을 곱한 값을 계산해줘", help="agent 에게 줄 지시"),
    agent: str = typer.Option("gemini", help="실행할 agent: gemini | groq"),
    console: bool = typer.Option(True, help="OTel span 을 콘솔에 출력"),
):
    """agent 를 단일 prompt 로 실행하고 trajectory 를 출력(W1 디버깅용)."""
    load_dotenv()
    setup_tracing(console=console)
    agent_impl = _build_agent(agent)
    task = Task(id="cli_adhoc", prompt=prompt, expected_tools=[], expected_min_steps=1, ground_truth={})
    tr = asyncio.run(agent_impl.run(task, default_registry().all_tools()))
    _print_trajectory(tr)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="바인드 호스트"),
    port: int = typer.Option(8000, help="포트"),
    out: str = typer.Option("eval.db", help="조회할 SQLite 경로"),
):
    """FastAPI 조회 API 서버 기동 (Swagger UI: /docs)."""
    import os
    import uvicorn

    os.environ["EVAL_DB"] = out  # api.main._db() 가 이 env 를 읽음
    typer.echo(f"API: http://{host}:{port}  |  문서: http://{host}:{port}/docs")
    uvicorn.run("agent_eval_lab.api.main:app", host=host, port=port)


def main() -> None:
    app()
