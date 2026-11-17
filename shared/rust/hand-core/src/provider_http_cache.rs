//! Bounded process-local HTTP client reuse across Rust Hands.
//!
//! Account authority stays in Control Panel: callers MUST resolve and validate
//! the account for every operation before consulting this cache. No disk or
//! Valkey persistence is added; a changed account revision, credential, TLS
//! policy or endpoint never reuses the prior connection pool.
use std::{
    collections::VecDeque,
    sync::{Arc, Mutex},
};

use crate::{HandError, JsonHttp, ResolvedAccount};

struct ClientEntry {
    account: ResolvedAccount,
    auth_header: String,
    client: Arc<JsonHttp>,
}

impl ClientEntry {
    fn matches(&self, account: &ResolvedAccount, auth_header: &str) -> bool {
        self.account.provider == account.provider
            && self.account.id == account.id
            && self.auth_header == auth_header
            && self.account.updated_at == account.updated_at
            && self.account.auth_type == account.auth_type
            && self.account.base_url == account.base_url
            && self.account.credential == account.credential
            && self.account.verify_tls == account.verify_tls
            && self.account.ca_cert_pem == account.ca_cert_pem
    }

    fn same_key(&self, account: &ResolvedAccount, auth_header: &str) -> bool {
        self.account.provider == account.provider
            && self.account.id == account.id
            && self.auth_header == auth_header
    }
}

/// Reuses authenticated reqwest connection pools after independent account
/// resolution; credentials never appear in diagnostics or output projections.
///
/// This cache intentionally does NOT store authorization decisions: the
/// current account must be resolved before each call. Cache capacity is
/// configurable; zero disables it for strict per-call testing.
pub struct ProviderHttpCache {
    capacity: usize,
    entries: Mutex<VecDeque<ClientEntry>>,
}

impl ProviderHttpCache {
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity,
            entries: Mutex::new(VecDeque::new()),
        }
    }

    pub fn get_or_create(
        &self,
        account: &ResolvedAccount,
        auth_header: &str,
    ) -> Result<Arc<JsonHttp>, HandError> {
        // Do not pool connections for untrusted, disabled or empty-credential
        // records, even if an earlier version of the account was valid.
        if !account.enabled || account.credential.is_empty() {
            return Err(HandError::AccountUnavailable);
        }
        if self.capacity == 0 {
            return Ok(Arc::new(Self::new_http(account, auth_header)?));
        }
        let mut entries = self.entries.lock().map_err(|_| HandError::Configuration)?;
        if let Some(index) = entries
            .iter()
            .position(|entry| entry.same_key(account, auth_header))
        {
            let entry = entries.remove(index).ok_or(HandError::Configuration)?;
            if entry.matches(account, auth_header) {
                let client = Arc::clone(&entry.client);
                entries.push_back(entry);
                return Ok(client);
            }
            // Rotation invalidates the old connection pool before building a new one.
        }
        let client = Arc::new(Self::new_http(account, auth_header)?);
        if entries.len() >= self.capacity {
            entries.pop_front();
        }
        entries.push_back(ClientEntry {
            account: account.clone(),
            auth_header: auth_header.to_owned(),
            client: Arc::clone(&client),
        });
        Ok(client)
    }

    fn new_http(account: &ResolvedAccount, auth_header: &str) -> Result<JsonHttp, HandError> {
        JsonHttp::new(
            &account.base_url,
            auth_header,
            &account.credential,
            account.verify_tls,
            account.ca_cert_pem.as_deref(),
        )
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::ProviderHttpCache;
    use crate::ResolvedAccount;

    fn account(id: &str) -> ResolvedAccount {
        ResolvedAccount {
            id: id.into(),
            alias: id.into(),
            provider: "signoz".into(),
            auth_type: "signoz_api_key".into(),
            base_url: "http://127.0.0.1:5656".into(),
            credential: "synthetic-first-key".into(),
            enabled: true,
            verify_tls: true,
            ca_cert_pem: None,
            updated_at: "rev-1".into(),
            created_at: "created".into(),
            external_id: None,
        }
    }

    #[test]
    fn repeated_account_reuses_pool_without_caching_authorization() {
        let cache = ProviderHttpCache::new(3);
        let source = account("a");
        let first = cache.get_or_create(&source, "SIGNOZ-API-KEY").unwrap();
        let second = cache.get_or_create(&source, "SIGNOZ-API-KEY").unwrap();
        assert!(Arc::ptr_eq(&first, &second));

        let mut disabled = account("a");
        disabled.enabled = false;
        assert!(cache.get_or_create(&disabled, "SIGNOZ-API-KEY").is_err());

        let mut missing_key = account("a");
        missing_key.credential.clear();
        assert!(cache.get_or_create(&missing_key, "SIGNOZ-API-KEY").is_err());
    }

    #[test]
    fn revision_endpoint_tls_and_secret_rotation_invalidate_pool() {
        let cache = ProviderHttpCache::new(2);
        let mut source = account("a");
        let mut last = cache.get_or_create(&source, "SIGNOZ-API-KEY").unwrap();
        for change in 0..6 {
            match change {
                0 => source.credential = "synthetic-rotated-key".into(),
                1 => source.updated_at = "rev-2".into(),
                2 => source.base_url = "https://example.test".into(),
                3 => source.verify_tls = false,
                4 => source.ca_cert_pem = Some(String::new()),
                _ => source.auth_type = "changed-auth-type".into(),
            }
            let next = cache.get_or_create(&source, "SIGNOZ-API-KEY").unwrap();
            assert!(!Arc::ptr_eq(&last, &next));
            last = next;
        }
        let changed_header = cache.get_or_create(&source, "Authorization").unwrap();
        assert!(!Arc::ptr_eq(&last, &changed_header));
    }

    #[test]
    fn capacity_and_provider_scope_are_bounded() {
        let cache = ProviderHttpCache::new(2);
        let a = account("a");
        let old_a = cache.get_or_create(&a, "SIGNOZ-API-KEY").unwrap();
        cache
            .get_or_create(&account("b"), "SIGNOZ-API-KEY")
            .unwrap();
        cache
            .get_or_create(&account("c"), "SIGNOZ-API-KEY")
            .unwrap();
        let new_a = cache.get_or_create(&a, "SIGNOZ-API-KEY").unwrap();
        assert!(!Arc::ptr_eq(&old_a, &new_a));

        let mut wrong_provider = account("a");
        wrong_provider.provider = "github".into();
        let foreign = cache
            .get_or_create(&wrong_provider, "SIGNOZ-API-KEY")
            .unwrap();
        assert!(!Arc::ptr_eq(&new_a, &foreign));

        let no_cache = ProviderHttpCache::new(0);
        let first = no_cache.get_or_create(&a, "SIGNOZ-API-KEY").unwrap();
        let second = no_cache.get_or_create(&a, "SIGNOZ-API-KEY").unwrap();
        assert!(!Arc::ptr_eq(&first, &second));
    }
}
