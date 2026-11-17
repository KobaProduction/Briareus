//! Shared bounded JSON transport for provider Hands.
//! No automatic redirects: provider/service credentials must not follow 3xx to another host.
use std::time::Duration;

use reqwest::{
    Client, Method, Url,
    header::{HeaderMap, HeaderName, HeaderValue},
};
use serde_json::Value;

use crate::errors::HandError;

const MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;

#[derive(Clone)]
pub struct JsonHttp {
    client: Client,
    origin: Url,
    auth_name: HeaderName,
    auth_value: HeaderValue,
}

impl JsonHttp {
    pub fn new(
        origin: &str,
        header: &str,
        secret: &str,
        verify_tls: bool,
        ca_cert_pem: Option<&str>,
    ) -> Result<Self, HandError> {
        let origin = Url::parse(origin).map_err(|_| HandError::Configuration)?;
        if !matches!(origin.scheme(), "http" | "https")
            || origin.host_str().is_none()
            || !origin.username().is_empty()
            || origin.password().is_some()
            || origin.query().is_some()
            || origin.fragment().is_some()
        {
            return Err(HandError::Configuration);
        }
        let auth_name =
            HeaderName::from_bytes(header.as_bytes()).map_err(|_| HandError::Configuration)?;
        let auth_value = HeaderValue::from_str(secret).map_err(|_| HandError::Configuration)?;
        let mut builder = Client::builder()
            .timeout(Duration::from_secs(30))
            .connect_timeout(Duration::from_secs(8))
            .pool_max_idle_per_host(4)
            .redirect(reqwest::redirect::Policy::none())
            .danger_accept_invalid_certs(!verify_tls);
        if let Some(pem) = ca_cert_pem {
            if !pem.is_empty() {
                let pem = pem.replace("\\n", "\n");
                let cert = reqwest::Certificate::from_pem(pem.as_bytes())
                    .map_err(|_| HandError::Configuration)?;
                builder = builder.add_root_certificate(cert);
            }
        }
        Ok(Self {
            client: builder.build().map_err(|_| HandError::Configuration)?,
            origin,
            auth_name,
            auth_value,
        })
    }

    fn target(&self, segments: &[&str], query: &[(&str, &str)]) -> Result<Url, HandError> {
        let mut url = self.origin.clone();
        {
            let mut path = url
                .path_segments_mut()
                .map_err(|_| HandError::Configuration)?;
            path.pop_if_empty();
            for segment in segments {
                if segment.is_empty()
                    || matches!(*segment, "." | "..")
                    || segment.contains('/')
                    || segment.contains('\\')
                {
                    return Err(HandError::Invalid("invalid API route segment".into()));
                }
                path.push(segment);
            }
        }
        if !query.is_empty() {
            url.query_pairs_mut().extend_pairs(query);
        }
        Ok(url)
    }

    /// Send a JSON command to a private service that returns HTTP 204.
    ///
    /// Unlike `json`, this does not deserialize a response body. No redirects
    /// or raw upstream error bodies are exposed to the caller.
    pub async fn post_no_content(
        &self,
        segments: &[&str],
        payload: &Value,
    ) -> Result<(), HandError> {
        let url = self.target(segments, &[])?;
        let mut headers = HeaderMap::new();
        headers.insert(self.auth_name.clone(), self.auth_value.clone());
        headers.insert(
            reqwest::header::ACCEPT,
            HeaderValue::from_static("application/json"),
        );
        let response = self
            .client
            .post(url)
            .headers(headers)
            .json(payload)
            .send()
            .await
            .map_err(|_| HandError::Transport)?;
        let status = response.status();
        if status.as_u16() == 401 {
            return Err(HandError::Unauthorized);
        }
        if status.as_u16() == 403 {
            return Err(HandError::Forbidden);
        }
        if status != reqwest::StatusCode::NO_CONTENT {
            return Err(HandError::UpstreamStatus(status.as_u16()));
        }
        Ok(())
    }

    pub async fn json(
        &self,
        method: Method,
        segments: &[&str],
        query: &[(&str, &str)],
        payload: Option<&Value>,
    ) -> Result<Value, HandError> {
        let url = self.target(segments, query)?;
        let mut headers = HeaderMap::new();
        headers.insert(self.auth_name.clone(), self.auth_value.clone());
        headers.insert(
            reqwest::header::ACCEPT,
            HeaderValue::from_static("application/json"),
        );
        let mut request = self.client.request(method, url).headers(headers);
        if let Some(payload) = payload {
            request = request.json(payload);
        }
        let mut response = request.send().await.map_err(|_| HandError::Transport)?;
        let status = response.status();
        if status.as_u16() == 401 {
            return Err(HandError::Unauthorized);
        }
        if status.as_u16() == 403 {
            return Err(HandError::Forbidden);
        }
        if !status.is_success() {
            return Err(HandError::UpstreamStatus(status.as_u16()));
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|_| HandError::Transport)? {
            if chunk.len() > MAX_RESPONSE_BYTES.saturating_sub(bytes.len()) {
                return Err(HandError::InvalidResponse);
            }
            bytes.extend_from_slice(&chunk);
        }
        serde_json::from_slice(&bytes).map_err(|_| HandError::InvalidResponse)
    }
}

#[cfg(test)]
mod tests {
    use super::JsonHttp;

    #[test]
    fn rejects_credentials_in_origin_and_paths_that_escape_api() {
        for origin in [
            "https://user:password@example.test",
            "file:///tmp/test",
            "https://example.test/?bearer=sensitive",
        ] {
            assert!(JsonHttp::new(origin, "SIGNOZ-API-KEY", "fake", true, None).is_err());
        }
        let http = JsonHttp::new(
            "http://127.0.0.1:5050/base",
            "SIGNOZ-API-KEY",
            "fake",
            true,
            None,
        )
        .unwrap();
        assert_eq!(
            http.target(&["api", "v5", "query_range"], &[])
                .unwrap()
                .path(),
            "/base/api/v5/query_range"
        );
        assert!(http.target(&["api", "../internal"], &[]).is_err());
        assert!(http.target(&["api", "foo/bar"], &[]).is_err());
    }
}
