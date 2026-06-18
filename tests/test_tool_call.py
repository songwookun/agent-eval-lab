"""tool_call evaluator — 결정적 채점 로직 단위 테스트 (LLM 안 건드림).

AAA(Arrange-Act-Assert) 패턴. score()는 async라 await.
"""

import pytest

from agent_eval_lab.evaluators.tool_call import ToolCallEvaluator
from tests.factories import make_llm_step, make_task, make_trajectory


async def test_abstains_when_no_tools_expected():
    # Arrange: tool 불필요(expected=[]) + tool 한 번도 안 부른 trajectory
    task = make_task(expected_tools=[])
    traj = make_trajectory(steps=[])

    # Act
    score = await ToolCallEvaluator().score(traj, task)

    # Assert: "불필요한데 안 불렀으니 만점"
    assert score.score == 1.0
    assert score.passed is True


async def test_partial_match_gives_f1():
    # Arrange: 2개 기대(search, calc) 중 search 만 호출 → 부분 일치
    task = make_task(expected_tools=["search", "calc"])
    traj = make_trajectory(steps=[
        make_llm_step(tool_calls_requested=[{"name": "search"}]),
    ])

    # Act
    score = await ToolCallEvaluator().score(traj, task)

    # Assert: P=1/1=1.0, R=1/2=0.5 → F1 = 2·1·0.5/1.5 = 0.667
    assert score.score == pytest.approx(0.667, abs=0.01)
    assert score.passed is False  # threshold 1.0 미달


async def test_hallucinated_call_when_none_expected():
    # Arrange: tool 불필요(expected=[])인데 모델이 1개 호출 → 환각
    task = make_task(expected_tools=[])
    traj = make_trajectory(steps=[
        make_llm_step(tool_calls_requested=[{"name": "search"}]),
    ])

    # Act
    score = await ToolCallEvaluator().score(traj, task)

    # Assert: irrelevance 모드에서 호출하면 0.0
    assert score.score == 0.0
    assert score.passed is False


async def test_error_trajectory_scores_zero():
    # Arrange: agent 루프 자체가 죽음 → 채점 의미 없음
    task = make_task(expected_tools=["search"])
    traj = make_trajectory(error="boom")

    # Act
    score = await ToolCallEvaluator().score(traj, task)

    # Assert: error 가드가 즉시 0
    assert score.score == 0.0
    assert score.passed is False
