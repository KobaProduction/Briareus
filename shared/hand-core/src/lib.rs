//! Common boundaries for independently deployed Rust MCP Hands.
//! This crate owns HTTP safety and account resolution, not provider business logic.
pub mod accounts;
pub mod audit;

pub mod errors;
pub mod http;
pub mod provider_http_cache;
pub mod telemetry;

pub use accounts::{AccountDirectory, PanelAccountDirectory, ResolvedAccount};
pub use errors::HandError;
pub use http::JsonHttp;

pub use provider_http_cache::ProviderHttpCache;

pub use audit::{AuditReporter, AuditReporterConfig, AuditStatus};

pub use telemetry::{Telemetry, TelemetryConfig};

pub use briareus_service_discovery_rs::{DiscoveryConfig, DiscoveryRegistry, ServiceIdentity};
