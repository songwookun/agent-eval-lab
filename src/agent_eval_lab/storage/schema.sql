-- 평가 결과 스키마 (SQLite).
-- runs   : RunResult 1건 = 1행. payload 에 전체 JSON 보존(재현/감사), 인덱스 컬럼은 조회/집계용.
-- scores : RunResult.scores 를 펼침 = (run × task × metric) 1행. 집계 쿼리(평균/통과율)용.

CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL,
    suite_id      TEXT NOT NULL,
    suite_version TEXT NOT NULL,
    model         TEXT NOT NULL,
    git_sha       TEXT,
    started_at    TEXT NOT NULL,   -- ISO8601 UTC
    ended_at      TEXT NOT NULL,
    payload       TEXT NOT NULL    -- asdict(RunResult) 직렬화 전체
);

CREATE TABLE IF NOT EXISTS scores (
    run_id  TEXT NOT NULL,
    task_id TEXT NOT NULL,
    metric  TEXT NOT NULL,
    score   REAL NOT NULL,
    passed  INTEGER NOT NULL,      -- 0/1
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_scores_run ON scores(run_id);
