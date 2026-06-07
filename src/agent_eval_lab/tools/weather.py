"""get_weather Tool — 도시 날씨 조회 (결정적 Mock).

평가 재현성을 위해 실제 API 대신 고정 데이터 사용. 실제 API 면 같은 task 가
매번 다른 답을 내서 성공률 측정이 불가능 (RunConfig 재현성 철학과 동일).
"""

from typing import Any

_WEATHER = {
    "tokyo": {"temp": 22, "unit": "celsius", "condition": "맑음"},
    "seoul": {"temp": 18, "unit": "celsius", "condition": "흐림"},
    "new york": {"temp": 15, "unit": "celsius", "condition": "비"},
}
_DEFAULT = {"temp": 20, "unit": "celsius", "condition": "맑음"}  # 미등록 도시 fallback


class WeatherTool:
    name = "get_weather"
    description = "도시의 현재 날씨를 조회한다. 예: city='Tokyo'."
    input_schema = {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "도시 이름"}},
        "required": ["city"],
    }

    async def call(self, **kwargs: Any) -> dict:
        city = kwargs["city"]
        data = _WEATHER.get(city.strip().lower(), _DEFAULT)  # 키 정규화
        return {"city": city, **data}
