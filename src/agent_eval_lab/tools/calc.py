"""calc Tool — 산술식 계산 (가장 단순한 Tool 구현체).

보안: agent tool 은 신뢰 안 되는 입력(LLM 출력)을 받으므로 eval() 금지(RCE).
      ast 파싱 + 연산자 화이트리스트로 허용된 산술만 평가한다.
"""

import ast
import operator
from typing import Any

# 허용 연산자 화이트리스트 — 여기 없는 노드(Call/Name/…)는 전부 차단된다.
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

# DoS 가드: 거대 지수(예: 9**9**9 = 3.7억 자리)로 인한 자원 고갈 차단.
# 정상 범위(2**1000 ≈ 300자리)는 통과. exotic 중첩은 Task.timeout_s 가 backstop.
_MAX_POW_EXPONENT = 1000


def _eval_node(node: ast.AST) -> float:
    """AST 노드를 재귀 평가. 허용된 3종(숫자/이항/단항)만, 나머진 거부."""
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)  # True/False 가 int 로 새는 것 차단
    ):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW_EXPONENT:
            raise ValueError(f"지수가 너무 큼 (|{right}| > {_MAX_POW_EXPONENT})")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"허용되지 않은 식: {type(node).__name__}")


def _safe_eval(expr: str) -> float:
    """산술식 문자열을 안전하게 평가. ast.parse 는 실행이 아니라 구문분석만."""
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body)


class CalcTool:
    name = "calc"
    description = "수학 산술식을 계산한다. 예: '2 + 3 * 4'. 사칙연산/거듭제곱/괄호 지원."
    input_schema = {
        "type": "object",
        "properties": {"expr": {"type": "string", "description": "계산할 산술식"}},
        "required": ["expr"],
    }

    async def call(self, **kwargs: Any) -> float:
        return _safe_eval(kwargs["expr"])
