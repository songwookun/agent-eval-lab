"""OpenTelemetry 트레이싱 초기화.

W1: 콘솔 exporter (A안 — Langfuse 는 W1 이후). exporter plug 구조라
    OTLP 전환은 console=False + OTLP processor 추가 1~2줄 (STUDY.md 참고).
"""

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

_provider: TracerProvider | None = None  # 멱등성: 이미 초기화됐나 기억


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
    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def get_tracer(name: str = "agent_eval_lab") -> trace.Tracer:
    """span 을 만들 tracer 반환. agent/tool 이 트레이싱 진입점으로 사용."""
    return trace.get_tracer(name)
