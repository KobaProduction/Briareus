//! MCP transport surface. Keep SigNoz semantics in signoz.rs and the
//! reusable Hand contracts in shared/rust/hand-core.
use std::{
    env, io,
    net::{IpAddr, SocketAddr},
    sync::Arc,
};

use axum::{Router, routing::get};
use briareus_hand_core::{HandError, PanelAccountDirectory};
use rmcp::{
    Json, ServerHandler,
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::{CallToolResult, ContentBlock, Implementation, ServerCapabilities, ServerConfig},
    tool, tool_handler, tool_router,
    transport::streamable_http_server::{
        StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager,
    },
};
use schemars::JsonSchema;
use serde::Deserialize;
use serde_json::{Value, json};

use crate::signoz::SigNozApi;

const DEFAULT_PORT: u16 = 18081;
const DEFAULT_PROVIDER_HTTP_CACHE_ENTRIES: usize = 32;
const MAX_PROVIDER_HTTP_CACHE_ENTRIES: usize = 256;

fn configured_http_cache_capacity(value: Option<&str>) -> anyhow::Result<usize> {
    let capacity = value
        .map(str::parse::<usize>)
        .transpose()?
        .unwrap_or(DEFAULT_PROVIDER_HTTP_CACHE_ENTRIES);
    anyhow::ensure!(
        capacity <= MAX_PROVIDER_HTTP_CACHE_ENTRIES,
        "RUST_PROVIDER_HTTP_CACHE_ENTRIES must be between 0 and 256"
    );
    Ok(capacity)
}

#[derive(Debug, Deserialize, JsonSchema)]
struct AccountSelector {
    account_id: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
struct LogSearch {
    account_id: String,
    start_ms: i64,
    end_ms: i64,
    #[serde(default)]
    filter_expression: String,
    #[serde(default = "default_limit")]
    limit: i64,
    #[serde(default)]
    offset: i64,
}

fn default_limit() -> i64 {
    100
}

#[derive(Debug, Deserialize, JsonSchema)]
struct QueryTelemetry {
    account_id: String,
    query: Value,
}

#[derive(Debug, Deserialize, JsonSchema)]
struct ServiceWindow {
    account_id: String,
    start: String,
    end: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
struct FieldKeys {
    account_id: String,
    signal: String,
    #[serde(default)]
    search_text: String,
    #[serde(default)]
    metric_name: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
struct FieldValues {
    account_id: String,
    signal: String,
    name: String,
    #[serde(default)]
    search_text: String,
    #[serde(default)]
    metric_name: String,
}

fn output(result: Result<Value, HandError>) -> Result<Json<Value>, String> {
    result.map(Json).map_err(|error| error.to_string())
}

fn provider_output(result: Result<Value, HandError>) -> Result<CallToolResult, String> {
    // Python's JsonValue tools expose their payload inside structuredContent.result,
    // but return the raw provider JSON in the text fallback. The two views must
    // remain intentionally distinct for existing MCP clients.
    result
        .map(|value| {
            let mut reply = CallToolResult::success(vec![ContentBlock::text(value.to_string())]);
            reply.structured_content = Some(json!({"result": value}));
            reply
        })
        .map_err(|error| error.to_string())
}

#[derive(Clone)]
pub struct RustSigNozHand {
    api: Arc<SigNozApi<PanelAccountDirectory>>,
    tool_router: ToolRouter<Self>,
}

#[tool_router(router = tool_router)]
impl RustSigNozHand {
    fn new(api: SigNozApi<PanelAccountDirectory>) -> Self {
        let mut tool_router = Self::tool_router();
        // Python/FastMCP exposes two object tools and six JsonValue tools.
        // Match its tools/list output schemas, not only the payload bodies:
        // consumers use x-fastmcp-wrap-result when decoding structuredContent.
        let object_schema = Arc::new(serde_json::Map::from_iter([
            ("additionalProperties".into(), json!({})),
            ("type".into(), json!("object")),
        ]));
        let wrapped_schema = Arc::new(serde_json::Map::from_iter([
            ("properties".into(), json!({"result": {}})),
            ("required".into(), json!(["result"])),
            ("type".into(), json!("object")),
            ("x-fastmcp-wrap-result".into(), json!(true)),
        ]));
        for name in ["signoz_sources", "signoz_connection"] {
            tool_router
                .map
                .get_mut(name)
                .expect("registered SigNoz tool")
                .attr
                .output_schema = Some(Arc::clone(&object_schema));
        }
        for name in [
            "signoz_search_logs",
            "signoz_search_traces",
            "signoz_query_telemetry",
            "signoz_list_services",
            "signoz_field_keys",
            "signoz_field_values",
        ] {
            tool_router
                .map
                .get_mut(name)
                .expect("registered SigNoz tool")
                .attr
                .output_schema = Some(Arc::clone(&wrapped_schema));
        }
        Self {
            api: Arc::new(api),
            tool_router,
        }
    }

    #[tool(
        name = "signoz_sources",
        description = "List configured SigNoz sources without exposing credentials.",
        annotations(read_only_hint = true, open_world_hint = true)
    )]
    async fn sources(&self) -> Result<Json<Value>, String> {
        output(self.api.sources().await)
    }

    #[tool(
        name = "signoz_connection",
        description = "Show safe metadata for one configured SigNoz source.",
        annotations(read_only_hint = true, open_world_hint = true)
    )]
    async fn connection(
        &self,
        Parameters(p): Parameters<AccountSelector>,
    ) -> Result<Json<Value>, String> {
        output(self.api.connection(&p.account_id).await)
    }

    #[tool(
        name = "signoz_search_logs",
        description = "Search runtime logs in a selected SigNoz source.",
        annotations(read_only_hint = true, open_world_hint = true)
    )]
    async fn search_logs(
        &self,
        Parameters(p): Parameters<LogSearch>,
    ) -> Result<CallToolResult, String> {
        provider_output(
            self.api
                .search_logs(
                    &p.account_id,
                    p.start_ms,
                    p.end_ms,
                    &p.filter_expression,
                    p.limit,
                    p.offset,
                )
                .await,
        )
    }

    #[tool(
        name = "signoz_search_traces",
        description = "Search traces in a selected SigNoz source.",
        annotations(read_only_hint = true, open_world_hint = true)
    )]
    async fn search_traces(
        &self,
        Parameters(p): Parameters<LogSearch>,
    ) -> Result<CallToolResult, String> {
        provider_output(
            self.api
                .search_traces(
                    &p.account_id,
                    p.start_ms,
                    p.end_ms,
                    &p.filter_expression,
                    p.limit,
                    p.offset,
                )
                .await,
        )
    }

    #[tool(
        name = "signoz_query_telemetry",
        description = "Run a read-only SigNoz Query Builder v5 query for logs, traces or metrics.",
        annotations(read_only_hint = true, open_world_hint = true)
    )]
    async fn query_telemetry(
        &self,
        Parameters(p): Parameters<QueryTelemetry>,
    ) -> Result<CallToolResult, String> {
        provider_output(self.api.query_range(&p.account_id, &p.query).await)
    }

    #[tool(
        name = "signoz_list_services",
        description = "List services observed in an ISO 8601 or Unix timestamp window.",
        annotations(read_only_hint = true, open_world_hint = true)
    )]
    async fn list_services(
        &self,
        Parameters(p): Parameters<ServiceWindow>,
    ) -> Result<CallToolResult, String> {
        provider_output(
            self.api
                .list_services(&p.account_id, &p.start, &p.end)
                .await,
        )
    }

    #[tool(
        name = "signoz_field_keys",
        description = "Discover available SigNoz field keys for logs, traces or metrics.",
        annotations(read_only_hint = true, open_world_hint = true)
    )]
    async fn field_keys(
        &self,
        Parameters(p): Parameters<FieldKeys>,
    ) -> Result<CallToolResult, String> {
        provider_output(
            self.api
                .field_keys(&p.account_id, &p.signal, &p.search_text, &p.metric_name)
                .await,
        )
    }

    #[tool(
        name = "signoz_field_values",
        description = "Discover values for one field in a selected SigNoz source.",
        annotations(read_only_hint = true, open_world_hint = true)
    )]
    async fn field_values(
        &self,
        Parameters(p): Parameters<FieldValues>,
    ) -> Result<CallToolResult, String> {
        provider_output(
            self.api
                .field_values(
                    &p.account_id,
                    &p.signal,
                    &p.name,
                    &p.search_text,
                    &p.metric_name,
                )
                .await,
        )
    }
}

#[tool_handler(router = self.tool_router)]
impl ServerHandler for RustSigNozHand {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
            .with_server_info(Implementation::new(
                "signoz-rust",
                env!("CARGO_PKG_VERSION"),
            ))
            .with_instructions("Parallel read-only SigNoz Hand pilot; use an explicit account_id.")
    }
}

fn csv_config(key: &str, defaults: &[&str]) -> Vec<String> {
    env::var(key)
        .ok()
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

fn router(server: RustSigNozHand, config: StreamableHttpServerConfig) -> Router {
    let transport = StreamableHttpService::new(
        move || Ok::<_, io::Error>(server.clone()),
        Arc::new(LocalSessionManager::default()),
        config,
    );
    Router::new()
        .route("/health", get(|| async { "ok" }))
        .nest_service("/mcp", transport)
}

pub async fn run() -> anyhow::Result<()> {
    // Intentionally no fallback to guest privileges or a baked-in service token.
    let panel_url =
        env::var("CONTROL_PANEL_URL").unwrap_or_else(|_| "http://control-panel-api:8000".into());
    let token = env::var("BRIAREUS_SERVICE_TOKEN").unwrap_or_default();
    let directory = PanelAccountDirectory::new(&panel_url, &token, "signoz")?;
    // Reuse provider HTTP connection pools only after every account lookup;
    // zero disables pooling. Bounded to avoid uncontrolled per-account memory.
    let configured_capacity = env::var("RUST_PROVIDER_HTTP_CACHE_ENTRIES").ok();
    let cache_entries = configured_http_cache_capacity(configured_capacity.as_deref())?;
    let api = SigNozApi::with_http_cache_capacity(directory, cache_entries);
    let server = RustSigNozHand::new(api);

    let port = env::var("PORT")
        .ok()
        .map(|value| value.parse::<u16>())
        .transpose()?
        .unwrap_or(DEFAULT_PORT);
    // A private loopback listener is the safe local default. An isolated
    // container may opt into its private network interface explicitly.
    let bind_host = env::var("BIND_HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let listen = SocketAddr::new(bind_host.parse::<IpAddr>()?, port);
    let allowed_hosts = csv_config(
        "PRIVATE_MCP_ALLOWED_HOSTS",
        &["localhost:*", "127.0.0.1:*", "[::1]:*"],
    );
    let allowed_origins = csv_config(
        "PRIVATE_MCP_ALLOWED_ORIGINS",
        &["http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*"],
    );
    let config = StreamableHttpServerConfig::default()
        .with_allowed_hosts(allowed_hosts)
        .with_allowed_origins(allowed_origins)
        .with_legacy_session_mode(false)
        .with_json_response(true);
    let app = router(server, config);
    let listener = tokio::net::TcpListener::bind(listen).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sse_json(body: &str) -> Value {
        body.lines()
            .filter_map(|line| line.strip_prefix("data: "))
            .find_map(|content| serde_json::from_str(content).ok())
            .expect("MCP SSE response contains JSON")
    }

    #[tokio::test]
    async fn streamable_http_exposes_eight_read_only_tools() {
        let directory =
            PanelAccountDirectory::new("http://127.0.0.1:1", "fake-service-token", "signoz")
                .unwrap();
        let server = RustSigNozHand::new(SigNozApi::with_http_cache_capacity(directory, 32));
        let app = router(
            server,
            StreamableHttpServerConfig::default().with_allowed_hosts(["127.0.0.1:*"]),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let task = tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });

        let client = reqwest::Client::new();
        let url = format!("http://{address}/mcp");
        let initialize = client
            .post(&url)
            .header("Accept", "application/json, text/event-stream")
            .json(&json!({
                "jsonrpc":"2.0", "id":1,"method":"initialize",
                "params":{"protocolVersion":"2025-03-26","capabilities":{},
                    "clientInfo":{"name":"test","version":"1"}}
            }))
            .send()
            .await
            .unwrap();
        assert!(initialize.status().is_success());
        let session = initialize
            .headers()
            .get("mcp-session-id")
            .unwrap()
            .to_str()
            .unwrap()
            .to_owned();
        let info = sse_json(&initialize.text().await.unwrap());
        assert_eq!(info["result"]["serverInfo"]["name"], "signoz-rust");

        let tools = client
            .post(&url)
            .header("Accept", "application/json, text/event-stream")
            .header("Mcp-Session-Id", &session)
            .json(&json!({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}))
            .send()
            .await
            .unwrap();
        assert!(tools.status().is_success());
        let listing = sse_json(&tools.text().await.unwrap());
        let names = listing["result"]["tools"].as_array().unwrap();
        assert_eq!(names.len(), 8);
        for name in [
            "signoz_sources",
            "signoz_connection",
            "signoz_search_logs",
            "signoz_search_traces",
            "signoz_query_telemetry",
            "signoz_list_services",
            "signoz_field_keys",
            "signoz_field_values",
        ] {
            assert!(names.iter().any(|tool| tool["name"] == name), "{name}");
        }

        // Argument validation must occur before credential resolution and must
        // surface as an MCP tool error, not as a dropped transport connection.
        let invalid = client
            .post(&url)
            .header("Accept", "application/json, text/event-stream")
            .header("Mcp-Session-Id", &session)
            .json(&json!({"jsonrpc":"2.0","id":3,"method":"tools/call",
            "params":{"name":"signoz_search_logs","arguments":{
                "account_id":"dev","start_ms":0,"end_ms":1
            }}}))
            .send()
            .await
            .unwrap();
        let error = sse_json(&invalid.text().await.unwrap());
        assert_eq!(error["result"]["isError"], true);
        task.abort();
    }

    #[test]
    fn client_pool_capacity_is_configurable_and_bounded() {
        assert_eq!(configured_http_cache_capacity(None).unwrap(), 32);
        assert_eq!(configured_http_cache_capacity(Some("0")).unwrap(), 0);
        assert_eq!(configured_http_cache_capacity(Some("256")).unwrap(), 256);
        for invalid in ["", "-1", "257", "unbounded"] {
            assert!(configured_http_cache_capacity(Some(invalid)).is_err());
        }
    }

    #[test]
    fn optional_fields_match_python_defaults() {
        let query: LogSearch = serde_json::from_value(json!({
            "account_id":"alias","start_ms":100,"end_ms":200
        }))
        .unwrap();
        assert_eq!(query.limit, 100);
        assert_eq!(query.offset, 0);
        assert_eq!(query.filter_expression, "");
    }
}
