"""OpenTelemetry 트레이싱 초기화.

exporter plug 구조: 콘솔(디버깅) + OTLP(Langfuse 전송)를 공존시킨다.
Langfuse 는 OTLP 표준 endpoint(/api/public/otel/v1/traces)로 trace 를 직접 수신하고
gen_ai.* semconv 를 자동 파싱하므로, langfuse SDK 없이 순수 OTLP 로 보낸다(벤더 락인 0).
"""

import atexit
import base64
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

_provider: TracerProvider | None = None  # 멱등성: 이미 초기화됐나 기억


def _otlp_processor() -> BatchSpanProcessor | None:
    """Langfuse env 3개가 다 있으면 OTLP processor, 없으면 None(콘솔 only 로 graceful).

    BatchSpanProcessor 인 이유: span 종료마다 동기 HTTP 전송하면 agent loop 이 느려진다.
    배치로 모아 백그라운드 비동기 전송 → 단, 프로세스 종료 시 flush 필요(setup 에서 atexit).
    """
    host = os.getenv("LANGFUSE_HOST")
    pk = os.getenv("LANGFUSE_PUBLIC_KEY")
    sk = os.getenv("LANGFUSE_SECRET_KEY")
    if not (host and pk and sk):
        return None
    # Langfuse 인증: Basic base64(public:secret). OTLP 표준 헤더로 주입.
    token = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    exporter = OTLPSpanExporter(
        endpoint=f"{host.rstrip('/')}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {token}"},
    )
    return BatchSpanProcessor(exporter)


def setup_tracing(service_name: str = "agent-eval-lab", console: bool = True) -> TracerProvider:
    """트레이싱을 한 번 초기화한다. 재호출 시 기존 provider 재사용(멱등)."""
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    if console:
        # SimpleSpanProcessor: span 종료 즉시 콘솔 출력 (실행 순서대로 디버깅).
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    otlp = _otlp_processor()
    if otlp is not None:
        provider.add_span_processor(otlp)
        # 단발 CLI 실행: 프로세스 종료 전 배치 flush 보장(없으면 trace 유실).
        atexit.register(provider.shutdown)
    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def get_tracer(name: str = "agent_eval_lab") -> trace.Tracer:
    """span 을 만들 tracer 반환. agent/tool 이 트레이싱 진입점으로 사용."""
    return trace.get_tracer(name)
