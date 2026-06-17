#!/bin/bash
# ─────────────────────────────────────────────────────────────
# agent-eval-lab 대시보드 런처 (macOS)
# Finder 에서 더블클릭 → Terminal 에서 API(:8000) + dashboard(:3001) 기동 + 브라우저 오픈.
# 이 창을 닫으면(또는 Ctrl+C) 두 서버 모두 종료.
# ─────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1

echo "▶ agent-eval-lab 대시보드 기동..."

# 포트 점유 시 정리(이전 잔여 프로세스)
lsof -ti :8000 | xargs kill -9 2>/dev/null
lsof -ti :3001 | xargs kill -9 2>/dev/null

# 1) FastAPI 조회 API (백그라운드)
echo "  · API 서버 (http://localhost:8000)"
uv run agent-eval-lab serve --port 8000 >/tmp/aelab-api.log 2>&1 &
API_PID=$!

# 2) Next.js dashboard (백그라운드)
echo "  · dashboard (http://localhost:3001)"
( cd dashboard && npm run dev >/tmp/aelab-dash.log 2>&1 ) &
DASH_PID=$!

# 창 닫힘/Ctrl+C 시 두 서버 정리
trap 'echo; echo "■ 종료 중..."; kill $API_PID $DASH_PID 2>/dev/null; lsof -ti :8000 :3001 | xargs kill -9 2>/dev/null; exit 0' INT TERM EXIT

# dashboard 가 응답할 때까지 대기 후 브라우저 오픈
printf "  · 준비 대기"
until curl -fsS http://127.0.0.1:3001/ >/dev/null 2>&1; do printf "."; sleep 1; done
echo " 완료!"
open http://localhost:3001

echo
echo "✅ 대시보드: http://localhost:3001   (API 문서: http://localhost:8000/docs)"
echo "   이 창을 닫으면 서버가 종료됩니다. 로그: /tmp/aelab-api.log, /tmp/aelab-dash.log"
echo

# 포그라운드 유지(창이 살아있는 동안 서버 유지)
wait
