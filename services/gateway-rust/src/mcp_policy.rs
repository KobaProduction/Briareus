//! Read the existing Control Panel runtime policy with the existing service
//! credential. No separate operator input or provider registration.
use serde::Deserialize;
use std::{future::Future, sync::Arc, time::Duration};
use tokio::{sync::Mutex, time::Instant};

#[derive(Clone, Default)]
pub struct McpPolicy(Option<Arc<PolicyClient>>);

struct PolicyClient {
    http: reqwest::Client,
    endpoint: url::Url,
    authorization: reqwest::header::HeaderValue,
    cached: Mutex<Option<(Instant, u64)>>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PolicyReply {
    call_timeout_seconds: u64,
}

impl McpPolicy {
    pub fn new(origin: &str, service_token: &str) -> anyhow::Result<Self> {
        let endpoint = url::Url::parse(origin)?.join("/internal/runtime-settings/mcp")?;
        let mut authorization =
            reqwest::header::HeaderValue::from_str(&format!("Bearer {service_token}"))
                .map_err(|_| anyhow::anyhow!("Invalid private service credential"))?;
        authorization.set_sensitive(true);
        let http = reqwest::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(1))
            .build()?;
        Ok(Self(Some(Arc::new(PolicyClient {
            http,
            endpoint,
            authorization,
            cached: Mutex::new(None),
        }))))
    }

    async fn seconds(&self) -> u64 {
        let Some(client) = &self.0 else { return 0 };
        let mut cached = client.cached.lock().await;
        if let Some((deadline, seconds)) = *cached
            && deadline > Instant::now()
        {
            return seconds;
        }
        let seconds = client.fetch().await.unwrap_or_default();
        *cached = Some((Instant::now() + Duration::from_secs(5), seconds));
        seconds
    }

    pub async fn run<T, E>(
        &self,
        metadata: bool,
        future: impl Future<Output = Result<T, E>>,
    ) -> Result<T, ()> {
        let seconds = self.seconds().await;
        let seconds = if metadata { seconds.max(30) } else { seconds };
        if seconds == 0 {
            future.await.map_err(|_| ())
        } else {
            tokio::time::timeout(Duration::from_secs(seconds), future)
                .await
                .map_err(|_| ())?
                .map_err(|_| ())
        }
    }
}

impl PolicyClient {
    async fn fetch(&self) -> Option<u64> {
        let mut response = self
            .http
            .get(self.endpoint.clone())
            .header(reqwest::header::AUTHORIZATION, self.authorization.clone())
            .header(reqwest::header::ACCEPT, "application/json")
            .send()
            .await
            .ok()?
            .error_for_status()
            .ok()?;
        let mut body = Vec::new();
        while let Some(chunk) = response.chunk().await.ok()? {
            if body.len() + chunk.len() > 4096 {
                return None;
            }
            body.extend_from_slice(&chunk);
        }
        let reply: PolicyReply = serde_json::from_slice(&body).ok()?;
        (reply.call_timeout_seconds <= 300).then_some(reply.call_timeout_seconds)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        Json, Router,
        http::{HeaderMap, StatusCode},
        routing::get,
    };

    #[tokio::test]
    async fn existing_private_policy_controls_tool_deadline() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        let server = Router::new().route(
            "/internal/runtime-settings/mcp",
            get(|headers: HeaderMap| async move {
                if headers
                    .get("authorization")
                    .and_then(|value| value.to_str().ok())
                    != Some("Bearer fixture-service-token")
                {
                    return Err(StatusCode::UNAUTHORIZED);
                }
                Ok(Json(serde_json::json!({"call_timeout_seconds":1})))
            }),
        );
        let task = tokio::spawn(async move { axum::serve(listener, server).await.unwrap() });
        let policy = McpPolicy::new(&origin, "fixture-service-token").unwrap();
        assert_eq!(policy.seconds().await, 1);
        assert!(
            policy
                .run(false, async {
                    tokio::time::sleep(Duration::from_millis(1100)).await;
                    Ok::<_, ()>(())
                })
                .await
                .is_err()
        );
        assert_eq!(McpPolicy::default().seconds().await, 0);
        task.abort();
    }
}
