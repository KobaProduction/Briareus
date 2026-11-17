//! Bounded, opt-in official OpenTelemetry signals for Rust MCP Hands.
//!
//! No raw MCP arguments, account credentials, query filters, provider responses,
//! or arbitrary error messages are exported. This module is intentionally
//! independent of the provider API and of Management audit persistence.
use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant, SystemTime},
};

use opentelemetry::{
    KeyValue,
    logs::{LogRecord, Logger, LoggerProvider as _},
    metrics::{Counter, Gauge, Histogram, MeterProvider as _},
    trace::{Span, Status, Tracer as _, TracerProvider as _},
};
use opentelemetry_otlp::{Protocol, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::{
    Resource,
    logs::{BatchConfigBuilder as LogBatchConfig, BatchLogProcessor, SdkLogger, SdkLoggerProvider},
    metrics::{PeriodicReader, SdkMeterProvider},
    trace::{
        BatchConfigBuilder as SpanBatchConfig, BatchSpanProcessor, SdkTracer, SdkTracerProvider,
    },
};
use reqwest::Url;

use crate::HandError;

const TRACE_QUEUE_MAX: usize = 64;
const LOG_QUEUE_MAX: usize = 32;
const EXPORT_BATCH_MAX: usize = 16;
const EXPORT_TIMEOUT: Duration = Duration::from_secs(3);

#[derive(Clone, Debug)]
pub struct TelemetryConfig {
    pub endpoint: String,
    pub bearer_token: String,
    pub environment: String,
    pub service_name: String,
    pub scope: String,
    pub namespace: String,
    pub metric_interval: Duration,
}

impl TelemetryConfig {
    pub fn validate(&self) -> Result<(), HandError> {
        if self.endpoint.is_empty() {
            return Ok(());
        }
        let url = Url::parse(&self.endpoint).map_err(|_| HandError::Configuration)?;
        if !matches!(url.scheme(), "http" | "https")
            || url.host_str().is_none()
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || self.environment.is_empty()
            || self.environment.len() > 63
            || self.service_name.is_empty()
            || self.service_name.len() > 128
            || self.scope.is_empty()
            || self.scope.len() > 64
            || self.metric_interval < Duration::from_secs(1)
            || self.metric_interval > Duration::from_secs(300)
            || !self
                .scope
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
            || !self.environment.bytes().all(|byte| {
                byte.is_ascii_lowercase()
                    || byte.is_ascii_digit()
                    || matches!(byte, b'.' | b'_' | b'-')
            })
        {
            return Err(HandError::Configuration);
        }
        Ok(())
    }

    fn signal_url(&self, signal: &str) -> Result<String, HandError> {
        self.validate()?;
        if !matches!(signal, "traces" | "metrics" | "logs") {
            return Err(HandError::Configuration);
        }
        let mut base = self.endpoint.trim_end_matches('/').to_owned();
        for path in ["/v1/traces", "/v1/logs", "/v1/metrics"] {
            if base.ends_with(path) {
                base.truncate(base.len() - path.len());
                break;
            }
        }
        Ok(format!("{base}/v1/{signal}"))
    }
}

#[derive(Clone)]
pub struct Telemetry {
    inner: Option<Arc<TelemetryInner>>,
}

struct TelemetryInner {
    tracer_provider: SdkTracerProvider,
    meter_provider: SdkMeterProvider,
    logger_provider: SdkLoggerProvider,
    tracer: SdkTracer,
    logger: SdkLogger,
    calls: Counter<u64>,
    failures: Counter<u64>,
    rejections: Counter<u64>,
    duration: Histogram<f64>,
    runtime_up: Gauge<u64>,
}

impl Telemetry {
    pub fn start(config: TelemetryConfig) -> Result<Self, HandError> {
        config.validate()?;
        if config.endpoint.is_empty() {
            return Ok(Self { inner: None });
        }
        let headers = if config.bearer_token.is_empty() {
            HashMap::new()
        } else {
            HashMap::from([(
                "Authorization".to_owned(),
                format!("Bearer {}", config.bearer_token),
            )])
        };
        // The OTLP bearer token must never follow a collector 3xx redirect.
        // Reuse one very small connection pool across all three exporters.
        let collector = reqwest_otlp::blocking::Client::builder()
            .timeout(EXPORT_TIMEOUT)
            .pool_max_idle_per_host(2)
            .redirect(reqwest_otlp::redirect::Policy::none())
            .build()
            .map_err(|_| HandError::Configuration)?;
        let traces_url = config.signal_url("traces")?;
        let metrics_url = config.signal_url("metrics")?;
        let logs_url = config.signal_url("logs")?;
        let scope = config.scope.clone();
        let resource = Resource::builder_empty()
            .with_attributes([
                KeyValue::new("service.name", config.service_name),
                KeyValue::new("deployment.environment.name", config.environment),
                KeyValue::new("service.namespace", config.namespace),
                KeyValue::new("mcp.scope", scope.clone()),
                KeyValue::new("service.version", env!("CARGO_PKG_VERSION")),
            ])
            .build();

        let spans = opentelemetry_otlp::SpanExporter::builder()
            .with_http()
            .with_http_client(collector.clone())
            .with_endpoint(traces_url)
            .with_protocol(Protocol::HttpBinary)
            .with_headers(headers.clone())
            .with_timeout(EXPORT_TIMEOUT)
            .with_max_request_body_size(1024 * 1024)
            .build()
            .map_err(|_| HandError::Configuration)?;
        let span_batch = SpanBatchConfig::default()
            .with_max_queue_size(TRACE_QUEUE_MAX)
            .with_max_export_batch_size(EXPORT_BATCH_MAX)
            .with_scheduled_delay(Duration::from_millis(500))
            .build();
        let tracer_provider = SdkTracerProvider::builder()
            .with_resource(resource.clone())
            .with_span_processor(
                BatchSpanProcessor::builder(spans)
                    .with_batch_config(span_batch)
                    .build(),
            )
            .build();
        let tracer = tracer_provider.tracer("briareus.signoz.rust");

        let metrics = opentelemetry_otlp::MetricExporter::builder()
            .with_http()
            .with_http_client(collector.clone())
            .with_endpoint(metrics_url)
            .with_protocol(Protocol::HttpBinary)
            .with_headers(headers.clone())
            .with_timeout(EXPORT_TIMEOUT)
            .with_max_request_body_size(1024 * 1024)
            .build()
            .map_err(|_| HandError::Configuration)?;
        let meter_provider = SdkMeterProvider::builder()
            .with_resource(resource.clone())
            .with_reader(
                PeriodicReader::builder(metrics)
                    .with_interval(config.metric_interval)
                    .build(),
            )
            .build();
        let meter = meter_provider.meter("briareus.signoz.rust");
        let calls = meter.u64_counter("mcp.tool.calls").build();
        let failures = meter.u64_counter("mcp.tool.errors").build();
        let rejections = meter.u64_counter("mcp.tool.rejections").build();
        let duration = meter
            .f64_histogram("mcp.tool.duration")
            .with_unit("ms")
            .build();
        meter
            .u64_counter("mcp.runtime.started")
            .build()
            .add(1, &[KeyValue::new("mcp.scope", scope.clone())]);
        let runtime_up = meter.u64_gauge("mcp.runtime.up").build();
        runtime_up.record(1, &[KeyValue::new("mcp.scope", scope)]);

        let logs = opentelemetry_otlp::LogExporter::builder()
            .with_http()
            .with_http_client(collector)
            .with_endpoint(logs_url)
            .with_protocol(Protocol::HttpBinary)
            .with_headers(headers)
            .with_timeout(EXPORT_TIMEOUT)
            .with_max_request_body_size(1024 * 1024)
            .build()
            .map_err(|_| HandError::Configuration)?;
        let log_batch = LogBatchConfig::default()
            .with_max_queue_size(LOG_QUEUE_MAX)
            .with_max_export_batch_size(EXPORT_BATCH_MAX)
            .with_scheduled_delay(Duration::from_millis(500))
            .build();
        let logger_provider = SdkLoggerProvider::builder()
            .with_resource(resource)
            .with_log_processor(
                BatchLogProcessor::builder(logs)
                    .with_batch_config(log_batch)
                    .build(),
            )
            .build();
        let logger = logger_provider.logger("briareus.signoz.rust");

        Ok(Self {
            inner: Some(Arc::new(TelemetryInner {
                tracer_provider,
                meter_provider,
                logger_provider,
                tracer,
                logger,
                calls,
                failures,
                rejections,
                duration,
                runtime_up,
            })),
        })
    }

    pub fn enabled(&self) -> bool {
        self.inner.is_some()
    }

    pub fn record_outcome(
        &self,
        scope: &'static str,
        tool: &'static str,
        started: Instant,
        outcome: Result<(), &HandError>,
    ) {
        let Some(inner) = &self.inner else { return };
        let elapsed = started.elapsed();
        let rejected = matches!(outcome, Err(HandError::Invalid(_)));
        let status = if outcome.is_ok() { "success" } else { "error" };
        let attrs = [
            KeyValue::new("mcp.scope", scope),
            KeyValue::new("mcp.tool", tool),
            KeyValue::new("mcp.status", status),
        ];
        inner.calls.add(1, &attrs);
        inner.runtime_up.record(1, &attrs[..1]);
        inner.duration.record(elapsed.as_secs_f64() * 1000., &attrs);
        if outcome.is_err() {
            if rejected {
                inner.rejections.add(1, &attrs);
            } else {
                inner.failures.add(1, &attrs);
            }
        }

        let now = SystemTime::now();
        let started_at = now.checked_sub(elapsed).unwrap_or(now);
        let mut span = inner
            .tracer
            .span_builder(format!("mcp.tool.{tool}"))
            .with_start_time(started_at)
            .start(&inner.tracer);
        span.set_attributes(attrs.to_vec());
        if outcome.is_err() {
            span.set_status(Status::error("Rust Hand tool failed"));
        }
        span.end_with_timestamp(now);

        if outcome.is_err() {
            let mut record = inner.logger.create_log_record();
            record.set_body("Rust Hand tool call failed".into());
            record.set_severity_number(opentelemetry::logs::Severity::Error);
            record.add_attributes([("mcp.scope", scope), ("mcp.tool", tool)]);
            inner.logger.emit(record);
        }
    }

    /// Forces bounded export on shutdown. Call off the Tokio worker thread.
    pub fn shutdown(&self) {
        let Some(inner) = &self.inner else { return };
        let _ = inner.tracer_provider.shutdown_with_timeout(EXPORT_TIMEOUT);
        let _ = inner.meter_provider.shutdown();
        let _ = inner.logger_provider.shutdown_with_timeout(EXPORT_TIMEOUT);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base(endpoint: &str) -> TelemetryConfig {
        TelemetryConfig {
            endpoint: endpoint.into(),
            bearer_token: "synthetic-secret".into(),
            environment: "test".into(),
            service_name: "briareus-test".into(),
            scope: "signoz".into(),
            namespace: "briareus".into(),
            metric_interval: Duration::from_secs(1),
        }
    }

    #[test]
    fn disabled_has_no_allocated_exporters() {
        let telemetry = Telemetry::start(base("")).unwrap();
        assert!(!telemetry.enabled());
        telemetry.record_outcome("signoz", "signoz_sources", Instant::now(), Ok(()));
    }

    #[test]
    fn signal_path_is_canonical_and_url_is_bounded() {
        assert_eq!(
            base("http://127.0.0.1:4318/v1/logs")
                .signal_url("traces")
                .unwrap(),
            "http://127.0.0.1:4318/v1/traces"
        );
        for forbidden in [
            "http://user:pass@localhost",
            "file:///tmp/foo",
            "https://example.com?token=secret",
        ] {
            assert!(base(forbidden).validate().is_err());
        }
        let mut bad_scope = base("http://localhost:4318");
        bad_scope.scope = "other
secret"
            .into();
        assert!(bad_scope.validate().is_err());
        let mut invalid = base("http://localhost:4318");
        invalid.metric_interval = Duration::from_millis(10);
        assert!(invalid.validate().is_err());
    }
}
