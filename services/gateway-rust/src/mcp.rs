//! MCP facade: principal-bound frontend sessions and a bounded,
//! reusable backend-client pool. No public bearer is sent to backend Hands.
use std::{
    collections::HashMap,
    io,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use crate::mcp_policy::McpPolicy;
use axum::{
    body::Body,
    http::{Method, Request, StatusCode, header},
    response::{IntoResponse, Response},
};
use briareus_oidc_verifier_rs::VerifiedPrincipal;
use briareus_service_discovery_rs::ServiceIdentity;
use futures_util::StreamExt;
use rmcp::{
    ErrorData as McpError, ServerHandler, ServiceExt,
    model::{
        CallToolRequestParams, CallToolResponse, ContentBlock, GetPromptRequestParams,
        GetPromptResponse, Implementation, ListPromptsResult, ListResourceTemplatesResult,
        ListResourcesResult, ListToolsResult, PaginatedRequestParams, ReadResourceRequestParams,
        ReadResourceResponse, ServerCapabilities, ServerConfig,
    },
    service::{
        ClientInitializeError, Peer, RequestContext, RoleClient, RoleServer, RunningService,
    },
    transport::{
        StreamableHttpClientTransport,
        streamable_http_client::StreamableHttpClientTransportConfig,
        streamable_http_server::{
            StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager,
        },
    },
};
use tokio::{sync::Mutex, time::Instant};
use tower::ServiceExt as TowerServiceExt;

const BACKEND_CONNECT_TIMEOUT: Duration = Duration::from_secs(8);
const BACKEND_POOL_SIZE: usize = 2;

fn backend_error() -> McpError {
    McpError::internal_error("MCP backend unavailable", None)
}

type BackendSession = RunningService<RoleClient, ()>;
struct BackendSlot {
    session: Option<BackendSession>,
}

#[derive(Clone)]
struct BackendPool {
    url: Arc<str>,
    slots: Arc<Vec<Mutex<BackendSlot>>>,
    next_slot: Arc<AtomicUsize>,
    client: reqwest_mcp::Client,
    policy: McpPolicy,
}

impl BackendPool {
    fn new(url: String, policy: McpPolicy) -> Self {
        let client = reqwest_mcp::Client::builder()
            .redirect(reqwest_mcp::redirect::Policy::none())
            .no_proxy()
            .connect_timeout(Duration::from_secs(3))
            .pool_max_idle_per_host(2)
            .build()
            .expect("valid static HTTP client options");
        let slots = (0..BACKEND_POOL_SIZE)
            .map(|_| Mutex::new(BackendSlot { session: None }))
            .collect();
        Self {
            url: url.into(),
            slots: Arc::new(slots),
            next_slot: Arc::new(AtomicUsize::new(0)),
            client,
            policy,
        }
    }

    async fn connect(&self) -> Result<BackendSession, McpError> {
        // Only a failed initialization handshake is safe to repeat here.
        // Never repeat a dispatched tool/resource/prompt request.
        tokio::time::timeout(BACKEND_CONNECT_TIMEOUT, async {
            for attempt in 0..2 {
                let config = StreamableHttpClientTransportConfig::with_uri(self.url.clone())
                    .max_concurrent_requests(8)
                    .control_request_timeout(Duration::from_secs(3))
                    .session_recovery_timeout(Duration::from_secs(4))
                    .reinit_on_expired_session(true);
                let transport =
                    StreamableHttpClientTransport::with_client(self.client.clone(), config);
                match ().serve(transport).await {
                    Ok(service) => return Ok(service),
                    Err(ClientInitializeError::ConnectionClosed(context))
                        if attempt == 0 && context == "initialize response" =>
                    {
                        tokio::time::sleep(Duration::from_millis(100)).await;
                    }
                    Err(_) => return Err(backend_error()),
                }
            }
            Err(backend_error())
        })
        .await
        .map_err(|_| backend_error())?
    }

    async fn peer(&self) -> Result<Peer<RoleClient>, McpError> {
        let index = self.next_slot.fetch_add(1, Ordering::Relaxed) % BACKEND_POOL_SIZE;
        let mut slot = self.slots[index].lock().await;
        let disconnected = slot.session.as_ref().is_none_or(BackendSession::is_closed);
        if disconnected {
            slot.session = None;
            slot.session = Some(self.connect().await?);
        }
        Ok(slot
            .session
            .as_ref()
            .expect("session just set")
            .peer()
            .clone())
    }

    async fn list_tools(
        &self,
        request: Option<PaginatedRequestParams>,
    ) -> Result<ListToolsResult, McpError> {
        let peer = self.peer().await?;
        self.policy
            .run(true, peer.list_tools(request))
            .await
            .map_err(|_| backend_error())
    }

    async fn call_tool(&self, params: CallToolRequestParams) -> Result<CallToolResponse, McpError> {
        let peer = self.peer().await?;
        match self.policy.run(false, peer.call_tool(params)).await {
            Ok(result) => Ok(CallToolResponse::Complete(result)),
            _ => Ok(CallToolResponse::Complete(
                rmcp::model::CallToolResult::error(vec![ContentBlock::text(
                    "MCP backend unavailable",
                )]),
            )),
        }
    }
}

#[derive(Clone)]
struct ProviderFacade {
    service: ServiceIdentity,
    backend: BackendPool,
}

impl ServerHandler for ProviderFacade {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(
            ServerCapabilities::builder()
                .enable_tools()
                .enable_resources()
                .enable_prompts()
                .build(),
        )
        .with_server_info(Implementation::new(self.service.name.clone(), "1.0.0"))
    }

    async fn list_tools(
        &self,
        request: Option<PaginatedRequestParams>,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, McpError> {
        self.backend.list_tools(request).await
    }

    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, McpError> {
        self.backend.call_tool(request).await
    }

    async fn list_prompts(
        &self,
        request: Option<PaginatedRequestParams>,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<ListPromptsResult, McpError> {
        let peer = self.backend.peer().await?;
        self.backend
            .policy
            .run(true, peer.list_prompts(request))
            .await
            .map_err(|_| backend_error())
    }

    async fn list_resources(
        &self,
        request: Option<PaginatedRequestParams>,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<ListResourcesResult, McpError> {
        let peer = self.backend.peer().await?;
        self.backend
            .policy
            .run(true, peer.list_resources(request))
            .await
            .map_err(|_| backend_error())
    }

    async fn list_resource_templates(
        &self,
        request: Option<PaginatedRequestParams>,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<ListResourceTemplatesResult, McpError> {
        let peer = self.backend.peer().await?;
        self.backend
            .policy
            .run(true, peer.list_resource_templates(request))
            .await
            .map_err(|_| backend_error())
    }

    async fn read_resource(
        &self,
        request: ReadResourceRequestParams,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<ReadResourceResponse, McpError> {
        let peer = self.backend.peer().await?;
        self.backend
            .policy
            .run(false, peer.read_resource_once(request))
            .await
            .map_err(|_| backend_error())
    }

    async fn get_prompt(
        &self,
        request: GetPromptRequestParams,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<GetPromptResponse, McpError> {
        let peer = self.backend.peer().await?;
        let backend_info = peer.peer_info().map(|data| data.server_info.clone());
        let response = self
            .backend
            .policy
            .run(false, peer.get_prompt_once(request))
            .await
            .map_err(|_| backend_error())?;
        // Preserve the original Hand's serverInfo, matching Python FastMCPProxy.
        // It is provider metadata, never the calling user's authentication data.
        match response {
            GetPromptResponse::Complete(mut value) => {
                const ORIGIN_KEY: &str = "io.modelcontextprotocol/serverInfo";
                if let Some(origin) = backend_info {
                    let meta = value.meta.get_or_insert_with(Default::default);
                    if !meta.contains_key(ORIGIN_KEY) {
                        meta.insert(
                            ORIGIN_KEY.to_owned(),
                            serde_json::to_value(origin).map_err(|_| backend_error())?,
                        );
                    }
                }
                Ok(GetPromptResponse::Complete(value))
            }
            other => Ok(other),
        }
    }
}

type ProviderHttp = StreamableHttpService<ProviderFacade, LocalSessionManager>;

const SESSION_HEADER: &str = "mcp-session-id";
const MAX_FRONTEND_SESSIONS: usize = 128;
const MAX_OWNER_BYTES: usize = 4096;

#[derive(Clone, Eq, PartialEq)]
struct SessionOwner {
    subject: String,
    client_id: String,
}

struct SessionBoundary {
    manager: Arc<LocalSessionManager>,
    owners: Mutex<HashMap<String, SessionOwner>>,
    initialization: Mutex<()>,
}

impl SessionBoundary {
    fn new() -> Self {
        Self {
            manager: Arc::new(LocalSessionManager::default()),
            owners: Mutex::new(HashMap::new()),
            initialization: Mutex::new(()),
        }
    }

    async fn dispatch(
        &self,
        http: ProviderHttp,
        principal: &VerifiedPrincipal,
        mut request: Request<Body>,
    ) -> Response {
        if principal.subject.len() > MAX_OWNER_BYTES || principal.client_id.len() > MAX_OWNER_BYTES
        {
            return StatusCode::UNAUTHORIZED.into_response();
        }
        let Some(deadline) = token_deadline(principal.expires_at) else {
            return StatusCode::UNAUTHORIZED.into_response();
        };
        let owner = SessionOwner {
            subject: principal.subject.clone(),
            client_id: principal.client_id.clone(),
        };
        let session = {
            let mut ids = request.headers().get_all(SESSION_HEADER).iter();
            match ids.next() {
                None => None,
                Some(value) => {
                    let Ok(id) = value.to_str() else {
                        return StatusCode::BAD_REQUEST.into_response();
                    };
                    if id.is_empty() || id.len() > 256 || ids.next().is_some() {
                        return StatusCode::BAD_REQUEST.into_response();
                    }
                    Some(id.to_owned())
                }
            }
        };
        // Never expose the verified external bearer or a browser cookie to the
        // SDK's long-lived request/session state.
        request
            .headers_mut()
            .remove(axum::http::header::AUTHORIZATION);
        request.headers_mut().remove(axum::http::header::COOKIE);
        if let Some(id) = session {
            let owned = self.owners.lock().await.get(&id) == Some(&owner);
            if !owned {
                // Do not distinguish a foreign session from an absent session.
                return StatusCode::NOT_FOUND.into_response();
            }
            let deleting = request.method() == Method::DELETE;
            let response = serve_request(http, request, deadline).await;
            if deleting && response.status().is_success() {
                self.owners.lock().await.remove(&id);
            }
            return response;
        }
        if request.method() != Method::POST {
            return serve_request(http, request, deadline).await;
        }
        // Only a sessionless POST can initialize. Serialize this small
        // admission path, never ordinary tool requests. The SDK owns idle
        // eviction; remove corresponding owner records before admitting more.
        let Ok(_init) = tokio::time::timeout_at(deadline, self.initialization.lock()).await else {
            return StatusCode::UNAUTHORIZED.into_response();
        };
        {
            let sessions = self.manager.sessions.read().await;
            let mut owners = self.owners.lock().await;
            owners.retain(|id, _| sessions.contains_key(id.as_str()));
            if sessions.len() >= MAX_FRONTEND_SESSIONS {
                return StatusCode::SERVICE_UNAVAILABLE.into_response();
            }
        }
        let response = serve_request(http, request, deadline).await;
        if response.status().is_success()
            && let Some(id) = response
                .headers()
                .get(SESSION_HEADER)
                .and_then(|v| v.to_str().ok())
        {
            self.owners.lock().await.insert(id.to_owned(), owner);
        }
        response
    }
}

fn token_deadline(expires_at: u64) -> Option<Instant> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?;
    let remaining = Duration::from_secs(expires_at).checked_sub(now)?;
    if remaining.is_zero() {
        return None;
    }
    Instant::now().checked_add(remaining)
}

async fn serve_request(http: ProviderHttp, request: Request<Body>, deadline: Instant) -> Response {
    if Instant::now() >= deadline {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let deleting = request.method() == Method::DELETE;
    match tokio::time::timeout_at(deadline, http.oneshot(request)).await {
        Ok(Ok(response)) => {
            if Instant::now() >= deadline {
                return StatusCode::UNAUTHORIZED.into_response();
            }
            let (mut parts, body) = response.into_parts();
            // FastMCP acknowledges successful session termination with 200.
            if deleting && parts.status == StatusCode::ACCEPTED {
                parts.status = StatusCode::OK;
            }
            // A standalone SSE connection must not keep the authority of an
            // expired bearer. Bound delivery by the admitting token's expiry,
            // not by a later request's refreshed token. No dispatched tool
            // call is retried by this guard.
            parts.headers.remove(header::CONTENT_LENGTH);
            let stream = Body::new(body)
                .into_data_stream()
                .take_until(tokio::time::sleep_until(deadline));
            Response::from_parts(parts, Body::from_stream(stream))
        }
        Ok(Err(never)) => match never {},
        Err(_) => StatusCode::UNAUTHORIZED.into_response(),
    }
}

struct ProviderSurface {
    identity: ServiceIdentity,
    backend_url: String,
    http: ProviderHttp,
    boundary: Arc<SessionBoundary>,
}

#[derive(Clone)]
pub struct McpGateway {
    inner: Arc<Mutex<HashMap<String, ProviderSurface>>>,
    allowed_hosts: Arc<Vec<String>>,
    allowed_origins: Arc<Vec<String>>,
    policy: McpPolicy,
}

impl McpGateway {
    pub fn new(public_host: Option<&str>, public_origin: Option<&str>, policy: McpPolicy) -> Self {
        // The public OIDC origin is the single authority for transport Host
        // and Origin checks. Never reintroduce independent wildcard env lists.
        let allowed_hosts = public_host.map_or_else(
            || vec!["localhost:*".into(), "127.0.0.1:*".into()],
            |host| vec![host.to_owned()],
        );
        let allowed_origins = public_origin.map_or_else(
            || vec!["http://localhost:*".into(), "http://127.0.0.1:*".into()],
            |origin| vec![origin.to_owned()],
        );
        Self {
            inner: Arc::new(Mutex::new(HashMap::new())),
            allowed_hosts: Arc::new(allowed_hosts),
            allowed_origins: Arc::new(allowed_origins),
            policy,
        }
    }

    pub async fn handle(
        &self,
        service: ServiceIdentity,
        backend_url: String,
        principal: &VerifiedPrincipal,
        request: Request<Body>,
    ) -> Response {
        let (http_service, boundary) = {
            let mut surfaces = self.inner.lock().await;
            // Dynamic service discovery can change provider identity or origin.
            // Reuse a backend pool only for an *identical* service route and target;
            // a new target owns a fresh frontend session manager and backend pool.
            let changed = surfaces.get(&service.id).is_none_or(|surface| {
                surface.identity != service || surface.backend_url != backend_url
            });
            if changed {
                let handler = ProviderFacade {
                    service: service.clone(),
                    backend: BackendPool::new(backend_url.clone(), self.policy.clone()),
                };
                let config = StreamableHttpServerConfig::default()
                    .with_allowed_hosts(self.allowed_hosts.iter().cloned())
                    .with_allowed_origins(self.allowed_origins.iter().cloned())
                    .with_legacy_session_mode(true)
                    .with_json_response(true);
                let boundary = Arc::new(SessionBoundary::new());
                let http = StreamableHttpService::new(
                    move || Ok::<_, io::Error>(handler.clone()),
                    boundary.manager.clone(),
                    config,
                );
                surfaces.insert(
                    service.id.clone(),
                    ProviderSurface {
                        identity: service.clone(),
                        backend_url,
                        http,
                        boundary,
                    },
                );
            }
            let surface = surfaces.get(&service.id).expect("new surface inserted");
            (surface.http.clone(), surface.boundary.clone())
        };
        boundary.dispatch(http_service, principal, request).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn service_origin_change_replaces_cached_frontend_and_backend() {
        let gateway = McpGateway::new(None, None, McpPolicy::default());
        let principal = VerifiedPrincipal {
            subject: "synthetic-user".into(),
            username: "user".into(),
            display_name: "User".into(),
            client_id: "synthetic-client".into(),
            roles: vec!["node".into()],
            expires_at: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs()
                + 60,
            scopes: vec![],
        };
        for (expected_url, expected_name) in [
            ("http://127.0.0.1:12345/mcp", "GitHub"),
            ("http://127.0.0.1:12346/mcp", "GitHub"),
            ("http://127.0.0.1:12346/mcp", "GitHub Updated"),
        ] {
            let service = ServiceIdentity::new("github", expected_name, "svc").unwrap();
            let request = Request::builder().uri("/mcp").body(Body::empty()).unwrap();
            let _ = gateway
                .handle(service, expected_url.to_owned(), &principal, request)
                .await;
            let surfaces = gateway.inner.lock().await;
            let recorded = surfaces.get("github").unwrap();
            assert_eq!(recorded.backend_url, expected_url);
            assert_eq!(recorded.identity.name, expected_name);
            assert_eq!(surfaces.len(), 1);
        }
    }
}
