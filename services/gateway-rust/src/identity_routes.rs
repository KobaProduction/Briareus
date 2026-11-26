//! Same bounded private identity RPC and public browser configuration as Python Gateway.
use axum::{
    Json,
    body::{Body, to_bytes},
    http::{HeaderMap, HeaderValue, Request, StatusCode, header},
    response::{IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::{Value, json};
use subtle::ConstantTimeEq;

use crate::auth::ShadowOidc;

pub const METADATA_PATH: &str = "/internal/identity/v1/metadata";
pub const VERIFY_PATH: &str = "/internal/identity/v1/verify";
const INTERNAL_HOST: &str = "gateway:8000";
const MAX_MESSAGE_BYTES: usize = 65536;

#[derive(Clone)]
pub struct IdentityRoutes {
    metadata: Value,
    browser_config: Value,
    service_authorization: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct VerifyRequest {
    token: String,
}

fn one_header(headers: &HeaderMap, name: header::HeaderName) -> Option<&HeaderValue> {
    let mut values = headers.get_all(name).iter();
    let first = values.next()?;
    values.next().is_none().then_some(first)
}

fn no_store(mut response: Response) -> Response {
    response
        .headers_mut()
        .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    response
}

impl IdentityRoutes {
    pub fn new(
        auth: &ShadowOidc,
        node: &str,
        service_token: String,
        browser_client_id: &str,
    ) -> anyhow::Result<Self> {
        anyhow::ensure!(
            auth.verifier.is_some() && !service_token.trim().is_empty(),
            "Private Gateway service authentication is required"
        );
        let origin = auth
            .public_origin()
            .ok_or_else(|| anyhow::anyhow!("Public origin required"))?;
        Ok(Self {
            metadata: json!({"version":1,"node_id":node,"public_origin":origin}),
            browser_config: auth.browser_configuration(browser_client_id)?,
            service_authorization: format!("Bearer {service_token}"),
        })
    }

    fn admission_error(&self, headers: &HeaderMap) -> Option<Response> {
        if one_header(headers, header::HOST).and_then(|v| v.to_str().ok()) != Some(INTERNAL_HOST) {
            return Some(StatusCode::NOT_FOUND.into_response());
        }
        if !one_header(headers, header::AUTHORIZATION).is_some_and(|value| {
            bool::from(
                value
                    .as_bytes()
                    .ct_eq(self.service_authorization.as_bytes()),
            )
        }) {
            let mut response = StatusCode::UNAUTHORIZED.into_response();
            response.headers_mut().insert(
                header::WWW_AUTHENTICATE,
                HeaderValue::from_static("Bearer realm=\"briareus-internal\""),
            );
            return Some(response);
        }
        None
    }

    pub fn metadata(&self, headers: &HeaderMap) -> Response {
        if let Some(response) = self.admission_error(headers) {
            return response;
        }
        no_store(Json(self.metadata.clone()).into_response())
    }

    pub fn browser_config(&self, auth: &ShadowOidc, headers: &HeaderMap) -> Response {
        if one_header(headers, header::HOST).and_then(|v| v.to_str().ok()) != auth.public_host() {
            return StatusCode::MISDIRECTED_REQUEST.into_response();
        }
        no_store(Json(self.browser_config.clone()).into_response())
    }

    pub async fn verify(&self, auth: &ShadowOidc, node: &str, request: Request<Body>) -> Response {
        if let Some(response) = self.admission_error(request.headers()) {
            return response;
        }
        let Ok(body) = to_bytes(request.into_body(), MAX_MESSAGE_BYTES).await else {
            return StatusCode::PAYLOAD_TOO_LARGE.into_response();
        };
        let Ok(input) = serde_json::from_slice::<VerifyRequest>(&body) else {
            return StatusCode::BAD_REQUEST.into_response();
        };
        if input.token.is_empty() || input.token.len() > 16384 {
            return StatusCode::BAD_REQUEST.into_response();
        }
        let Some(verifier) = auth.verifier.as_ref() else {
            return StatusCode::SERVICE_UNAVAILABLE.into_response();
        };
        match verifier.verify(&input.token).await {
            Ok(principal) => {
                if [
                    &principal.subject,
                    &principal.username,
                    &principal.display_name,
                    &principal.client_id,
                ]
                .iter()
                .any(|v| v.is_empty() || v.chars().count() > 4096)
                    || principal.roles.len() > 256
                    || principal.scopes.len() > 256
                {
                    return StatusCode::SERVICE_UNAVAILABLE.into_response();
                }
                let message = json!({
                    "version":1, "node_id":node, "subject":principal.subject,
                    "username":principal.username, "display_name":principal.display_name,
                    "roles":principal.roles, "expires_at":principal.expires_at,
                    "client_id":principal.client_id, "scopes":principal.scopes,
                });
                if serde_json::to_vec(&message).map_or(true, |body| body.len() > MAX_MESSAGE_BYTES)
                {
                    return StatusCode::SERVICE_UNAVAILABLE.into_response();
                }
                no_store(Json(message).into_response())
            }
            Err(error) => match error.reason {
                "missing_grant" => StatusCode::FORBIDDEN.into_response(),
                "provider_unavailable" | "introspection_failed" => {
                    StatusCode::SERVICE_UNAVAILABLE.into_response()
                }
                _ => StatusCode::UNAUTHORIZED.into_response(),
            },
        }
    }
}
