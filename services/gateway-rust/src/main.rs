//! Native Gateway with explicit local, private-preview and public launch boundaries.
//! Public rollout still requires independent operational acceptance.
mod auth;
mod browser_sockets;
mod discovery;
mod mcp;
mod mcp_policy;
mod proxy;
mod runtime_mode;

use axum::{
    Router,
    body::Body,
    extract::State,
    http::{Request, StatusCode, header},
    response::{IntoResponse, Response},
    routing::{any, get},
};
use serde_json::json;
use std::{env, net::SocketAddr, sync::Arc, time::Duration};

use auth::ShadowOidc;
use briareus_service_discovery_rs::ServiceIdentity;
use discovery::GatewayDirectory;
use mcp::McpGateway;
use proxy::{Proxy, ProxyKind};
use runtime_mode::{GatewayMode, RuntimeConfig};

#[derive(Clone)]
struct AppState {
    mode: GatewayMode,
    node: String,
    commit: String,
    api: Proxy,
    ui: Proxy,
    auth: ShadowOidc,
    directory: GatewayDirectory,
    mcp: McpGateway,
}

async fn health(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    axum::Json(json!({"status":"ok", "node":state.node, "commit":state.commit}))
}

async fn handle(State(state): State<Arc<AppState>>, request: Request<Body>) -> Response {
    let path = request.uri().path();
    if path.starts_with("/internal/") {
        return StatusCode::NOT_FOUND.into_response();
    }
    if state.mode == GatewayMode::Public
        && let Err(status) = state.auth.validate_mcp_headers(request.headers())
    {
        return status.into_response();
    }
    if path == "/admin/api" || path.starts_with("/admin/api/") {
        return StatusCode::NOT_FOUND.into_response();
    }
    if path == "/api" || path.starts_with("/api/") {
        return state.api.forward(request, ProxyKind::Api).await;
    }
    if path == "/admin" || path.starts_with("/admin/") {
        return state.ui.forward(request, ProxyKind::Ui).await;
    }
    if let Some(path) = path.strip_prefix("/.well-known/oauth-protected-resource") {
        if request.method() == axum::http::Method::GET
            && let Some(service) = state.directory.lookup(path).await
            && let Some(metadata) = state.auth.resource_metadata(&service.identity)
        {
            if let Err(status) = state.auth.validate_mcp_headers(request.headers()) {
                return status.into_response();
            }
            return axum::Json(metadata).into_response();
        }
        return StatusCode::NOT_FOUND.into_response();
    }
    if path.ends_with("/mcp") && path != "/mcp" {
        let Some(service) = state.directory.lookup(path).await else {
            return StatusCode::NOT_FOUND.into_response();
        };
        if let Err(status) = state.auth.validate_mcp_headers(request.headers()) {
            return status.into_response();
        }
        if state.directory.discovery_configured() && !service.connected {
            return (
                StatusCode::SERVICE_UNAVAILABLE,
                axum::Json(json!({
                    "code": "service_unavailable", "service": service.identity.id,
                })),
            )
                .into_response();
        }
        // Every MCP HTTP request is authenticated *before* any session lookup.
        let token = auth::bearer_token(request.headers());
        let challenge = state
            .auth
            .challenge(&service.identity)
            .and_then(|raw| header::HeaderValue::from_str(&raw).ok())
            .unwrap_or_else(|| header::HeaderValue::from_static("Bearer"));
        let mut response = if let (Some(verifier), Some(token)) =
            (state.auth.verifier.as_ref(), token)
            && let Ok(principal) = verifier.verify(token).await
        {
            let backend_url = state.directory.backend_mcp_url(&service.identity);
            state
                .mcp
                .handle(service.identity, backend_url, &principal, request)
                .await
        } else {
            StatusCode::UNAUTHORIZED.into_response()
        };
        if response.status() == StatusCode::UNAUTHORIZED {
            response
                .headers_mut()
                .insert(header::WWW_AUTHENTICATE, challenge);
        }
        return response;
    }
    StatusCode::NOT_FOUND.into_response()
}

fn app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/api/realtime", get(browser_sockets::realtime))
        .route("/api/browser/operator/ws", get(browser_sockets::operator))
        .route(
            "/api/browser/cdp/page/{target_id}",
            get(browser_sockets::cdp),
        )
        .fallback(any(handle))
        .with_state(Arc::new(state))
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let config = RuntimeConfig::from_env()?;
    let mode = config.mode;
    let node = config.node;
    let api = Proxy::new(&config.api, "control-panel-api")?;
    let ui = Proxy::new(&config.ui, "control-panel-ui")?;
    let auth = ShadowOidc::from_env(&node)?;
    if mode != GatewayMode::LocalShadow {
        anyhow::ensure!(
            auth.verifier.is_some(),
            "Deployed Gateway requires OIDC verifier"
        );
    }
    let _websocket_limit = browser_sockets::websocket_limit()?;
    let catalog: Vec<ServiceIdentity> = serde_json::from_str(include_str!("../catalog.json"))?;
    anyhow::ensure!(
        !catalog.is_empty()
            && catalog.iter().all(|entry| {
                ServiceIdentity::new(&entry.id, &entry.name, &entry.group).is_ok()
            }),
        "Invalid static Gateway catalog"
    );
    let directory = GatewayDirectory::from_env(catalog)?;
    // Existing Control Panel API owns browser configuration and node
    // provisioning for this compatibility release. Do not initialize a new
    // browser client or machine registration during a transport-only cutover.
    let policy = match env::var("BRIAREUS_SERVICE_TOKEN") {
        Ok(token) => mcp_policy::McpPolicy::new(&config.api, &token)?,
        Err(_) => mcp_policy::McpPolicy::default(),
    };
    let mcp = McpGateway::new(auth.public_host(), auth.public_origin(), policy);
    let state = AppState {
        mode,
        directory,
        mcp,
        node,
        auth,
        commit: env::var("BUILD_SHA").unwrap_or_else(|_| "unknown".into()),
        api,
        ui,
    };
    let listener = tokio::net::TcpListener::bind(SocketAddr::new(config.ip, config.port)).await?;
    let (shutdown, notification) = tokio::sync::oneshot::channel();
    let server = axum::serve(listener, app(state))
        .with_graceful_shutdown(async move {
            let _ = notification.await;
        })
        .into_future();
    tokio::pin!(server);
    tokio::select! {
        result = &mut server => result?,
        _ = shutdown_signal() => {
            let _ = shutdown.send(());
            // The Compose stop grace is 25 seconds. Do not retain an open
            // SSE response indefinitely and force the orchestrator to SIGKILL.
            match tokio::time::timeout(Duration::from_secs(20), &mut server).await {
                Ok(result) => result?,
                Err(_) => eprintln!("Gateway shutdown drain deadline elapsed"),
            }
        }
    }
    Ok(())
}

async fn shutdown_signal() {
    #[cfg(unix)]
    {
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("SIGTERM handler");
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {},
            _ = terminate.recv() => {},
        }
    }
    #[cfg(not(unix))]
    {
        let _ = tokio::signal::ctrl_c().await;
    }
}
