//! PRIVATE, LOOPBACK-ONLY gateway porting fixture. NOT production ready.
//! OAuth, MCP session bridging and WebSocket parity are required before exposure.
mod auth;
mod browser_sockets;
mod discovery;
mod identity_routes;
mod mcp;
mod node_registration;
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
    identity: Option<identity_routes::IdentityRoutes>,
    directory: GatewayDirectory,
    mcp: McpGateway,
}

async fn health(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    axum::Json(json!({"status":"ok", "node":state.node, "commit":state.commit}))
}

async fn handle(State(state): State<Arc<AppState>>, request: Request<Body>) -> Response {
    let path = request.uri().path();
    if let Some(identity) = state.identity.as_ref() {
        match (request.method(), path) {
            (&axum::http::Method::GET, identity_routes::METADATA_PATH) => {
                return identity.metadata(request.headers());
            }
            (&axum::http::Method::POST, identity_routes::VERIFY_PATH) => {
                return identity.verify(&state.auth, &state.node, request).await;
            }
            (&axum::http::Method::GET, "/api/identity/config") => {
                return identity.browser_config(&state.auth, request.headers());
            }
            (
                _,
                identity_routes::METADATA_PATH
                | identity_routes::VERIFY_PATH
                | "/api/identity/config",
            ) => return StatusCode::METHOD_NOT_ALLOWED.into_response(),
            _ => {}
        }
    }
    if path.starts_with("/internal/") {
        return StatusCode::NOT_FOUND.into_response();
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum GatewayMode {
    LocalShadow,
    PrivatePreview,
}

fn configured_mode(
    shadow: bool,
    preview: bool,
    ip: IpAddr,
    discovery: bool,
    oidc: bool,
) -> anyhow::Result<GatewayMode> {
    match (shadow, preview) {
        (true, false) if ip.is_loopback() => Ok(GatewayMode::LocalShadow),
        (false, true) if ip == IpAddr::V4(std::net::Ipv4Addr::UNSPECIFIED) && discovery && oidc => {
            Ok(GatewayMode::PrivatePreview)
        }
        _ => anyhow::bail!(
            "Rust Gateway requires either local loopback shadow, or explicitly configured private preview with OIDC and Valkey discovery"
        ),
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Deliberately no public Gateway mode. Private preview must have neither
    // a published host port nor an ingress route in its deployment resource.
    let shadow = env::var("RUST_GATEWAY_SHADOW_ONLY").as_deref() == Ok("true");
    let preview = env::var("GATEWAY_PRIVATE_PREVIEW").as_deref() == Ok("true");
    let host = env::var("BIND_HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let ip: IpAddr = host.parse()?;
    let mode = configured_mode(
        shadow,
        preview,
        ip,
        env::var("VALKEY_PASSWORD").is_ok_and(|value| !value.is_empty()),
        env::var("OIDC_ISSUER_URL").is_ok_and(|value| !value.is_empty()),
    )?;
    if mode == GatewayMode::PrivatePreview {
        anyhow::ensure!(
            env::var_os("GATEWAY_SHADOW_TARGETS_JSON").is_none(),
            "Private preview forbids shadow fixture target overrides"
        );
    }
    let port: u16 = env::var("PORT")
        .unwrap_or_else(|_| "18082".into())
        .parse()?;
    let node = env::var("BRIAREUS_NODE_ID")?;
    anyhow::ensure!(!node.trim().is_empty(), "BRIAREUS_NODE_ID is required");
    let api = Proxy::new(&env::var("CONTROL_PANEL_URL")?, "management")?;
    let ui = Proxy::new(&env::var("CONTROL_PANEL_UI_URL")?, "management-ui")?;
    let auth = ShadowOidc::from_env(&node)?;
    if mode == GatewayMode::PrivatePreview {
        anyhow::ensure!(
            auth.verifier.is_some(),
            "Private preview requires OIDC verifier"
        );
    }
    let identity = if let Ok(browser_id) = env::var("OIDC_BROWSER_CLIENT_ID") {
        let service_token = env::var("BRIAREUS_SERVICE_TOKEN")
            .map_err(|_| anyhow::anyhow!("BRIAREUS_SERVICE_TOKEN is required"))?;
        Some(identity_routes::IdentityRoutes::new(
            &auth,
            &node,
            service_token,
            &browser_id,
        )?)
    } else {
        None
    };
    if mode == GatewayMode::PrivatePreview {
        anyhow::ensure!(
            identity.is_some(),
            "Private preview requires Gateway identity configuration"
        );
        let token = env::var("OIDC_PROVISIONING_TOKEN")
            .map_err(|_| anyhow::anyhow!("OIDC_PROVISIONING_TOKEN is required"))?;
        node_registration::ensure_node_role(
            auth.issuer()
                .ok_or_else(|| anyhow::anyhow!("OIDC issuer required"))?,
            auth.audience()
                .ok_or_else(|| anyhow::anyhow!("OIDC audience required"))?,
            &node,
            &token,
        )
        .await?;
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
    let mcp = McpGateway::new(auth.public_host(), auth.public_origin());
    let state = AppState {
        directory,
        mcp,
        node,
        auth,
        identity,
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

#[cfg(test)]
mod mode_tests {
    use super::{GatewayMode, configured_mode};
    use std::net::{IpAddr, Ipv4Addr};

    #[test]
    fn local_shadow_never_accepts_public_or_mixed_modes() {
        let local = IpAddr::V4(Ipv4Addr::LOCALHOST);
        let any = IpAddr::V4(Ipv4Addr::UNSPECIFIED);
        assert!(matches!(
            configured_mode(true, false, local, false, false),
            Ok(GatewayMode::LocalShadow)
        ));
        for (shadow, preview, address) in [
            (false, false, local),
            (true, true, local),
            (true, false, any),
            (false, true, local),
            (false, false, any),
            (true, true, any),
        ] {
            assert!(configured_mode(shadow, preview, address, true, true).is_err());
        }
    }

    #[test]
    fn private_preview_requires_explicit_isolation_and_both_authorities() {
        let any = IpAddr::V4(Ipv4Addr::UNSPECIFIED);
        assert!(matches!(
            configured_mode(false, true, any, true, true),
            Ok(GatewayMode::PrivatePreview)
        ));
        for (discovery, oidc) in [(false, false), (false, true), (true, false)] {
            assert!(configured_mode(false, true, any, discovery, oidc).is_err());
        }
    }
}
