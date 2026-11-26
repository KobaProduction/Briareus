//! Optional RFC 7662 verification for opaque access tokens. Secrets remain
//! exclusively in process memory; cache indexes contain only SHA-256 digests.
use std::{
    collections::{HashMap, VecDeque},
    sync::Arc,
    time::{Duration, Instant},
};

use futures_util::StreamExt;
use reqwest::{Client, Response, redirect::Policy};
use serde_json::Value;
use sha2::{Digest, Sha256};
use tokio::sync::Mutex;

use crate::{OidcSettings, TokenError, VerifiedPrincipal, audience_and_roles, permitted_url};

const RESPONSE_BYTES: usize = 65536;
const TOKEN_BYTES: usize = 16384;
const CACHE_CAPACITY: usize = 256;
const RESULT_TTL: Duration = Duration::from_secs(30);
const METADATA_TTL: Duration = Duration::from_secs(300);

#[derive(Default)]
struct PrincipalCache {
    entries: HashMap<[u8; 32], (Instant, VerifiedPrincipal)>,
    recent: VecDeque<[u8; 32]>,
}

impl PrincipalCache {
    fn lookup(&mut self, id: &[u8; 32]) -> Option<VerifiedPrincipal> {
        if let Some((valid_until, principal)) = self.entries.get(id)
            && *valid_until > Instant::now()
            && principal.expires_at > unix_now()
        {
            let selected = principal.clone();
            self.recent.retain(|record| record != id);
            self.recent.push_back(*id);
            return Some(selected);
        }
        self.entries.remove(id);
        self.recent.retain(|record| record != id);
        None
    }

    fn insert(&mut self, id: [u8; 32], value: VerifiedPrincipal) {
        if self.entries.contains_key(&id) {
            self.recent.retain(|record| record != &id);
        } else if self.entries.len() >= CACHE_CAPACITY
            && let Some(old) = self.recent.pop_front()
        {
            self.entries.remove(&old);
        }
        self.entries
            .insert(id, (Instant::now() + RESULT_TTL, value));
        self.recent.push_back(id);
    }
}

fn unix_now() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(u64::MAX, |duration| duration.as_secs())
}

#[derive(Clone)]
pub struct IntrospectionVerifier {
    settings: Arc<OidcSettings>,
    client: Client,
    client_id: Arc<str>,
    client_secret: Arc<str>,
    endpoint: Arc<Mutex<Option<(Instant, String)>>>,
    cache: Arc<Mutex<PrincipalCache>>,
}

impl IntrospectionVerifier {
    pub fn new(
        settings: OidcSettings,
        client_id: String,
        client_secret: String,
    ) -> Result<Self, TokenError> {
        permitted_url(&settings.issuer)?;
        if settings.audience.is_empty()
            || settings.required_role.is_empty()
            || settings.audience.trim() != settings.audience
            || settings.required_role.trim() != settings.required_role
            || settings.roles_claim_path.is_empty()
            || settings.roles_claim_path.iter().any(String::is_empty)
            || (settings.roles_format == crate::RolesFormat::OrganizationGrants
                && settings.roles_organization_id.is_empty())
            || settings.algorithms.is_empty()
            || settings.algorithms.iter().any(|value| {
                !matches!(
                    value.as_str(),
                    "RS256" | "RS384" | "RS512" | "ES256" | "ES384" | "ES512" | "EdDSA"
                )
            })
            || client_id.trim().is_empty()
            || client_secret.is_empty()
        {
            return Err(TokenError {
                reason: "invalid_claims",
            });
        }
        let client = Client::builder()
            .redirect(Policy::none())
            .connect_timeout(Duration::from_secs(3))
            .timeout(Duration::from_secs(5))
            .pool_max_idle_per_host(4)
            .build()
            .map_err(|_| TokenError {
                reason: "invalid_claims",
            })?;
        Ok(Self {
            settings: Arc::new(settings),
            client,
            client_id: client_id.into(),
            client_secret: client_secret.into(),
            endpoint: Arc::new(Mutex::new(None)),
            cache: Arc::new(Mutex::new(PrincipalCache::default())),
        })
    }

    async fn read_bounded(response: Response, code: &'static str) -> Result<Value, TokenError> {
        let failed = TokenError { reason: code };
        if !response.status().is_success()
            || response
                .content_length()
                .is_some_and(|n| n > RESPONSE_BYTES as u64)
        {
            return Err(failed);
        }
        let mut bytes = Vec::new();
        let mut stream = response.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|_| failed)?;
            if bytes.len().saturating_add(chunk.len()) > RESPONSE_BYTES {
                return Err(failed);
            }
            bytes.extend_from_slice(&chunk);
        }
        serde_json::from_slice(&bytes).map_err(|_| failed)
    }

    async fn introspection_endpoint(&self) -> Result<String, TokenError> {
        let mut cached = self.endpoint.lock().await;
        if let Some((valid_until, url)) = cached.as_ref()
            && *valid_until > Instant::now()
        {
            return Ok(url.clone());
        }
        let metadata_url = format!(
            "{}/.well-known/openid-configuration",
            self.settings.issuer.trim_end_matches('/')
        );
        let result = self
            .client
            .get(metadata_url)
            .send()
            .await
            .map_err(|_| TokenError {
                reason: "provider_unavailable",
            })?;
        let metadata = Self::read_bounded(result, "provider_unavailable").await?;
        if metadata.get("issuer").and_then(Value::as_str) != Some(self.settings.issuer.as_str()) {
            return Err(TokenError {
                reason: "invalid_issuer",
            });
        }
        let endpoint = metadata
            .get("introspection_endpoint")
            .and_then(Value::as_str)
            .ok_or(TokenError {
                reason: "provider_unavailable",
            })?;
        let url = permitted_url(endpoint).map_err(|_| TokenError {
            reason: "provider_unavailable",
        })?;
        let target = url.as_str().to_owned();
        *cached = Some((Instant::now() + METADATA_TTL, target.clone()));
        Ok(target)
    }

    pub async fn verify(&self, token: &str) -> Result<VerifiedPrincipal, TokenError> {
        if token.is_empty() || token.len() > TOKEN_BYTES {
            return Err(TokenError {
                reason: "invalid_token",
            });
        }
        let key: [u8; 32] = Sha256::digest(token.as_bytes()).into();
        if let Some(principal) = self.cache.lock().await.lookup(&key) {
            return Ok(principal);
        }
        let url = self.introspection_endpoint().await?;
        // Match Python httpx.BasicAuth(quote_plus(id), quote_plus(secret)).
        let encoded = |value: &str| {
            url::form_urlencoded::byte_serialize(value.as_bytes())
                .collect::<String>()
                .replace("%20", "+")
        };
        let response = self
            .client
            .post(&url)
            .basic_auth(encoded(&self.client_id), Some(encoded(&self.client_secret)))
            .form(&[("token", token), ("token_type_hint", "access_token")])
            .send()
            .await
            .map_err(|_| TokenError {
                reason: "provider_unavailable",
            })?;
        let value = Self::read_bounded(response, "introspection_failed").await?;
        match value.get("active") {
            Some(Value::Bool(true)) => {}
            Some(Value::Bool(false)) => return Err(TokenError { reason: "inactive" }),
            _ => {
                return Err(TokenError {
                    reason: "invalid_token",
                });
            }
        }
        if value.get("iss").and_then(Value::as_str) != Some(self.settings.issuer.as_str()) {
            return Err(TokenError {
                reason: "invalid_issuer",
            });
        }
        let audience = value.get("aud");
        let correct_audience = audience.and_then(Value::as_str)
            == Some(self.settings.audience.as_str())
            || audience.and_then(Value::as_array).is_some_and(|values| {
                values
                    .iter()
                    .any(|value| value.as_str() == Some(self.settings.audience.as_str()))
            });
        if !correct_audience {
            return Err(TokenError {
                reason: "invalid_audience",
            });
        }
        let principal = audience_and_roles(&value, &self.settings)?;
        self.cache.lock().await.insert(key, principal.clone());
        Ok(principal)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounded_principal_cache_lru_eviction_and_timeout() {
        let mut cache = PrincipalCache::default();
        for n in 0..(CACHE_CAPACITY + 20) {
            let mut key = [0u8; 32];
            key[..8].copy_from_slice(&(n as u64).to_le_bytes());
            cache.insert(
                key,
                VerifiedPrincipal {
                    subject: "fixture".into(),
                    username: "fixture".into(),
                    display_name: "Fixture".into(),
                    roles: vec!["tambov".into()],
                    client_id: "client".into(),
                    expires_at: unix_now() + 120,
                    scopes: vec![],
                },
            );
        }
        assert_eq!(cache.entries.len(), CACHE_CAPACITY);
        assert!(cache.lookup(&[0u8; 32]).is_none());
        let mut last = [0u8; 32];
        last[..8].copy_from_slice(&((CACHE_CAPACITY + 19) as u64).to_le_bytes());
        assert!(cache.lookup(&last).is_some());
    }
}
