//! Bounded, best-effort invocation audit shared by Rust Hands.
//!
//! The Control Panel retains audit authority. No tool input, upstream payload,
//! credentials, or live telemetry are copied into the audit queue.
use std::{
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};

use serde::Serialize;
use serde_json::{Value, json};
use tokio::sync::{mpsc, oneshot};

use crate::{HandError, JsonHttp};

const BATCH_MAX: usize = 32;
const BATCH_WINDOW: Duration = Duration::from_millis(50);
pub const DEFAULT_AUDIT_QUEUE: usize = 64;
pub const MAX_AUDIT_QUEUE: usize = 256;
const SAFE_ARGUMENTS: &str = r#"{"detail":"Rust Hand arguments omitted from audit"}"#;
const SAFE_RESULT: &str = r#"{"detail":"Rust Hand result omitted from audit"}"#;

#[derive(Clone, Copy)]
pub struct AuditReporterConfig {
    pub enabled: bool,
    pub queue_capacity: usize,
}

impl Default for AuditReporterConfig {
    fn default() -> Self {
        Self {
            enabled: false, // Preview starts without writing production audit history.
            queue_capacity: DEFAULT_AUDIT_QUEUE,
        }
    }
}

impl AuditReporterConfig {
    pub fn validate(self) -> Result<Self, HandError> {
        if !(1..=MAX_AUDIT_QUEUE).contains(&self.queue_capacity) {
            return Err(HandError::Configuration);
        }
        Ok(self)
    }
}

#[derive(Serialize)]
struct InvocationEvent {
    request_id: &'static str,
    module: String,
    tool: String,
    account_id: String,
    provider: &'static str,
    status: &'static str,
    duration_ms: f64,
    error_type: &'static str,
    arguments_json: &'static str,
    result_json: &'static str,
    error_message: &'static str,
}

enum AuditMessage {
    Event(InvocationEvent),
    Flush(oneshot::Sender<()>),
}

#[derive(Clone)]
pub struct AuditReporter {
    sender: Option<mpsc::Sender<AuditMessage>>,
    dropped: Arc<AtomicU64>,
    failed_batches: Arc<AtomicU64>,
}

fn safe_account_id(value: &str) -> String {
    // An invalid account selector can contain a pasted credential or token.
    // Do not retain arbitrary caller-controlled text in audit history.
    if value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        value.to_owned()
    } else {
        "<omitted>".into()
    }
}

fn safe_error_type(error: &HandError) -> &'static str {
    match error {
        HandError::Invalid(_) => "caller_rejected:Invalid",
        HandError::AccountUnavailable => "AccountUnavailable",
        HandError::Unauthorized => "Unauthorized",
        HandError::Forbidden => "Forbidden",
        HandError::UpstreamStatus(_) => "UpstreamStatus",
        HandError::Transport => "Transport",
        HandError::InvalidResponse => "InvalidResponse",
        HandError::Configuration => "Configuration",
        HandError::MissingToken => "MissingToken",
    }
}

impl AuditReporter {
    pub fn start(
        panel_url: &str,
        service_token: &str,
        config: AuditReporterConfig,
    ) -> Result<Self, HandError> {
        let config = config.validate()?;
        let dropped = Arc::new(AtomicU64::new(0));
        let failed_batches = Arc::new(AtomicU64::new(0));
        let sender = if config.enabled {
            let http = JsonHttp::new(
                panel_url,
                "Authorization",
                &format!("Bearer {service_token}"),
                true,
                None,
            )?;
            let (sender, receiver) = mpsc::channel(config.queue_capacity);
            let failures = Arc::clone(&failed_batches);
            tokio::spawn(async move { drain_audit(http, receiver, failures).await });
            Some(sender)
        } else {
            None
        };
        Ok(Self {
            sender,
            dropped,
            failed_batches,
        })
    }

    pub fn record_outcome<T>(
        &self,
        module: &str,
        tool: &str,
        account_id: &str,
        started: Instant,
        result: &Result<T, HandError>,
    ) {
        let Some(sender) = &self.sender else { return };
        let error = result.as_ref().err();
        let event = InvocationEvent {
            request_id: "",
            module: module.to_owned(),
            tool: tool.to_owned(),
            account_id: safe_account_id(account_id),
            provider: "",
            status: if error.is_some() { "error" } else { "success" },
            duration_ms: started.elapsed().as_secs_f64() * 1000.,
            error_type: error.map_or("", safe_error_type),
            arguments_json: SAFE_ARGUMENTS,
            result_json: if error.is_none() { SAFE_RESULT } else { "" },
            error_message: if error.is_some() {
                "Rust Hand tool call failed; details omitted from audit"
            } else {
                ""
            },
        };
        if sender.try_send(AuditMessage::Event(event)).is_err() {
            let dropped = self.dropped.fetch_add(1, Ordering::Relaxed) + 1;
            if dropped.is_power_of_two() {
                eprintln!("Rust Hand audit queue full or closed, dropped_count={dropped}");
            }
        }
    }

    /// Complete queued delivery attempts before the runtime is stopped.
    /// A successful barrier confirms processing, not acceptance by Control Panel.
    pub async fn flush(&self, limit: Duration) -> bool {
        let Some(sender) = &self.sender else {
            return true;
        };
        let before = self.failed_batches();
        let (done, ack) = oneshot::channel();
        let work = async {
            sender.send(AuditMessage::Flush(done)).await.ok()?;
            ack.await.ok()
        };
        tokio::time::timeout(limit, work)
            .await
            .ok()
            .flatten()
            .is_some()
            && self.failed_batches() == before
    }

    pub fn dropped_count(&self) -> u64 {
        self.dropped.load(Ordering::Relaxed)
    }

    pub fn failed_batches(&self) -> u64 {
        self.failed_batches.load(Ordering::Relaxed)
    }
}

async fn drain_audit(
    http: JsonHttp,
    mut receiver: mpsc::Receiver<AuditMessage>,
    failed_batches: Arc<AtomicU64>,
) {
    while let Some(item) = receiver.recv().await {
        let first = match item {
            AuditMessage::Event(event) => event,
            AuditMessage::Flush(ack) => {
                let _ = ack.send(());
                continue;
            }
        };
        let mut batch = Vec::with_capacity(BATCH_MAX);
        batch.push(first);
        let mut barrier = None;
        let deadline = tokio::time::Instant::now() + BATCH_WINDOW;
        while batch.len() < BATCH_MAX {
            match tokio::time::timeout_at(deadline, receiver.recv()).await {
                Ok(Some(AuditMessage::Event(next))) => batch.push(next),
                Ok(Some(AuditMessage::Flush(ack))) => {
                    barrier = Some(ack);
                    break;
                }
                Ok(None) | Err(_) => break,
            }
        }
        let payload: Value = json!({ "events": batch });
        if http
            .post_no_content(&["internal", "events", "batch"], &payload)
            .await
            .is_err()
        {
            let failed = failed_batches.fetch_add(1, Ordering::Relaxed) + 1;
            if failed.is_power_of_two() {
                // The error is intentionally suppressed: upstream responses
                // could contain sensitive information or arbitrary text.
                eprintln!("Rust Hand audit batch failed, failed_batches={failed}");
            }
        }
        if let Some(ack) = barrier {
            let _ = ack.send(());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_unbounded_memory_configuration() {
        assert!(
            AuditReporterConfig {
                enabled: true,
                queue_capacity: 0
            }
            .validate()
            .is_err()
        );
        assert!(
            AuditReporterConfig {
                enabled: false,
                queue_capacity: 257
            }
            .validate()
            .is_err()
        );
        assert!(
            AuditReporterConfig {
                enabled: false,
                queue_capacity: 64
            }
            .validate()
            .is_ok()
        );
    }

    #[test]
    fn account_selector_omits_arbitrary_or_sensitive_text() {
        assert_eq!(safe_account_id("test-account_id.1"), "test-account_id.1");
        assert_eq!(safe_account_id("Bearer super-secret"), "<omitted>");
        assert_eq!(safe_account_id("test\nvalue"), "<omitted>");
        assert_eq!(safe_account_id(&"a".repeat(129)), "<omitted>");
    }

    #[tokio::test]
    async fn bounded_queue_drops_without_blocking_an_mcp_response() {
        let audit = AuditReporter::start(
            "http://127.0.0.1:1",
            "synthetic-secret",
            AuditReporterConfig {
                enabled: true,
                queue_capacity: 1,
            },
        )
        .unwrap();
        for _ in 0..1024 {
            audit.record_outcome(
                "signoz",
                "signoz_sources",
                "",
                Instant::now(),
                &Result::<Value, HandError>::Ok(json!({ "secret": "must-not-be-audited" })),
            );
        }
        assert!(audit.dropped_count() > 0);
    }

    #[tokio::test]
    async fn unavailable_control_panel_does_not_block_tools_or_leak_data() {
        let audit = AuditReporter::start(
            "http://127.0.0.1:1",
            "synthetic-panel-token",
            AuditReporterConfig {
                enabled: true,
                queue_capacity: 4,
            },
        )
        .unwrap();
        audit.record_outcome(
            "signoz",
            "signoz_search_logs",
            "valid-alias",
            Instant::now(),
            &Result::<Value, HandError>::Err(HandError::Transport),
        );
        assert!(!audit.flush(Duration::from_secs(3)).await);
        assert_eq!(audit.failed_batches(), 1);
    }

    #[tokio::test]
    async fn disabled_reporter_keeps_no_events() {
        let audit = AuditReporter::start(
            "http://127.0.0.1:1",
            "synthetic-panel-token",
            AuditReporterConfig::default(),
        )
        .unwrap();
        audit.record_outcome(
            "signoz",
            "signoz_sources",
            "",
            Instant::now(),
            &Result::<Value, HandError>::Ok(json!({"secret": "must-not-be-recorded"})),
        );
        assert!(audit.flush(Duration::from_millis(10)).await);
        assert_eq!(audit.dropped_count(), 0);
        assert_eq!(audit.failed_batches(), 0);
    }

    #[test]
    fn error_categories_are_static() {
        assert_eq!(
            safe_error_type(&HandError::Invalid("secret".into())),
            "caller_rejected:Invalid"
        );
        assert_eq!(safe_error_type(&HandError::Transport), "Transport");
    }
}
