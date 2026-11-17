//! Gateway-owned dynamic Valkey and private HTTP discovery. No caller authorization here.
//! Discovery is never a substitute for JWT issuer/audience/node-role verification.
use std::{
    collections::{BTreeMap, BTreeSet},
    env,
    sync::Arc,
    time::{Duration, Instant},
};

use briareus_service_discovery_rs::{DiscoveryConfig, DiscoveryReader, ServiceIdentity};
use futures_util::{StreamExt, stream};
use reqwest::{Client, redirect::Policy};
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;
use url::Url;

const SNAPSHOT_TTL: Duration = Duration::from_secs(5);
const PROBE_TIMEOUT: Duration = Duration::from_millis(750);

#[derive(Clone, Debug, Serialize)]
pub struct ServiceAvailability {
    #[serde(flatten)]
    pub identity: ServiceIdentity,
    pub mcp_path: String,
    pub connected: bool,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProbeHealth {
    service: ServiceIdentity,
    environment: String,
    ready: bool,
}

struct CachedSnapshot {
    valid_until: Instant,
    services: Vec<ServiceAvailability>,
}

#[derive(Clone)]
pub struct GatewayDirectory {
    known: Arc<Vec<ServiceIdentity>>,
    reader: Option<DiscoveryReader>,
    environment: String,
    http: Client,
    targets: Arc<BTreeMap<String, Url>>,
    // A short-lived snapshot avoids per-request Valkey traffic and matches Python's TTL.
    snapshot: Arc<Mutex<Option<CachedSnapshot>>>,
}

impl GatewayDirectory {
    pub fn from_env(known: Vec<ServiceIdentity>) -> anyhow::Result<Self> {
        let environment = env::var("DEPLOYMENT_ENVIRONMENT").unwrap_or_else(|_| "test".into());
        let valkey_password = env::var("VALKEY_PASSWORD").unwrap_or_default();
        let reader = if valkey_password.is_empty() {
            None // Local loopback-only shadow; no claims of live membership.
        } else {
            Some(DiscoveryReader::new(&DiscoveryConfig {
                enabled: true,
                valkey_url: env::var("VALKEY_URL")
                    .unwrap_or_else(|_| "redis://valkey:6379/0".into()),
                username: env::var("VALKEY_USERNAME").unwrap_or_else(|_| "default".into()),
                password: valkey_password,
                namespace: env::var("VALKEY_NAMESPACE").unwrap_or_else(|_| "briareus:v1".into()),
                environment: environment.clone(),
            })?)
        };
        let http = Client::builder()
            .no_proxy()
            .redirect(Policy::none())
            .connect_timeout(PROBE_TIMEOUT)
            .timeout(PROBE_TIMEOUT)
            .pool_max_idle_per_host(8)
            .build()?;
        let mut targets = BTreeMap::new();
        if let Ok(value) = env::var("GATEWAY_SHADOW_TARGETS_JSON") {
            let supplied: BTreeMap<String, String> = serde_json::from_str(&value)?;
            anyhow::ensure!(supplied.len() <= 25, "Too many shadow service targets");
            for (key, value) in supplied {
                ServiceIdentity::new(&key, "Fixture", "svc")?;
                let url = Url::parse(&value)?;
                anyhow::ensure!(
                    url.scheme() == "http"
                        && matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"))
                        && url.path() == "/"
                        && url.query().is_none()
                        && url.fragment().is_none()
                        && url.username().is_empty()
                        && url.password().is_none(),
                    "Shadow service targets must be local HTTP origins"
                );
                targets.insert(key, url);
            }
        }
        Ok(Self {
            known: Arc::new(known),
            reader,
            environment,
            http,
            targets: Arc::new(targets),
            snapshot: Arc::new(Mutex::new(None)),
        })
    }

    async fn probe(&self, identity: &ServiceIdentity) -> bool {
        let url = self.targets.get(&identity.id).cloned().unwrap_or_else(|| {
            Url::parse(&identity.internal_origin()).expect("trusted service origin")
        });
        let Ok(path) = url.join("health/discovery") else {
            return false;
        };
        let Ok(reply) = self.http.get(path).send().await else {
            return false;
        };
        if !reply.status().is_success() || reply.content_length().is_some_and(|bytes| bytes > 4096)
        {
            return false;
        }
        // Response is an authenticated **private network** readiness signal,
        // never a replacement for public bearer authorization.
        let Ok(body) = reply.bytes().await else {
            return false;
        };
        if body.len() > 4096 {
            return false;
        }
        let Ok(health) = serde_json::from_slice::<ProbeHealth>(&body) else {
            return false;
        };
        health.ready && health.environment == self.environment && health.service == *identity
    }

    pub async fn snapshot(&self) -> Vec<ServiceAvailability> {
        let mut cache = self.snapshot.lock().await;
        if let Some(snapshot) = cache.as_ref()
            && snapshot.valid_until > Instant::now()
        {
            return snapshot.services.clone();
        }
        let mut candidates = BTreeMap::<String, ServiceIdentity>::new();
        for service in self.known.iter() {
            candidates.insert(service.id.clone(), service.clone());
        }
        let active: BTreeSet<String> = if let Some(reader) = &self.reader {
            let (registered, inventory) =
                tokio::join!(reader.active_services(), reader.inventory());
            if let (Ok(active), Ok(inventory)) = (registered, inventory) {
                for service in inventory {
                    candidates.insert(service.id.clone(), service);
                }
                active
            } else {
                BTreeSet::new() // No stale availability on Valkey failure.
            }
        } else {
            BTreeSet::new()
        };
        // Small V1 catalog: probe only explicitly leased candidates, with bounded total.
        let services: Vec<ServiceAvailability> = stream::iter(candidates.into_values().take(1024))
            .map(|identity| async {
                let connected = active.contains(&identity.id) && self.probe(&identity).await;
                ServiceAvailability {
                    mcp_path: identity.mcp_path(),
                    identity,
                    connected,
                }
            })
            .buffer_unordered(12)
            .collect()
            .await;
        *cache = Some(CachedSnapshot {
            valid_until: Instant::now() + SNAPSHOT_TTL,
            services: services.clone(),
        });
        services
    }

    pub fn backend_mcp_url(&self, identity: &ServiceIdentity) -> String {
        let origin = self.targets.get(&identity.id).cloned().unwrap_or_else(|| {
            Url::parse(&identity.internal_origin()).expect("validated identity")
        });
        origin.join("mcp").expect("validated origin").to_string()
    }

    pub fn discovery_configured(&self) -> bool {
        self.reader.is_some()
    }

    pub async fn lookup(&self, path: &str) -> Option<ServiceAvailability> {
        self.snapshot()
            .await
            .into_iter()
            .find(|service| service.mcp_path == path)
    }
}
