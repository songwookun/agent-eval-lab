"""FastAPI 조회 API — eval.db 를 읽기 전용 REST 로 노출.

평가 실행/저장은 CLI 담당, 이 API 는 *조회만* (관심사 분리). Next.js dashboard 의
백엔드이자, /docs 자동 Swagger UI 로 그 자체가 데모/포폴 자산.
"""

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent_eval_lab.storage.repository import get_run, list_runs


# ─── 응답 스키마 (FastAPI 가 검증 + OpenAPI 문서 자동 생성) ───
class RunSummary(BaseModel):
    """GET /runs 1행 — list_runs 집계 결과."""
    run_id: str
    agent_id: str | None = None
    suite_id: str
    model: str | None = None
    started_at: str
    n_scores: int
    avg_score: float | None = None
    n_passed: int | None = None


class ScoreOut(BaseModel):
    """EvalScore 1개 — 4축 중 한 축의 채점 결과."""
    task_id: str
    metric: str
    score: float
    sub_scores: dict = {}
    passed: bool
    reason: str | None = None
    details: dict = {}


class RunDetail(BaseModel):
    """GET /runs/{id} — run 1개 상세. trajectories 는 무거워 v1 에선 제외."""
    run_id: str
    agent_id: str | None = None
    suite_id: str
    config: dict
    scores: list[ScoreOut]
    started_at: str
    ended_at: str | None = None


def _db() -> str:
    """조회 대상 SQLite 경로. env 로 오버라이드(테스트/배포 유연), 기본 eval.db."""
    return os.getenv("EVAL_DB", "eval.db")


app = FastAPI(
    title="agent-eval-lab API",
    description="평가 결과(eval.db) 읽기 전용 조회 API",
    version="0.1.0",
)

# Next.js dashboard(다른 포트)가 호출할 수 있게 CORS 허용(로컬 개발용).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001", "http://127.0.0.1:3001",  # Next.js dashboard(3000은 Langfuse)
        "http://localhost:3000", "http://127.0.0.1:3000",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """헬스체크 — 서버 살아있는지."""
    return {"status": "ok"}


@app.get("/runs", response_model=list[RunSummary])
def get_runs(limit: int = Query(20, ge=1, le=200, description="최근 N개")) -> list[dict]:
    """최근 run 목록(평균/통과 집계). started_at 내림차순."""
    return list_runs(limit, _db())


@app.get("/runs/{run_id}", response_model=RunDetail)
def get_run_detail(run_id: str) -> dict:
    """run 1개 상세(4축 점수표). 없으면 404."""
    payload = get_run(run_id, _db())
    if payload is None:
        raise HTTPException(status_code=404, detail=f"run 없음: {run_id}")
    return payload
