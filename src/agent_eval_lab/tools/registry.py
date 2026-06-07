"""ToolRegistry — tool 을 이름으로 등록/조회.

클래스 인스턴스(전역 아님): registry 마다 독립 → 같은 agent 를 다른 tool 셋으로
비교 평가 + 테스트 격리. agent loop 은 get(name) 으로 LLM function call 을 실행.
"""

from agent_eval_lab.core.protocols import Tool
from agent_eval_lab.tools.calc import CalcTool
from agent_eval_lab.tools.weather import WeatherTool
from agent_eval_lab.tools.file_ops import FileOpsTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise TypeError(f"Tool Protocol 미충족: {tool!r}")
        if tool.name in self._tools:
            raise ValueError(f"중복 등록: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"등록되지 않은 tool: {name}")
        return self._tools[name]

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())  # 복사본 (내부 dict 보호)


def default_registry() -> ToolRegistry:
    """W1 표준 tool 3개를 채운 fresh registry. 매 호출 새 인스턴스(격리)."""
    reg = ToolRegistry()
    for tool in (CalcTool(), WeatherTool(), FileOpsTool()):
        reg.register(tool)
    return reg
