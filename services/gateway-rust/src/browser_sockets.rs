//! Browser WebSocket ownership: public OIDC, exact Origin, private API relay.
//! This is not a public WebSocket proxy to arbitrary upstream hosts.
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use axum::{
    extract::{
        Path, State,
        ws::{CloseFrame, Message, WebSocket, WebSocketUpgrade, close_code},
    },
    http::{HeaderMap, HeaderValue, StatusCode, header},
    response::{IntoResponse, Response},
};
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{
    connect_async_with_config,
    tungstenite::{self, client::IntoClientRequest, protocol::WebSocketConfig},
};

use crate::AppState;
use std::sync::Arc;

const RELAY_MESSAGE_BYTES_DEFAULT: usize = 8 * 1024 * 1024;
const RELAY_MESSAGE_BYTES_MAX: usize = 32 * 1024 * 1024;

pub fn websocket_limit() -> anyhow::Result<usize> {
    let value = std::env::var("GATEWAY_WS_MAX_MESSAGE_BYTES")
        .ok()
        .map(|v| v.parse::<usize>())
        .transpose()?
        .unwrap_or(RELAY_MESSAGE_BYTES_DEFAULT);
    anyhow::ensure!(
        (1024..=RELAY_MESSAGE_BYTES_MAX).contains(&value),
        "GATEWAY_WS_MAX_MESSAGE_BYTES outside allowed range"
    );
    Ok(value)
}

fn protocol_token(headers: &HeaderMap) -> Option<String> {
    let mut has_protocol = false;
    let mut tokens = Vec::new();
    for header in headers.get_all(header::SEC_WEBSOCKET_PROTOCOL) {
        let value = header.to_str().ok()?;
        for part in value.split(',').map(str::trim) {
            if part == "briareus.v1" {
                has_protocol = true;
            }
            if let Some(value) = part.strip_prefix("bearer.") {
                tokens.push(value);
            }
        }
    }
    if has_protocol && tokens.len() == 1 && !tokens[0].is_empty() && tokens[0].len() <= 16384 {
        Some(tokens[0].to_owned())
    } else {
        None
    }
}

fn close(code: u16) -> Message {
    Message::Close(Some(CloseFrame {
        code,
        reason: "".into(),
    }))
}

struct RelayConfig {
    backend_url: String,
    bearer: String,
    origin: String,
    forwarded_host: String,
    forwarded_proto: String,
    expires_at: u64,
    max_bytes: usize,
}

async fn relay(mut caller: WebSocket, configuration: RelayConfig) {
    let RelayConfig {
        backend_url,
        bearer,
        origin,
        forwarded_host,
        forwarded_proto,
        expires_at,
        max_bytes,
    } = configuration;
    let mut request = match backend_url.into_client_request() {
        Ok(request) => request,
        Err(_) => {
            let _ = caller.send(close(close_code::ERROR)).await;
            return;
        }
    };
    let headers = request.headers_mut();
    let values = [
        (header::AUTHORIZATION, format!("Bearer {bearer}")),
        (header::ORIGIN, origin),
        (header::SEC_WEBSOCKET_PROTOCOL, "briareus.v1".into()),
        (
            header::HeaderName::from_static("x-forwarded-host"),
            forwarded_host,
        ),
        (
            header::HeaderName::from_static("x-forwarded-proto"),
            forwarded_proto,
        ),
    ];
    for (name, value) in values {
        let Ok(value) = HeaderValue::from_str(&value) else {
            let _ = caller.send(close(close_code::ERROR)).await;
            return;
        };
        headers.insert(name, value);
    }
    let config = WebSocketConfig::default()
        .max_message_size(Some(max_bytes))
        .max_frame_size(Some(max_bytes));
    let attempt = tokio::time::timeout(
        Duration::from_secs(10),
        connect_async_with_config(request, Some(config), false),
    )
    .await;
    let Ok(Ok((backend, _))) = attempt else {
        let _ = caller.send(close(close_code::ERROR)).await;
        return;
    };
    let (mut backend_tx, mut backend_rx) = backend.split();
    let (mut caller_tx, mut caller_rx) = caller.split();
    let mut expiry = tokio::time::interval(Duration::from_secs(1));
    loop {
        tokio::select! {
            _ = expiry.tick() => {
                let now = SystemTime::now().duration_since(UNIX_EPOCH).map_or(u64::MAX, |d| d.as_secs());
                if expires_at <= now {
                    let _ = caller_tx.send(close(4401)).await;
                    break;
                }
            }
            client_message = caller_rx.next() => {
                let Some(Ok(message)) = client_message else { break; };
                let translated = match message {
                    Message::Text(value) => tungstenite::Message::Text(value.to_string().into()),
                    Message::Binary(value) => tungstenite::Message::Binary(value),
                    Message::Ping(value) => tungstenite::Message::Ping(value),
                    Message::Pong(value) => tungstenite::Message::Pong(value),
                    Message::Close(_) => break,
                };
                if backend_tx.send(translated).await.is_err() { break; }
            }
            server_message = backend_rx.next() => {
                let Some(Ok(message)) = server_message else { break; };
                let translated = match message {
                    tungstenite::Message::Text(value) => Message::Text(value.to_string().into()),
                    tungstenite::Message::Binary(value) => Message::Binary(value),
                    tungstenite::Message::Ping(value) => Message::Ping(value),
                    tungstenite::Message::Pong(value) => Message::Pong(value),
                    tungstenite::Message::Close(_) => break,
                    tungstenite::Message::Frame(_) => continue,
                };
                if caller_tx.send(translated).await.is_err() { break; }
            }
        }
    }
    let _ = backend_tx.close().await;
    let _ = caller_tx.close().await;
}

async fn route(
    state: Arc<AppState>,
    upgrade: WebSocketUpgrade,
    headers: HeaderMap,
    target: &str,
) -> Response {
    let Some(token) = protocol_token(&headers) else {
        return StatusCode::UNAUTHORIZED.into_response();
    };
    let Some(public_origin) = state.auth.public_origin() else {
        return StatusCode::UNAUTHORIZED.into_response();
    };
    let origin = headers
        .get(header::ORIGIN)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .trim_end_matches('/')
        .to_owned();
    if origin != public_origin {
        return StatusCode::FORBIDDEN.into_response();
    }
    let Some(verifier) = state.auth.verifier.as_ref() else {
        return StatusCode::UNAUTHORIZED.into_response();
    };
    let Ok(principal) = verifier.verify(&token).await else {
        return StatusCode::UNAUTHORIZED.into_response();
    };
    let Ok(url) = state.api.internal_ws_url(target) else {
        return StatusCode::BAD_GATEWAY.into_response();
    };
    let host = headers
        .get(header::HOST)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_owned();
    let proto = headers
        .get("x-forwarded-proto")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("https")
        .to_owned();
    let Ok(max_bytes) = websocket_limit() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    upgrade
        .protocols(["briareus.v1"])
        .max_message_size(max_bytes)
        .max_frame_size(max_bytes)
        .on_upgrade(move |caller| {
            relay(
                caller,
                RelayConfig {
                    backend_url: url.to_string(),
                    bearer: token,
                    origin,
                    forwarded_host: host,
                    forwarded_proto: proto,
                    expires_at: principal.expires_at,
                    max_bytes,
                },
            )
        })
}

pub async fn realtime(
    State(state): State<Arc<AppState>>,
    upgrade: WebSocketUpgrade,
    headers: HeaderMap,
) -> Response {
    route(state, upgrade, headers, "/admin/api/realtime").await
}

pub async fn operator(
    State(state): State<Arc<AppState>>,
    upgrade: WebSocketUpgrade,
    headers: HeaderMap,
) -> Response {
    route(state, upgrade, headers, "/admin/api/browser/operator/ws").await
}

pub async fn cdp(
    State(state): State<Arc<AppState>>,
    Path(target_id): Path<String>,
    upgrade: WebSocketUpgrade,
    headers: HeaderMap,
) -> Response {
    if target_id.is_empty()
        || target_id.len() > 128
        || !target_id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_'))
    {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let path = format!("/admin/api/browser/cdp/page/{target_id}");
    route(state, upgrade, headers, &path).await
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bearer_protocol_is_unambiguous() {
        let mut headers = HeaderMap::new();
        headers.insert(
            header::SEC_WEBSOCKET_PROTOCOL,
            HeaderValue::from_static("briareus.v1, bearer.fixture"),
        );
        assert_eq!(protocol_token(&headers).as_deref(), Some("fixture"));
        headers.insert(
            header::SEC_WEBSOCKET_PROTOCOL,
            HeaderValue::from_static("briareus.v1, bearer.one, bearer.two"),
        );
        assert!(protocol_token(&headers).is_none());
        headers.insert(
            header::SEC_WEBSOCKET_PROTOCOL,
            HeaderValue::from_static("bearer.fixture"),
        );
        assert!(protocol_token(&headers).is_none());
    }
}
