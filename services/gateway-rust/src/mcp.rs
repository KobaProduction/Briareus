//! Local-shadow MCP facade: independent frontend sessions and a bounded,
//! reusable backend-client pool. No public bearer is sent to backend Hands.
use std::{
    collections::HashMap,
    io,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};

use axum::{
    body::Body,
    http::{Method, Request, StatusCode},
    response::{IntoResponse, Response},
};
use briareus_service_discovery_rs::ServiceIdentity;
use rmcp::{
    ErrorData as McpError, ServerHandler, ServiceExt,
    model::{
        CallToolRequestParams, CallToolResponse, ContentBlock, GetPromptRequestParams,
        GetPromptResponse, Implementation, ListPromptsResult, ListResourceTemplatesResult,
        ListResourcesResult, ListToolsResult, PaginatedRequestParams, ReadResourceRequestParams,
        ReadResourceResponse, ServerCapabilities, ServerConfig,
    },
    service::{Peer, RequestContext, RoleClient, RoleServer, RunningService},
    transport::{
        StreamableHttpClientTransport,
        streamable_http_client::StreamableHttpClientTransportConfig,
        streamable_http_server::{
            StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager,
        },
    },
};
use tokio::sync::Mutex;
use tower::ServiceExt as TowerServiceExt;

const BACKEND_CONNECT_TIMEOUT: Duration = Duration::from_secs(8);
const BACKEND_REQUEST_TIMEOUT: Duration = Duration::from_secs(300);
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
}

impl BackendPool {
    fn new(url: String) -> Self {
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
        }
    }

    async fn peer(&self) -> Result<Peer<RoleClient>, McpError> {
        let index = self.next_slot.fetch_add(1, Ordering::Relaxed) % BACKEND_POOL_SIZE;
        let mut slot = self.slots[index].lock().await;
        let disconnected = slot.session.as_ref().is_none_or(BackendSession::is_closed);
        if disconnected {
            slot.session = None;
            let config = StreamableHttpClientTransportConfig::with_uri(self.url.clone())
                .max_concurrent_requests(8)
                .control_request_timeout(Duration::from_secs(3))
                .session_recovery_timeout(Duration::from_secs(4))
                .reinit_on_expired_session(true);
            let transport = StreamableHttpClientTransport::with_client(self.client.clone(), config);
            let service = tokio::time::timeout(BACKEND_CONNECT_TIMEOUT, ().serve(transport))
                .await
                .map_err(|_| backend_error())?
                .map_err(|_| backend_error())?;
            slot.session = Some(service);
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
        tokio::time::timeout(Duration::from_secs(30), peer.list_tools(request))
            .await
            .map_err(|_| backend_error())?
            .map_err(|_| backend_error())
    }

    async fn call_tool(&self, params: CallToolRequestParams) -> Result<CallToolResponse, McpError> {
        let peer = self.peer().await?;
        match tokio::time::timeout(BACKEND_REQUEST_TIMEOUT, peer.call_tool(params)).await {
            Ok(Ok(result)) => Ok(CallToolResponse::Complete(result)),
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
        tokio::time::timeout(Duration::from_secs(30), peer.list_prompts(request))
            .await
            .map_err(|_| backend_error())?
            .map_err(|_| backend_error())
    }

    async fn list_resources(
        &self,
        request: Option<PaginatedRequestParams>,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<ListResourcesResult, McpError> {
        let peer = self.backend.peer().await?;
        tokio::time::timeout(Duration::from_secs(30), peer.list_resources(request))
            .await
            .map_err(|_| backend_error())?
            .map_err(|_| backend_error())
    }

    async fn list_resource_templates(
        &self,
        request: Option<PaginatedRequestParams>,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<ListResourceTemplatesResult, McpError> {
        let peer = self.backend.peer().await?;
        tokio::time::timeout(
            Duration::from_secs(30),
            peer.list_resource_templates(request),
        )
        .await
        .map_err(|_| backend_error())?
        .map_err(|_| backend_error())
    }

    async fn read_resource(
        &self,
        request: ReadResourceRequestParams,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<ReadResourceResponse, McpError> {
        let peer = self.backend.peer().await?;
        tokio::time::timeout(BACKEND_REQUEST_TIMEOUT, peer.read_resource_once(request))
            .await
            .map_err(|_| backend_error())?
            .map_err(|_| backend_error())
    }

    async fn get_prompt(
        &self,
        request: GetPromptRequestParams,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<GetPromptResponse, McpError> {
        let peer = self.backend.peer().await?;
        let backend_info = peer.peer_info().map(|data| data.server_info.clone());
        let response = tokio::time::timeout(Duration::from_secs(30), peer.get_prompt_once(request))
            .await
            .map_err(|_| backend_error())?
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

struct ProviderSurface {
    identity: ServiceIdentity,
    backend_url: String,
    http: ProviderHttp,
}

#[derive(Clone)]
pub struct McpGateway {
    inner: Arc<Mutex<HashMap<String, ProviderSurface>>>,
    allowed_hosts: Arc<Vec<String>>,
    allowed_origins: Arc<Vec<String>>,
}

impl McpGateway {
    pub fn new() -> Self {
        fn csv(key: &str, defaults: &[&str]) -> Vec<String> {
            std::env::var(key)
                .ok()
                .filter(|v| !v.trim().is_empty())
                .map(|v| {
                    v.split(',')
                        .map(str::trim)
                        .filter(|x| !x.is_empty())
                        .map(str::to_owned)
                        .collect()
                })
                .unwrap_or_else(|| defaults.iter().map(|x| x.to_string()).collect())
        }
        Self {
            inner: Arc::new(Mutex::new(HashMap::new())),
            allowed_hosts: Arc::new(csv("MCP_ALLOWED_HOSTS", &["localhost:*", "127.0.0.1:*"])),
            allowed_origins: Arc::new(csv(
                "MCP_ALLOWED_ORIGINS",
                &["http://localhost:*", "http://127.0.0.1:*"],
            )),
        }
    }

    pub async fn handle(
        &self,
        service: ServiceIdentity,
        backend_url: String,
        request: Request<Body>,
    ) -> Response {
        let http_service = {
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
                    backend: BackendPool::new(backend_url.clone()),
                };
                let config = StreamableHttpServerConfig::default()
                    .with_allowed_hosts(self.allowed_hosts.iter().cloned())
                    .with_allowed_origins(self.allowed_origins.iter().cloned())
                    .with_legacy_session_mode(true)
                    .with_json_response(true);
                let http = StreamableHttpService::new(
                    move || Ok::<_, io::Error>(handler.clone()),
                    Arc::new(LocalSessionManager::default()),
                    config,
                );
                surfaces.insert(
                    service.id.clone(),
                    ProviderSurface {
                        identity: service.clone(),
                        backend_url,
                        http,
                    },
                );
            }
            surfaces
                .get(&service.id)
                .expect("new surface inserted")
                .http
                .clone()
        };
        let is_delete = request.method() == Method::DELETE;
        match http_service.oneshot(request).await {
            Ok(response) => {
                let mut response = response.map(Body::new).into_response();
                // FastMCP's Python Gateway acknowledges successful session
                // termination with 200, not rmcp's default 202.
                if is_delete && response.status() == StatusCode::ACCEPTED {
                    *response.status_mut() = StatusCode::OK;
                }
                response
            }
            Err(never) => match never {},
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn service_origin_change_replaces_cached_frontend_and_backend() {
        let gateway = McpGateway::new();
        let identity = ServiceIdentity::new("github", "GitHub", "svc").unwrap();
        for (expected_url, expected_name) in [
            ("http://127.0.0.1:12345/mcp", "GitHub"),
            ("http://127.0.0.1:12346/mcp", "GitHub"),
            ("http://127.0.0.1:12346/mcp", "GitHub Updated"),
        ] {
            let service = ServiceIdentity::new("github", expected_name, "svc").unwrap();
            let request = Request::builder().uri("/mcp").body(Body::empty()).unwrap();
            let _ = gateway
                .handle(service, expected_url.to_owned(), request)
                .await;
            let surfaces = gateway.inner.lock().await;
            let recorded = surfaces.get("github").unwrap();
            assert_eq!(recorded.backend_url, expected_url);
            assert_eq!(recorded.identity.name, expected_name);
            assert_eq!(surfaces.len(), 1);
        }
        let _ = identity;
    }
}
