"""suite JSON 로더 + 검증 게이트.

설계(research 2026-06-11): 포맷은 versioned object `{version, tasks:[...]}`.
dataclass 생성은 타입을 강제하지 않으므로, 여기서 fail-fast 검증한다
("어느 task 의 어느 필드가 왜 틀렸나"를 명시). pydantic 미도입 — 표준 lib 수동 검증.
"""

import json
from pathlib import Path

from agent_eval_lab.core.types import Task

_SUITES_DIR = Path(__file__).parent / "suites"  # 패키지 내부 suites/

# Task 의 필수 필드(기본값 없는 것). 나머지(metadata/timeout_s/max_cost_usd)는 옵션.
_REQUIRED = ("id", "prompt", "expected_tools", "expected_min_steps", "ground_truth")
# JSON 에서 허용할 키 전체 — 오타/잉여 키를 조용히 무시하지 않고 잡아낸다.
_ALLOWED = _REQUIRED + ("metadata", "timeout_s", "max_cost_usd")


def suite_path(name: str) -> Path:
    """suite 이름('suite_v1') → 패키지 내부 JSON 경로. 이미 경로면 그대로."""
    p = Path(name)
    if p.suffix == ".json" and p.exists():  # 직접 경로로도 호출 가능
        return p
    return _SUITES_DIR / f"{name}.json"


def _validate_task(raw: dict, idx: int) -> Task:
    """task dict 1개를 검증 후 Task 로. 실패 시 위치를 담은 ValueError."""
    where = f"tasks[{idx}]" + (f"(id={raw['id']!r})" if isinstance(raw.get("id"), str) else "")
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: object 가 아님")
    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        raise ValueError(f"{where}: 필수 필드 누락 {missing}")
    unknown = [k for k in raw if k not in _ALLOWED]
    if unknown:
        raise ValueError(f"{where}: 알 수 없는 필드 {unknown} (오타 의심)")
    if not isinstance(raw["expected_tools"], list):
        raise ValueError(f"{where}: expected_tools 는 list 여야 함")
    if not isinstance(raw["expected_min_steps"], int):
        raise ValueError(f"{where}: expected_min_steps 는 int 여야 함")
    if not isinstance(raw["ground_truth"], dict):
        raise ValueError(f"{where}: ground_truth 는 object 여야 함")
    return Task(**raw)  # 허용 키만 남았으므로 안전하게 언팩


def load_suite(name: str) -> tuple[str, list[Task]]:
    """suite 를 읽어 (version, list[Task]) 반환. 검증 실패 시 ValueError.

    version 은 RunConfig.suite_version 재현성 필드로 흘러간다.
    """
    path = suite_path(name)
    if not path.exists():
        raise FileNotFoundError(f"suite 없음: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "tasks" not in data:
        raise ValueError(f"{path}: 최상위는 {{'version','tasks'}} object 여야 함")
    version = data.get("version", "unknown")
    raw_tasks = data["tasks"]
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError(f"{path}: tasks 는 비어있지 않은 list 여야 함")
    ids = [t.get("id") for t in raw_tasks if isinstance(t, dict)]
    if len(ids) != len(set(ids)):  # id 중복 = 점수 집계가 깨짐
        raise ValueError(f"{path}: task id 중복 {[i for i in ids if ids.count(i) > 1]}")
    tasks = [_validate_task(t, i) for i, t in enumerate(raw_tasks)]
    return version, tasks
