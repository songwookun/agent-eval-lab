"""SQLite 영속화. RunResult 를 저장/조회한다.

설계 결정: payload(전체 JSON) + scores(펼친 집계용 행) 이원화.
  - payload: 재현/감사용 완전 보존(asdict 직렬화).
  - scores: 평균/통과율 같은 집계를 SQL 로 뽑기 위한 평면 테이블.
get_run/list_runs 는 dataclass 복원 대신 dict 를 반환(중첩 복원 비용 회피, 표 출력엔 충분).
"""

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from agent_eval_lab.core.types import RunResult

_SCHEMA = Path(__file__).parent / "schema.sql"
DEFAULT_DB = "eval.db"


def _json_default(o: Any) -> Any:
    """asdict 가 남긴 datetime/Enum 을 JSON 직렬화 가능 형태로."""
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    raise TypeError(f"직렬화 불가: {type(o).__name__}")


def init_db(db_path: str = DEFAULT_DB) -> None:
    """스키마 적용(멱등 — IF NOT EXISTS)."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA.read_text(encoding="utf-8"))


def save_run(result: RunResult, db_path: str = DEFAULT_DB) -> None:
    """RunResult 1건을 runs + scores 에 저장. payload 는 전체 JSON."""
    payload = json.dumps(asdict(result), ensure_ascii=False, default=_json_default)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, agent_id, suite_id, suite_version, model, "
            "git_sha, started_at, ended_at, payload) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                result.run_id, result.agent_id, result.suite_id,
                result.config.suite_version, result.config.model, result.config.git_sha,
                result.started_at.isoformat(), result.ended_at.isoformat(), payload,
            ),
        )
        conn.executemany(
            "INSERT INTO scores (run_id, task_id, metric, score, passed) VALUES (?,?,?,?,?)",
            [(result.run_id, s.task_id, s.metric, s.score, int(s.passed)) for s in result.scores],
        )


def get_run(run_id: str, db_path: str = DEFAULT_DB) -> dict | None:
    """run_id 의 payload(전체 dict) 반환. 없으면 None."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def list_runs(limit: int = 20, db_path: str = DEFAULT_DB) -> list[dict]:
    """최근 run 요약 목록(집계 포함). started_at 내림차순."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT r.run_id, r.agent_id, r.suite_id, r.model, r.started_at, "
            "       COUNT(s.task_id) AS n_scores, "
            "       AVG(s.score) AS avg_score, "
            "       SUM(s.passed) AS n_passed "
            "FROM runs r LEFT JOIN scores s ON r.run_id = s.run_id "
            "GROUP BY r.run_id ORDER BY r.started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
