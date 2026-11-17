//! PRIVATE, LOOPBACK-ONLY gateway porting fixture. NOT production ready.
//! OAuth, MCP session bridging and WebSocket parity are required before exposure.
mod auth;
mod browser_sockets;
mod discovery;
mod mcp;
mod proxy;

use axum::{
    Router,
    body::Body,
    extract::State,
    http::{Request, StatusCode, header},
    response::{IntoResponse, Response},
    routing::{any, get},
};
use serde_json::json;
use std::{
    env,
    net::{IpAddr, SocketAddr},
    sync::Arc,
};

use auth::ShadowOidc;
use briareus_service_discovery_rs::ServiceIdentity;
use discovery::GatewayDirectory;
use mcp::McpGateway;
use proxy::{Proxy, ProxyKind};

#[derive(Clone)]
struct AppState {
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
            return axum::Json(metadata).into_response();
        }
        return StatusCode::NOT_FOUND.into_response();
    }
    if path.ends_with("/mcp") && path != "/mcp" {
        let Some(service) = state.directory.lookup(path).await else {
            return StatusCode::NOT_FOUND.into_response();
        };
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
        let token = request
            .headers()
            .get(header::AUTHORIZATION)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.strip_prefix("Bearer "));
        if let (Some(verifier), Some(token)) = (state.auth.verifier.as_ref(), token)
            && verifier.verify(token).await.is_ok()
        {
            let backend_url = state.directory.backend_mcp_url(&service.identity);
            return state
                .mcp
                .handle(service.identity, backend_url, request)
                .await;
        }
        let mut response = StatusCode::UNAUTHORIZED.into_response();
        let challenge = state
            .auth
            .challenge(&service.identity)
            .and_then(|raw| header::HeaderValue::from_str(&raw).ok())
            .unwrap_or_else(|| header::HeaderValue::from_static("Bearer"));
        response
            .headers_mut()
            .insert(header::WWW_AUTHENTICATE, challenge);
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
    // Prevent accidental public use of an incomplete replacement.
    anyhow::ensure!(
        env::var("RUST_GATEWAY_SHADOW_ONLY").as_deref() == Ok("true"),
        "Rust Gateway requires explicit local shadow mode"
    );
    let host = env::var("BIND_HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let ip: IpAddr = host.parse()?;
    anyhow::ensure!(
        ip.is_loopback(),
        "Rust Gateway shadow may bind only to loopback"
    );
    let port: u16 = env::var("PORT")
        .unwrap_or_else(|_| "18082".into())
        .parse()?;
    let node = env::var("BRIAREUS_NODE_ID")?;
    anyhow::ensure!(!node.trim().is_empty(), "BRIAREUS_NODE_ID is required");
    let api = Proxy::new(&env::var("CONTROL_PANEL_URL")?, "management")?;
    let ui = Proxy::new(&env::var("CONTROL_PANEL_UI_URL")?, "management-ui")?;
    let auth = ShadowOidc::from_env(&node)?;
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
    let state = AppState {
        directory,
        mcp: McpGateway::new(),
        node,
        auth,
        commit: env::var("BUILD_SHA").unwrap_or_else(|_| "unknown".into()),
        api,
        ui,
    };
    let listener = tokio::net::TcpListener::bind(SocketAddr::new(ip, port)).await?;
    axum::serve(listener, app(state))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}
