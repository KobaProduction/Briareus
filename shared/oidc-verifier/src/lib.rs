//! External access-token verifier. This library never issues tokens or owns human sessions.
mod es512;
pub use es512::verify_es512;
pub mod introspection;
pub use introspection::IntrospectionVerifier;

#[derive(Clone)]
pub enum ExternalTokenVerifier {
    Jwt(JwtTokenVerifier),
    Introspection(IntrospectionVerifier),
}

impl ExternalTokenVerifier {
    pub async fn verify(&self, token: &str) -> Result<VerifiedPrincipal, TokenError> {
        match self {
            Self::Jwt(client) => client.verify(token).await,
            Self::Introspection(client) => client.verify(token).await,
        }
    }
}
use std::{
    sync::Arc,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use futures_util::StreamExt;
use jsonwebtoken::{Algorithm, DecodingKey, crypto, jwk::Jwk};
use reqwest::{Client, redirect::Policy};
use serde::Deserialize;
use serde_json::Value;
use tokio::sync::{Mutex, RwLock};
use url::Url;

const MAX_TOKEN_BYTES: usize = 16384;
const MAX_PROVIDER_BYTES: usize = 65536;
const CACHE_LIFETIME: Duration = Duration::from_secs(300);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TokenError {
    pub reason: &'static str,
}
impl std::fmt::Display for TokenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "OIDC token rejected: {}", self.reason)
    }
}
impl std::error::Error for TokenError {}
const INVALID: TokenError = TokenError {
    reason: "invalid_token",
};
const CONFIG: TokenError = TokenError {
    reason: "invalid_claims",
};
const UNAVAILABLE: TokenError = TokenError {
    reason: "provider_unavailable",
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RolesFormat {
    List,
    OrganizationGrants,
}

#[derive(Clone, Debug)]
pub struct OidcSettings {
    pub issuer: String,
    pub audience: String,
    pub required_role: String,
    pub roles_claim_path: Vec<String>,
    pub roles_format: RolesFormat,
    pub roles_organization_id: String,
    pub algorithms: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedPrincipal {
    pub subject: String,
    pub username: String,
    pub display_name: String,
    pub roles: Vec<String>,
    pub client_id: String,
    pub expires_at: u64,
    pub scopes: Vec<String>,
}

#[derive(Deserialize)]
struct ProviderMetadata {
    issuer: String,
    jwks_uri: String,
}

struct CachedKeys {
    expires: Instant,
    keys: JwkSet,
}

#[derive(Clone)]
pub struct JwtTokenVerifier {
    settings: Arc<OidcSettings>,
    client: Client,
    cache: Arc<RwLock<Option<CachedKeys>>>,
    refresh_guard: Arc<Mutex<()>>,
}

pub(crate) fn permitted_url(value: &str) -> Result<Url, TokenError> {
    let url = Url::parse(value).map_err(|_| CONFIG)?;
    let host = url.host_str().ok_or(CONFIG)?;
    let local = matches!(host, "localhost" | "127.0.0.1" | "[::1]") || host.ends_with(".localhost");
    if !(url.scheme() == "https" || (url.scheme() == "http" && local))
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || value.trim() != value
    {
        return Err(CONFIG);
    }
    Ok(url)
}

const ALGORITHMS: [&str; 7] = [
    "RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA",
];

impl OidcSettings {
    fn validate_bootstrap(&self) -> Result<(), TokenError> {
        permitted_url(&self.issuer)?;
        if self.audience.is_empty()
            || self.audience.trim() != self.audience
            || self.required_role.is_empty()
            || self.required_role.trim() != self.required_role
            || self.roles_claim_path.is_empty()
            || self.roles_claim_path.iter().any(String::is_empty)
            || (self.roles_format == RolesFormat::OrganizationGrants
                && self.roles_organization_id.is_empty())
        {
            return Err(CONFIG);
        }
        if self.algorithms.is_empty()
            || self.algorithms.len() > ALGORITHMS.len()
            || !self
                .algorithms
                .iter()
                .all(|alg| ALGORITHMS.contains(&alg.as_str()))
        {
            return Err(CONFIG);
        }
        Ok(())
    }
}

#[derive(Clone, Deserialize)]
struct JwkSet {
    keys: Vec<Value>,
}

impl JwkSet {
    fn find(&self, kid: &str) -> Result<Option<&Value>, TokenError> {
        let mut matches = self
            .keys
            .iter()
            .filter(|key| key.get("kid").and_then(Value::as_str) == Some(kid));
        let key = matches.next();
        if matches.next().is_some() {
            return Err(TokenError {
                reason: "invalid_signature",
            });
        }
        Ok(key)
    }
}

#[derive(Deserialize)]
struct ProtectedHeader {
    alg: String,
    kid: String,
    #[serde(default)]
    crit: Vec<String>,
    b64: Option<bool>,
}

struct SignedJwt<'a> {
    header: ProtectedHeader,
    input: &'a str,
    payload: &'a str,
    signature: &'a str,
}

impl<'a> SignedJwt<'a> {
    fn parse(token: &'a str) -> Result<Self, TokenError> {
        if token.is_empty() || token.len() > MAX_TOKEN_BYTES {
            return Err(INVALID);
        }
        let (input, signature) = token.rsplit_once('.').ok_or(INVALID)?;
        let (header, payload) = input.split_once('.').ok_or(INVALID)?;
        if header.is_empty() || payload.is_empty() || signature.is_empty() || payload.contains('.')
        {
            return Err(INVALID);
        }
        let bytes = URL_SAFE_NO_PAD.decode(header).map_err(|_| INVALID)?;
        let header: ProtectedHeader = serde_json::from_slice(&bytes).map_err(|_| INVALID)?;
        if header.kid.is_empty() || !header.crit.is_empty() || header.b64 == Some(false) {
            return Err(INVALID);
        }
        Ok(Self {
            header,
            input,
            payload,
            signature,
        })
    }

    fn verify(&self, jwk: &Value) -> Result<Value, TokenError> {
        let algorithm = self.header.alg.as_str();
        let bad_signature = TokenError {
            reason: "invalid_signature",
        };
        if algorithm == "ES512" {
            let signature = URL_SAFE_NO_PAD
                .decode(self.signature)
                .map_err(|_| bad_signature)?;
            verify_es512(jwk, self.input.as_bytes(), &signature)?;
        } else {
            es512::check_key_policy(jwk, algorithm)?;
            // Keep the existing SDK/backend for the six other approved JWA algorithms.
            let expected = match algorithm {
                "RS256" | "RS384" | "RS512" => ("RSA", None),
                "ES256" => ("EC", Some("P-256")),
                "ES384" => ("EC", Some("P-384")),
                "EdDSA" => ("OKP", Some("Ed25519")),
                _ => {
                    return Err(TokenError {
                        reason: "invalid_algorithm",
                    });
                }
            };
            if jwk.get("kty").and_then(Value::as_str) != Some(expected.0)
                || expected
                    .1
                    .is_some_and(|curve| jwk.get("crv").and_then(Value::as_str) != Some(curve))
            {
                return Err(bad_signature);
            }
            let algorithm: Algorithm = algorithm.parse().map_err(|_| bad_signature)?;
            let jwk: Jwk = serde_json::from_value(jwk.clone()).map_err(|_| bad_signature)?;
            let key = DecodingKey::from_jwk(&jwk).map_err(|_| bad_signature)?;
            if !crypto::verify(self.signature, self.input.as_bytes(), &key, algorithm)
                .map_err(|_| bad_signature)?
            {
                return Err(bad_signature);
            }
        }
        // Never interpret authorization claims before cryptographic verification.
        let payload = URL_SAFE_NO_PAD.decode(self.payload).map_err(|_| INVALID)?;
        serde_json::from_slice(&payload).map_err(|_| INVALID)
    }
}

fn optional_string(value: Option<&Value>) -> Result<&str, TokenError> {
    match value {
        Some(value) => value.as_str().ok_or(CONFIG),
        None => Ok(""),
    }
}

pub(crate) fn verified_principal(
    claims: &Value,
    settings: &OidcSettings,
) -> Result<VerifiedPrincipal, TokenError> {
    let claims = claims.as_object().ok_or(CONFIG)?;
    if claims.get("iss").and_then(Value::as_str) != Some(settings.issuer.as_str()) {
        return Err(TokenError {
            reason: "invalid_issuer",
        });
    }
    let audience = claims.get("aud");
    let correct_audience = audience.and_then(Value::as_str) == Some(settings.audience.as_str())
        || audience.and_then(Value::as_array).is_some_and(|values| {
            values.iter().all(Value::is_string)
                && values
                    .iter()
                    .any(|value| value.as_str() == Some(settings.audience.as_str()))
        });
    if !correct_audience {
        return Err(TokenError {
            reason: "invalid_audience",
        });
    }

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| CONFIG)?
        .as_secs();
    let exp = claims.get("exp").and_then(Value::as_u64).ok_or(CONFIG)?;
    let iat = claims.get("iat").and_then(Value::as_u64).ok_or(CONFIG)?;
    if exp <= now {
        return Err(TokenError { reason: "expired" });
    }
    if iat > now
        || claims
            .get("nbf")
            .is_some_and(|value| value.as_u64().is_none_or(|n| n > now))
    {
        return Err(TokenError {
            reason: "not_yet_valid",
        });
    }
    let subject = claims
        .get("sub")
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty())
        .ok_or(CONFIG)?;
    let client_id = claims
        .get("client_id")
        .or_else(|| claims.get("azp"))
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty())
        .ok_or(CONFIG)?;
    if claims
        .get("azp")
        .is_some_and(|azp| azp.as_str() != Some(client_id))
    {
        return Err(CONFIG);
    }
    let mut roles = claims
        .get(&settings.roles_claim_path[0])
        .ok_or(TokenError {
            reason: "missing_grant",
        })?;
    for segment in &settings.roles_claim_path[1..] {
        roles = roles.get(segment).ok_or(TokenError {
            reason: "missing_grant",
        })?;
    }
    let mut granted_roles = std::collections::BTreeSet::new();
    match settings.roles_format {
        RolesFormat::List => {
            let items = roles.as_array().ok_or(TokenError {
                reason: "missing_grant",
            })?;
            for item in items {
                let role = item.as_str().ok_or(TokenError {
                    reason: "missing_grant",
                })?;
                granted_roles.insert(role.to_owned());
            }
        }
        RolesFormat::OrganizationGrants => {
            let groups: Vec<&Value> = match roles {
                Value::Array(items) => items.iter().collect(),
                Value::Object(_) => vec![roles],
                _ => vec![],
            };
            for group in groups {
                let entries = group.as_object().ok_or(TokenError {
                    reason: "missing_grant",
                })?;
                for (role, orgs) in entries {
                    let organizations = orgs.as_object().ok_or(TokenError {
                        reason: "missing_grant",
                    })?;
                    if !organizations.values().all(Value::is_string) {
                        return Err(TokenError {
                            reason: "missing_grant",
                        });
                    }
                    if organizations
                        .get(&settings.roles_organization_id)
                        .and_then(Value::as_str)
                        .is_some_and(|value| !value.is_empty())
                    {
                        granted_roles.insert(role.to_owned());
                    }
                }
            }
        }
    }
    if !granted_roles.contains(&settings.required_role) {
        return Err(TokenError {
            reason: "missing_grant",
        });
    }
    let username = optional_string(
        claims
            .get("preferred_username")
            .or_else(|| claims.get("username")),
    )?;
    let username = if username.is_empty() {
        subject
    } else {
        username
    };
    let name = optional_string(claims.get("name"))?;
    let display_name = if name.is_empty() { username } else { name };
    let scope = optional_string(claims.get("scope"))?;
    Ok(VerifiedPrincipal {
        subject: subject.to_owned(),
        username: username.to_owned(),
        display_name: display_name.to_owned(),
        roles: granted_roles.into_iter().collect(),
        client_id: client_id.to_owned(),
        expires_at: exp,
        scopes: scope.split_whitespace().map(str::to_owned).collect(),
    })
}

impl JwtTokenVerifier {
    pub fn new(settings: OidcSettings) -> Result<Self, TokenError> {
        settings.validate_bootstrap()?;
        let client = Client::builder()
            .redirect(Policy::none())
            .connect_timeout(Duration::from_secs(3))
            .timeout(Duration::from_secs(5))
            .pool_max_idle_per_host(4)
            .build()
            .map_err(|_| CONFIG)?;
        Ok(Self {
            settings: Arc::new(settings),
            client,
            cache: Arc::new(RwLock::new(None)),
            refresh_guard: Arc::new(Mutex::new(())),
        })
    }

    async fn json_response<T: serde::de::DeserializeOwned>(
        &self,
        url: &str,
    ) -> Result<T, TokenError> {
        let response = self.client.get(url).send().await.map_err(|_| UNAVAILABLE)?;
        if !response.status().is_success() {
            return Err(UNAVAILABLE);
        }
        let mut bytes = Vec::new();
        let mut chunks = response.bytes_stream();
        while let Some(chunk) = chunks.next().await {
            let chunk = chunk.map_err(|_| UNAVAILABLE)?;
            if bytes.len() + chunk.len() > MAX_PROVIDER_BYTES {
                return Err(UNAVAILABLE);
            }
            bytes.extend_from_slice(&chunk);
        }
        serde_json::from_slice(&bytes).map_err(|_| UNAVAILABLE)
    }

    async fn refresh(&self, forced: bool) -> Result<JwkSet, TokenError> {
        if !forced
            && let Some(cache) = self.cache.read().await.as_ref()
            && cache.expires > Instant::now()
        {
            return Ok(cache.keys.clone());
        }
        let _lock = self.refresh_guard.lock().await;
        if !forced
            && let Some(cache) = self.cache.read().await.as_ref()
            && cache.expires > Instant::now()
        {
            return Ok(cache.keys.clone());
        }
        let metadata_url = format!(
            "{}/.well-known/openid-configuration",
            self.settings.issuer.trim_end_matches('/')
        );
        let metadata: ProviderMetadata = self.json_response(&metadata_url).await?;
        if metadata.issuer != self.settings.issuer {
            return Err(TokenError {
                reason: "invalid_issuer",
            });
        }
        let uri = permitted_url(&metadata.jwks_uri).map_err(|_| UNAVAILABLE)?;
        let keys: JwkSet = self.json_response(uri.as_ref()).await?;
        if keys.keys.is_empty() || keys.keys.len() > 32 {
            return Err(UNAVAILABLE);
        }
        *self.cache.write().await = Some(CachedKeys {
            expires: Instant::now() + CACHE_LIFETIME,
            keys: keys.clone(),
        });
        Ok(keys)
    }

    pub async fn verify(&self, token: &str) -> Result<VerifiedPrincipal, TokenError> {
        let jwt = SignedJwt::parse(token)?;
        if !self.settings.algorithms.contains(&jwt.header.alg) {
            return Err(TokenError {
                reason: "invalid_algorithm",
            });
        }
        let mut keys = self.refresh(false).await?;
        if keys.find(&jwt.header.kid)?.is_none() {
            keys = self.refresh(true).await?;
        }
        let jwk = keys.find(&jwt.header.kid)?.ok_or(TokenError {
            reason: "invalid_signature",
        })?;
        let claims = jwt.verify(jwk)?;
        verified_principal(&claims, &self.settings)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn settings() -> OidcSettings {
        OidcSettings {
            issuer: "http://localhost:9999".into(),
            audience: "project".into(),
            required_role: "tambov".into(),
            roles_claim_path: vec!["roles".into()],
            roles_format: RolesFormat::List,
            roles_organization_id: String::new(),
            algorithms: vec!["RS256".into()],
        }
    }
    #[test]
    fn bootstrap_does_not_accept_insecure_or_symmetric_algorithms() {
        let mut s = settings();
        assert!(JwtTokenVerifier::new(s.clone()).is_ok());
        s.issuer = "http://evil.example".into();
        assert!(JwtTokenVerifier::new(s.clone()).is_err());
        s.issuer = "http://localhost:9999".into();
        s.algorithms = vec!["HS256".into()];
        assert!(JwtTokenVerifier::new(s).is_err());
    }
    #[test]
    fn bootstrap_accepts_the_complete_asymmetric_allowlist() {
        let mut s = settings();
        s.algorithms = ALGORITHMS.iter().map(|name| (*name).to_owned()).collect();
        assert!(JwtTokenVerifier::new(s.clone()).is_ok());
        assert!(
            IntrospectionVerifier::new(s.clone(), "fixture".into(), "fixture-secret".into())
                .is_ok()
        );
        s.algorithms.push("none".into());
        assert!(JwtTokenVerifier::new(s.clone()).is_err());
        assert!(IntrospectionVerifier::new(s, "fixture".into(), "fixture-secret".into()).is_err());
    }

    #[test]
    fn jwt_envelope_rejects_ambiguous_or_unsupported_protected_headers() {
        for header in [
            r#"{"alg":"ES512","alg":"RS256","kid":"fixture"}"#,
            r#"{"alg":"ES512","kid":"fixture","kid":"other"}"#,
            r#"{"alg":"ES512","kid":""}"#,
            r#"{"alg":"ES512","kid":"fixture","crit":["extension"]}"#,
            r#"{"alg":"ES512","kid":"fixture","b64":false}"#,
        ] {
            let token = format!("{}.e30.AA", URL_SAFE_NO_PAD.encode(header));
            assert!(SignedJwt::parse(&token).is_err());
        }
    }

    #[test]
    fn verified_claims_require_exact_issuer_audience_and_timestamps() {
        let s = settings();
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let valid = json!({"iss":s.issuer,"aud":[s.audience,"other"],"sub":"user",
            "client_id":"client","iat":now-1,"exp":now+300,"roles":["tambov"]});
        assert!(verified_principal(&valid, &s).is_ok());
        for name in ["iss", "aud", "sub", "client_id", "iat", "exp", "roles"] {
            let mut malformed = valid.clone();
            malformed.as_object_mut().unwrap().remove(name);
            assert!(verified_principal(&malformed, &s).is_err(), "{name}");
        }
        let mut malformed = valid.clone();
        malformed["aud"] = json!(["project", 1]);
        assert!(verified_principal(&malformed, &s).is_err());
        malformed = valid;
        malformed["exp"] = json!("9999999999");
        assert!(verified_principal(&malformed, &s).is_err());
    }

    #[test]
    fn signed_claims_require_client_and_exact_node_role() {
        let s = settings();
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let allowed = json!({"iss":s.issuer,"aud":s.audience,"sub":"user","client_id":"client", "iat":now-1,"exp":now+300,
            "roles":["tambov"],"scope":"openid offline_access"});
        assert_eq!(verified_principal(&allowed, &s).unwrap().subject, "user");
        let forbidden = json!({"roles":["other"]});
        let mut wrong = allowed.clone();
        wrong["roles"] = forbidden["roles"].clone();
        assert_eq!(
            verified_principal(&wrong, &s).unwrap_err().reason,
            "missing_grant"
        );
        wrong = allowed.clone();
        wrong["azp"] = json!("different-client");
        assert_eq!(
            verified_principal(&wrong, &s).unwrap_err().reason,
            "invalid_claims"
        );
    }
}
