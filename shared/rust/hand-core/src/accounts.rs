//! Account/credential boundary shared by future Rust Hands.
//! The Panel is the sole credential owner. No database access or local credential store.
use std::future::Future;

use reqwest::Method;
use serde::Deserialize;
use serde_json::{Value, json};

use crate::{HandError, JsonHttp};

#[derive(Deserialize)]
pub struct ResolvedAccount {
    pub id: String,
    pub alias: String,
    pub provider: String,
    pub auth_type: String,
    pub base_url: String,
    pub credential: String,
    #[serde(default = "enabled")]
    pub enabled: bool,
    #[serde(default = "enabled")]
    pub verify_tls: bool,
    pub ca_cert_pem: Option<String>,
    #[serde(default)]
    pub updated_at: String,
    #[serde(default)]
    pub created_at: String,
    pub external_id: Option<String>,
}

fn enabled() -> bool { true }

impl ResolvedAccount {
    /// Safe projection matching Python's AccountPublic fields.
    pub fn public(&self) -> Value {
        json!({
            "id": self.id,
            "alias": self.alias,
            "provider": self.provider,
            "auth_type": self.auth_type,
            "base_url": self.base_url,
            "external_id": self.external_id,
            "verify_tls": self.verify_tls,
            "ca_cert_pem": self.ca_cert_pem,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
    }
}

/// Future provider Hands can implement a fake directory for contract tests.
pub trait AccountDirectory: Send + Sync {
    fn provider(&self) -> &str;
    fn sources(&self) -> impl Future<Output = Result<Value, HandError>> + Send;
    fn resolve(&self, selector: &str) -> impl Future<Output = Result<ResolvedAccount, HandError>> + Send;
}

#[derive(Clone)]
pub struct PanelAccountDirectory {
    http: JsonHttp,
    provider: String,
}

impl PanelAccountDirectory {
    pub fn new(
        url: &str,
        service_token: &str,
        provider: &str,
    ) -> Result<Self, HandError> {
        if service_token.trim().is_empty() {
            return Err(HandError::MissingToken);
        }
        Ok(Self {
            http: JsonHttp::new(url, "Authorization",
                &format!("Bearer {service_token}"), true, None)?,
            provider: provider.into(),
        })
    }

    fn filter_public(data: Value, provider: &str) -> Result<Value, HandError> {
        let object = data.as_object().ok_or(HandError::InvalidResponse)?;
        let accounts = object.get("accounts").and_then(Value::as_array)
            .ok_or(HandError::InvalidResponse)?;
        let mut safe_accounts = Vec::new();
        for raw in accounts {
            let raw = raw.as_object().ok_or(HandError::InvalidResponse)?;
            if raw.get("provider").and_then(Value::as_str) != Some(provider) {
                return Err(HandError::InvalidResponse);
            }
            let mut safe = serde_json::Map::new();
            for key in [
                "id", "alias", "provider", "auth_type", "base_url", "external_id",
                "verify_tls", "ca_cert_pem", "enabled", "created_at", "updated_at",
            ] {
                if let Some(value) = raw.get(key) {
                    safe.insert(key.into(), value.clone());
                }
            }
            safe_accounts.push(Value::Object(safe));
        }
        Ok(json!({"sources":safe_accounts,"count":safe_accounts.len()}))
    }
}

impl AccountDirectory for PanelAccountDirectory {
    fn provider(&self) -> &str { &self.provider }

    async fn sources(&self) -> Result<Value, HandError> {
        let data = self.http.json(
            Method::GET, &["internal","accounts"], &[("provider", &self.provider)], None,
        ).await?;
        Self::filter_public(data, &self.provider)
    }

    async fn resolve(&self, selector: &str) -> Result<ResolvedAccount, HandError> {
        if selector.is_empty() || selector.len() > 256 { return Err(HandError::Invalid("account_id is required (max 256 characters)".into())); }
        let data = self.http.json(
            Method::GET, &["internal","accounts",selector,"resolve"], &[("provider",&self.provider)], None,
        ).await?;
        let account: ResolvedAccount =
            serde_json::from_value(data).map_err(|_| HandError::InvalidResponse)?;
        if !account.enabled || account.provider != self.provider || account.credential.is_empty() {
            return Err(HandError::AccountUnavailable);
        }
        Ok(account)
    }
}

#[cfg(test)]
mod tests {
    use super::PanelAccountDirectory;
    use serde_json::json;

    #[test]
    fn filtered_sources_never_expose_provider_credentials() {
        let payload = json!({
            "accounts":[{"id":"a", "alias":"test","provider":"signoz",
                "credential":"must-not-leak", "unknown_secret":"must-not-leak"}],
            "count":1
        });
        let safe = PanelAccountDirectory::filter_public(payload, "signoz").unwrap();
        assert_eq!(safe["count"], 1);
        assert!(!safe.to_string().contains("must-not-leak"));
    }
}
