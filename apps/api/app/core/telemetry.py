"""OpenTelemetry instrumentation setup."""

import logging

from app.config import settings

logger = logging.getLogger(__name__)
_configured = False


def setup_telemetry(app, service_name: str | None = None) -> None:
    global _configured
    if _configured:
        return

    service = service_name or getattr(settings, "otel_service_name", "agenthub-api")
    endpoint = getattr(settings, "otel_endpoint", None)

    if not endpoint:
        logger.info("OTEL_ENDPOINT not set — telemetry disabled")
        _configured = True
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)

        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
            from app.db.session import engine
            SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine if hasattr(engine, "sync_engine") else None)
        except Exception as e:
            logger.debug("SQLAlchemy instrumentation skipped: %s", e)

        logger.info("OpenTelemetry configured for %s → %s", service, endpoint)
    except ImportError:
        logger.warning("OpenTelemetry packages not installed — telemetry disabled")
    except Exception as e:
        logger.warning("Telemetry setup failed: %s", e)

    _configured = True
