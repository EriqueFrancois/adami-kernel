# src/adami_kernel/web/otel.py
# ====================== 【Agent Lightning 集成专用修复版】 ======================
# 文件路径：src/adami_kernel/web/otel.py
# 版本：v2.1（OTEL 完全防御 + Agent Lightning 兼容）
# 修复目标：解决 _HTTPStabilityMode ImportError，兼容 Agent Lightning 带来的新版 OTEL

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExporter
from opentelemetry.trace import Status, StatusCode

# ====================== 【Bug 1 核心修复】使用统一配置中心 ======================
from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.observability.otel_export_policy import (
    RedactingSpanExporter,
    resolve_trace_sampler,
)

# =================================================================================

logger = logging.getLogger("AdamI-OpenTelemetry")


def _wbotel_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# ====================== 【本次核心修复】防御性 OTEL  instrumentation 导入 ======================
# 解决 Agent Lightning 依赖的新版 opentelemetry-instrumentation-fastapi 导致的 _HTTPStabilityMode 错误
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    _INSTRUMENTORS_AVAILABLE = True
except ImportError as e:
    # Optional stack: base ``opentelemetry`` is required; auto-instrumentation packages are not.
    logger.debug(boot_t("boot.log.otel_instr_failed", detail=str(e)))
    _INSTRUMENTORS_AVAILABLE = False

    class NoopFastAPIInstrumentor:
        def instrument(self):
            pass

        def uninstrument(self):
            pass

    class NoopHTTPXClientInstrumentor:
        def instrument(self):
            pass

        def uninstrument(self):
            pass

    FastAPIInstrumentor = NoopFastAPIInstrumentor
    HTTPXClientInstrumentor = NoopHTTPXClientInstrumentor
# =================================================================================

_HTTP_AUTO_INSTRUMENTED = False


def _trace_sampler_from_settings():
    return resolve_trace_sampler(
        adami_sampler=getattr(settings, "ADAMI_OTEL_TRACES_SAMPLER", None),
        adami_ratio=float(getattr(settings, "ADAMI_OTEL_TRACES_SAMPLER_RATIO", 1.0)),
    )


def _redacting_exporter(inner: SpanExporter) -> SpanExporter:
    enabled = bool(getattr(settings, "ADAMI_OTEL_EXPORT_REDACT_ENABLED", True))
    max_len = int(getattr(settings, "ADAMI_OTEL_EXPORT_ATTR_VALUE_MAX_LEN", 2048))
    return RedactingSpanExporter(inner, max_value_len=max_len, enabled=enabled)


def _register_batch_processor(exporter: SpanExporter) -> None:
    trace.get_tracer_provider().add_span_processor(
        BatchSpanProcessor(_redacting_exporter(exporter))
    )


class NullSpanExporter(SpanExporter):
    """Drop spans (used to keep CLI output clean)."""

    def export(self, spans):  # type: ignore[override]
        return None

    def shutdown(self):  # type: ignore[override]
        return None


def _log_export_policy() -> None:
    try:
        prov = trace.get_tracer_provider()
        desc = getattr(getattr(prov, "sampler", None), "get_description", lambda: "?")()
        logger.info(
            _wbotel_t(
                "wbotel.log.trace_sampler",
                description=str(desc),
            )
        )
        logger.info(
            _wbotel_t(
                "wbotel.log.trace_export_redact",
                enabled=str(bool(getattr(settings, "ADAMI_OTEL_EXPORT_REDACT_ENABLED", True))),
                max_len=str(int(getattr(settings, "ADAMI_OTEL_EXPORT_ATTR_VALUE_MAX_LEN", 2048))),
            )
        )
    except Exception as e:
        logger.debug(_wbotel_t("wbotel.debug.trace_policy_log_skip", e=e))


def _apply_http_auto_instrumentation() -> None:
    """Attach FastAPI + HTTPX instrumentors once (safe after TracerProvider is set)."""
    global _HTTP_AUTO_INSTRUMENTED
    if _HTTP_AUTO_INSTRUMENTED or not _INSTRUMENTORS_AVAILABLE:
        return
    try:
        FastAPIInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()
        _HTTP_AUTO_INSTRUMENTED = True
        logger.info(_wbotel_t("wbotel.log.http_instrumentation"))
    except Exception as e:
        logger.warning(_wbotel_t("wbotel.warn.http_instrumentation", e=e))


class AdamIOtel:
    """AdamI 工业级 OpenTelemetry 追踪器（Phase 4 核心 - OTLP gRPC）
    【已修复】gRPC exporter UNAVAILABLE 时自动回退到 ConsoleSpanExporter
    【本次新增】Agent Lightning 完全兼容 + 防御性 instrumentation 导入
    【技能全链路 Span 追踪】生成、验证、写入、加载
    """

    _tracer = None
    _initialized = False

    @classmethod
    def init(cls):
        if cls._initialized:
            return
        try:
            if not settings.ADAMI_ENABLE_OBSERVABILITY:
                trace.set_tracer_provider(TracerProvider(sampler=_trace_sampler_from_settings()))
                _register_batch_processor(NullSpanExporter())
                cls._tracer = trace.get_tracer("adami-kernel")
                _log_export_policy()
                _apply_http_auto_instrumentation()
                cls._initialized = True
                return

            exporter_mode = (
                (getattr(settings, "ADAMI_OTEL_EXPORTER", "console") or "console").strip().lower()
            )
            if exporter_mode != "otlp":
                trace.set_tracer_provider(TracerProvider(sampler=_trace_sampler_from_settings()))
                if bool(getattr(settings, "ADAMI_OTEL_CONSOLE_EXPORT_ENABLED", False)):
                    logger.info(boot_t("boot.log.otel_console_default"))
                    _register_batch_processor(ConsoleSpanExporter())
                else:
                    _register_batch_processor(NullSpanExporter())
                cls._tracer = trace.get_tracer("adami-kernel")
                _log_export_policy()
                _apply_http_auto_instrumentation()
                cls._initialized = True
                return

            # ====================== 关键修复：设置 service.name ======================
            resource = Resource.create(
                {
                    "service.name": "adami-kernel",
                    "service.version": "1.0",
                    "deployment.environment": "production",
                }
            )
            # =========================================================================

            # ====================== 【Bug 1 核心修复】统一配置读取 OTLP Endpoint ======================
            endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            # =================================================================================

            trace.set_tracer_provider(
                TracerProvider(sampler=_trace_sampler_from_settings(), resource=resource)
            )
            _register_batch_processor(exporter)

            cls._tracer = trace.get_tracer("adami-kernel")
            _apply_http_auto_instrumentation()
            _log_export_policy()

            logger.info(_wbotel_t("wbotel.log.otlp", endpoint=endpoint))
            logger.info(_wbotel_t("wbotel.log.jaeger"))
            logger.info(_wbotel_t("wbotel.log.svc"))
            cls._initialized = True
        except Exception as e:
            logger.warning(_wbotel_t("wbotel.warn.grpc_fallback", e=e))
            trace.set_tracer_provider(TracerProvider(sampler=_trace_sampler_from_settings()))
            if bool(getattr(settings, "ADAMI_OTEL_CONSOLE_EXPORT_ENABLED", False)):
                _register_batch_processor(ConsoleSpanExporter())
            else:
                _register_batch_processor(NullSpanExporter())
            cls._tracer = trace.get_tracer("adami-kernel")
            _log_export_policy()
            _apply_http_auto_instrumentation()
            cls._initialized = True

    @classmethod
    def get_tracer(cls):
        if not cls._initialized:
            cls.init()
        return cls._tracer

    @classmethod
    def start_span(cls, name: str, attributes: dict = None):
        tracer = cls.get_tracer()
        span = tracer.start_span(name)
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
        return span

    @classmethod
    def record_error(cls, span, error: Exception):
        span.set_status(Status(StatusCode.ERROR, str(error)))
        span.record_exception(error)

    # ====================== 【新增】技能生成全链路 Span 追踪 ======================
    @classmethod
    def start_skill_generation_span(cls, skill_name: str):
        """技能生成阶段 Span（Factory 调用）"""
        span = cls.start_span(f"skill.generation.{skill_name}")
        span.set_attribute("skill.name", skill_name)
        span.set_attribute("phase", "generation")
        return span

    @classmethod
    def start_validation_span(cls, skill_name: str):
        """技能验证阶段 Span（Validator / Builder 调用）"""
        span = cls.start_span(f"skill.validation.{skill_name}")
        span.set_attribute("skill.name", skill_name)
        span.set_attribute("phase", "validation")
        return span

    @classmethod
    def start_write_span(cls, skill_name: str):
        """技能写入阶段 Span（Builder 调用）"""
        span = cls.start_span(f"skill.write.{skill_name}")
        span.set_attribute("skill.name", skill_name)
        span.set_attribute("phase", "write")
        return span

    @classmethod
    def start_load_span(cls, skill_name: str):
        """技能加载阶段 Span（Loader 调用）"""
        span = cls.start_span(f"skill.load.{skill_name}")
        span.set_attribute("skill.name", skill_name)
        span.set_attribute("phase", "load")
        return span

    # =================================================================================


# --- END OF FILE otel.py ---
# 文件路径：src/adami_kernel/web/otel.py
# 版本：v2.1（OTEL 完全防御 + Agent Lightning 兼容）
