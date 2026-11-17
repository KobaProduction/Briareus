//! Cookie-stateless bounded-connection HTTP reverse proxy for Control Panel UI/API.
//! MCP forwarding and WebSocket relay intentionally belong to separate authority paths.
use std::time::Duration;

use axum::{
    body::Body,
    http::{HeaderMap, HeaderName, HeaderValue, Request, StatusCode, header},
    response::{IntoResponse, Response},
};
use reqwest::{Client, redirect::Policy};
use url::Url;

#[derive(Clone)]
pub struct Proxy {
    client: Client,
    origin: Url,
    name: &'static str,
}

#[derive(Clone, Copy)]
pub enum ProxyKind {
    Api,
    Ui,
}

const FILTER_HEADERS: &[&str] = &[
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
];

fn allowed_header(name: &HeaderName) -> bool {
    !FILTER_HEADERS.contains(&name.as_str())
}

impl Proxy {
    pub fn new(raw_origin: &str, name: &'static str) -> anyhow::Result<Self> {
        let origin = Url::parse(raw_origin)?;
        anyhow::ensure!(
            matches!(origin.scheme(), "http" | "https")
                && origin.host().is_some()
                && origin.username().is_empty()
                && origin.password().is_none()
                && origin.query().is_none()
                && origin.fragment().is_none()
                && origin.path() == "/",
            "Backend origin must be an http(s) root origin without credentials"
        );
        let client = Client::builder()
            .redirect(Policy::none())
            .no_proxy()
            .connect_timeout(Duration::from_secs(3))
            .pool_max_idle_per_host(16)
            .build()?;
        Ok(Self {
            client,
            origin,
            name,
        })
    }

    pub fn internal_ws_url(&self, path: &str) -> anyhow::Result<Url> {
        let mut url = self.origin.clone();
        let scheme = if url.scheme() == "https" { "wss" } else { "ws" };
        url.set_scheme(scheme)
            .map_err(|_| anyhow::anyhow!("invalid WebSocket scheme"))?;
        url.set_path(path);
        url.set_query(None);
        url.set_fragment(None);
        Ok(url)
    }

    fn upstream_path(kind: ProxyKind, path: &str) -> &str {
        match kind {
            ProxyKind::Api => path.strip_prefix("/api").unwrap_or(path),
            ProxyKind::Ui => path.strip_prefix("/admin").unwrap_or(path),
        }
    }

    fn without_backend_origin(&self, raw: &str) -> Option<String> {
        let parsed = Url::parse(raw).ok()?;
        if parsed.origin() != self.origin.origin()
            || !parsed.username().is_empty()
            || parsed.password().is_some()
        {
            return None;
        }
        let mut relative = parsed.path().to_owned();
        if let Some(query) = parsed.query() {
            relative.push('?');
            relative.push_str(query);
        }
        if let Some(fragment) = parsed.fragment() {
            relative.push('#');
            relative.push_str(fragment);
        }
        Some(relative)
    }

    fn rewrite_location(&self, value: &HeaderValue) -> HeaderValue {
        let Ok(raw) = value.to_str() else {
            return value.clone();
        };
        let mut result = self
            .without_backend_origin(raw)
            .unwrap_or_else(|| raw.to_owned());
        // Python ReverseProxy also rewrites callback URLs inside Location query
        // parameters. Do not rewrite a foreign or lookalike authority.
        let (path, fragment) = result.split_once('#').unwrap_or((&result, ""));
        let (pathname, query) = path.split_once('?').unwrap_or((path, ""));
        if !query.is_empty() {
            let items: Vec<(String, String)> = url::form_urlencoded::parse(query.as_bytes())
                .map(|(key, value)| (key.into_owned(), value.into_owned()))
                .collect();
            let mut changed = false;
            let normalized: Vec<(String, String)> = items
                .into_iter()
                .map(|(key, value)| {
                    if let Some(replacement) = self.without_backend_origin(&value) {
                        changed = true;
                        (key, replacement)
                    } else {
                        (key, value)
                    }
                })
                .collect();
            if changed {
                let new_query = url::form_urlencoded::Serializer::new(String::new())
                    .extend_pairs(normalized)
                    .finish();
                let mut rewritten = format!("{pathname}?{new_query}");
                if !fragment.is_empty() {
                    rewritten.push('#');
                    rewritten.push_str(fragment);
                }
                result = rewritten;
            }
        }
        HeaderValue::from_str(&result).unwrap_or_else(|_| value.clone())
    }

    pub async fn forward(&self, request: Request<Body>, kind: ProxyKind) -> Response {
        let (parts, body) = request.into_parts();
        let suffix = Self::upstream_path(kind, parts.uri.path());
        let target_path = match kind {
            ProxyKind::Api => format!("/admin/api{suffix}"),
            ProxyKind::Ui => {
                if suffix.is_empty() {
                    "/".to_owned()
                } else {
                    suffix.to_owned()
                }
            }
        };
        let mut target = self.origin.clone();
        target.set_path(&target_path);
        target.set_query(parts.uri.query());
        let mut outbound = self
            .client
            .request(parts.method.clone(), target)
            .body(reqwest::Body::wrap_stream(body.into_data_stream()));
        let mut headers = HeaderMap::new();
        for (name, value) in &parts.headers {
            if allowed_header(name)
                && name != header::HOST
                && name != header::CONTENT_LENGTH
                && name.as_str() != "x-forwarded-host"
                && name.as_str() != "x-forwarded-proto"
            {
                headers.append(name, value.clone());
            }
        }
        if let Some(host) = parts.headers.get(header::HOST) {
            headers.insert("x-forwarded-host", host.clone());
            headers.insert(header::HOST, host.clone());
        }
        let public_proto = parts
            .headers
            .get("x-forwarded-proto")
            .cloned()
            .unwrap_or_else(|| HeaderValue::from_static("http"));
        headers.insert("x-forwarded-proto", public_proto);
        outbound = outbound.headers(headers);
        let result = match tokio::time::timeout(Duration::from_secs(30), outbound.send()).await {
            Ok(Ok(result)) => result,
            _ => {
                return (
                    StatusCode::BAD_GATEWAY,
                    format!("{} backend unavailable", self.name),
                )
                    .into_response();
            }
        };
        let status = result.status();
        let mut builder = Response::builder().status(status);
        for (name, value) in result.headers() {
            if !allowed_header(name) || name == header::CONTENT_LENGTH {
                continue;
            }
            let header_value = if name == header::LOCATION {
                self.rewrite_location(value)
            } else {
                value.clone()
            };
            builder = builder.header(name, header_value);
        }
        builder
            .body(Body::from_stream(result.bytes_stream()))
            .unwrap_or_else(|_| StatusCode::BAD_GATEWAY.into_response())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn backend_only_accepts_private_explicit_origin() {
        assert!(Proxy::new("http://127.0.0.1:8080", "api").is_ok());
        for invalid in [
            "file:///etc/passwd",
            "http://u:p@localhost:42",
            "http://localhost:42/path",
            "https://localhost/?token=secret",
        ] {
            assert!(Proxy::new(invalid, "api").is_err());
        }
    }
    #[test]
    fn internal_location_is_rewritten_and_external_retained() {
        let p = Proxy::new("http://api.test:8000", "api").unwrap();
        assert_eq!(
            p.rewrite_location(&HeaderValue::from_static(
                "http://api.test:8000/admin/api/users"
            )),
            "/admin/api/users"
        );
        assert_eq!(
            p.rewrite_location(&HeaderValue::from_static("https://external.test/redirect")),
            "https://external.test/redirect"
        );
    }
}
