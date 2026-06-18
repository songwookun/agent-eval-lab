"""task_success evaluator — 결정적 부분만 테스트 (LLM judge 안 건드림).

핵심: checks 게이트가 실패하면 judge 호출 *전에* 단락된다 → GEMINI_API_KEY 없이도 도는 게
정상. 그게 "결정적 게이트" 설계의 증거.
"""

import pytest

from agent_eval_lab.evaluators.task_success import TaskSuccessEvaluator
from tests.factories import make_task, make_trajectory


def test_run_check_final_contains_true():
    # Arrange: final_output 에 기대값 존재
    traj = make_trajectory(final_output="날씨는 맑음입니다")
    check = {"type": "final_contains", "value": "맑음"}

    # Act + Assert
    assert TaskSuccessEvaluator()._run_check(check, traj) is True


def test_run_check_final_contains_false():
    # Arrange: final_output 에 기대값 없음
    traj = make_trajectory(final_output="날씨는 흐림입니다")
    check = {"type": "final_contains", "value": "맑음"}

    # Act + Assert
    assert TaskSuccessEvaluator()._run_check(check, traj) is False


def test_run_check_unknown_type_raises():
    # Arrange: 정의되지 않은 check type
    traj = make_trajectory()
    check = {"type": "telepathy"}

    # Act + Assert: 알 수 없는 type 은 조용히 통과시키지 않고 예외
    with pytest.raises(ValueError):
        TaskSuccessEvaluator()._run_check(check, traj)


async def test_failed_check_short_circuits_before_judge():
    # Arrange: checks 실패 + rubric 존재. rubric 이 있어도 judge 까지 가면 안 됨(키 없음).
    task = make_task(ground_truth={
        "checks": [{"type": "final_contains", "value": "맑음"}],
        "rubric": "답변이 친절한가",
    })
    traj = make_trajectory(final_output="흐림")  # check 실패 유도

    # Act: GEMINI_API_KEY 없이도 예외 없이 돌아야 한다(= judge 안 불렀다는 증거)
    score = await TaskSuccessEvaluator().score(traj, task)

    # Assert: 결정적 게이트에서 막혀 0.0, 미통과
    assert score.score == 0.0
    assert score.passed is False
