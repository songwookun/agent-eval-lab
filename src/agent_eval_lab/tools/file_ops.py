"""write_file Tool — workspace 안에 파일 쓰기 (부수효과 tool).

보안: 신뢰 안 되는 path 입력 → path traversal 로 시스템 임의 파일 덮어쓰기 위협.
      모든 쓰기를 workspace 하위로 강제하고, resolve 후 이탈을 검사한다.
"""

from pathlib import Path
from typing import Any

_WORKSPACE = Path("agent_workspace").resolve()  # 모든 쓰기의 sandbox base


def _safe_path(path: str) -> Path:
    """workspace 기준으로 정규화하고, base 밖이면 거부. (../, 절대경로, 심볼릭링크 차단)"""
    target = (_WORKSPACE / path).resolve()
    if not target.is_relative_to(_WORKSPACE):
        raise ValueError(f"workspace 이탈 거부: {path}")
    return target


class FileOpsTool:
    name = "write_file"
    description = "workspace 안에 파일을 쓴다. path 는 workspace 기준 상대경로."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "workspace 기준 상대 경로"},
            "content": {"type": "string", "description": "파일 내용"},
        },
        "required": ["path", "content"],
    }

    async def call(self, **kwargs: Any) -> dict:
        target = _safe_path(kwargs["path"])          # 보안 게이트 먼저
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(kwargs["content"], encoding="utf-8")
        return {"ok": True, "path": str(target)}
