//! Reusable private MCP Streamable HTTP listener for independently deployed Hands.
//! Gateway's public OAuth boundary remains a separate component.
use std::{io, sync::Arc};

use axum::{Router, routing::get};
use briareus_service_discovery_rs::ServiceIdentity;
use rmcp::{
    ServerHandler,
    transport::streamable_http_server::{
        StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager,
    },
};
use serde_json::json;

/// Private host and origin restrictions, not an alternative to public Gateway OAuth.
#[derive(Clone, Debug)]
pub struct PrivateMcpSettings {
    pub allowed_hosts: Vec<String>,
    pub allowed_origins: Vec<String>,
}

impl PrivateMcpSettings {
    pub fn from_csv(hosts: Option<&str>, origins: Option<&str>) -> Self {
        fn split(value: Option<&str>, defaults: &[&str]) -> Vec<String> {
            value
                .filter(|value| !value.trim().is_empty())
                .map(|value| {
                    value
                        .split(',')
                        .map(str::trim)
                        .filter(|part| !part.is_empty())
                        .map(str::to_owned)
                        .collect()
                })
                .unwrap_or_else(|| defaults.iter().map(|value| (*value).to_owned()).collect())
        }
        Self {
            allowed_hosts: split(hosts, &["localhost:*", "127.0.0.1:*", "[::1]:*"]),
            allowed_origins: split(
                origins,
                &["http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*"],
            ),
        }
    }

    fn into_transport(self) -> StreamableHttpServerConfig {
        StreamableHttpServerConfig::default()
            .with_allowed_hosts(self.allowed_hosts)
            .with_allowed_origins(self.allowed_origins)
            .with_legacy_session_mode(false)
            .with_json_response(true)
    }
}

/// Supply provider identity/environment explicitly; no service-specific literals in shared code.
/// Provider-specific diagnostics can be composed with the returned Axum Router.
pub fn private_mcp_router<H>(
    handler: H,
    identity: ServiceIdentity,
    environment: String,
    settings: PrivateMcpSettings,
) -> Router
where
    H: ServerHandler + Clone + Send + Sync + 'static,
{
    let transport = StreamableHttpService::new(
        move || Ok::<_, io::Error>(handler.clone()),
        Arc::new(LocalSessionManager::default()),
        settings.into_transport(),
    );
    Router::new()
        .route("/health", get(|| async { "ok" }))
        .route(
            "/health/discovery",
            get(move || {
                let identity = identity.clone();
                let environment = environment.clone();
                async move {
                    axum::Json(
                        json!({"service": identity, "environment": environment, "ready": true}),
                    )
                }
            }),
        )
        .nest_service("/mcp", transport)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rmcp::model::{ServerCapabilities, ServerConfig};
    use tower::ServiceExt;

    #[derive(Clone)]
    struct EmptyHandler;
    impl ServerHandler for EmptyHandler {
        fn get_info(&self) -> ServerConfig {
            ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
        }
    }

    #[tokio::test]
    async fn discovery_is_derived_from_identity_not_hardcoded() {
        let router = private_mcp_router(
            EmptyHandler,
            ServiceIdentity::new("github", "GitHub", "svc").unwrap(),
            "test".into(),
            PrivateMcpSettings::from_csv(None, None),
        );
        let request = axum::http::Request::builder()
            .uri("/health/discovery")
            .body(axum::body::Body::empty())
            .unwrap();
        let response = router.oneshot(request).await.unwrap();
        assert_eq!(response.status(), axum::http::StatusCode::OK);
        let content = axum::body::to_bytes(response.into_body(), 2048)
            .await
            .unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&content).unwrap(),
            json!({
                "service": {"id":"github", "name":"GitHub", "group":"svc"},
                "environment": "test", "ready": true,
            })
        );
    }
}
