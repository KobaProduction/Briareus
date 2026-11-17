//! Opt-in V1 Valkey lease registration. No provider credentials or user grants.
//! Exact key/TTL and service descriptor contract matches the Python registry.
use std::{sync::Arc, time::Duration};

use serde_json::json;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
    sync::watch,
    time::{sleep, timeout},
};
use url::Url;

use crate::HandError;

const IO_TIMEOUT: Duration = Duration::from_secs(1);
const RENEW_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Clone)]
pub struct DiscoveryConfig {
    pub enabled: bool,
    pub valkey_url: String,
    pub username: String,
    pub password: String,
    pub namespace: String,
    pub environment: String,
}

#[derive(Clone)]
pub struct DiscoveryRegistry {
    host: String,
    port: u16,
    username: String,
    password: String,
    inventory_key: String,
    lease_key: String,
    inventory: String,
}

impl DiscoveryRegistry {
    pub fn new(config: DiscoveryConfig, instance_id: &str) -> Result<Option<Self>, HandError> {
        if !config.enabled {
            return Ok(None);
        }
        let url = Url::parse(&config.valkey_url).map_err(|_| HandError::Configuration)?;
        if url.scheme() != "redis"
            || url.username() != ""
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || url.host_str().is_none()
            || url.path() != "/0"
            || config.password.is_empty()
            || config.username.is_empty()
            || config.username.len() > 64
            || !config
                .username
                .bytes()
                .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, b'-' | b'_'))
            || config.namespace.is_empty()
            || config.namespace.len() > 64
            || !config
                .namespace
                .bytes()
                .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, b'-' | b'_' | b':'))
            || config.environment.is_empty()
            || config.environment.len() > 63
            || !config
                .environment
                .bytes()
                .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, b'-' | b'_'))
            || instance_id.len() != 32
            || !instance_id.bytes().all(|ch| ch.is_ascii_hexdigit())
        {
            return Err(HandError::Configuration);
        }
        let prefix = format!("{}:services:{}:", config.namespace, config.environment);
        Ok(Some(Self {
            host: url.host_str().unwrap().to_owned(),
            port: url.port().unwrap_or(6379),
            username: config.username,
            password: config.password,
            inventory_key: format!("{prefix}inventory:signoz"),
            lease_key: format!("{prefix}lease:signoz:{instance_id}"),
            inventory: json!({"id":"signoz","name":"SigNoz","group":"observability"}).to_string(),
        }))
    }

    async fn command(stream: &mut TcpStream, arguments: &[&str]) -> Result<(), HandError> {
        let mut payload = format!("*{}\r\n", arguments.len()).into_bytes();
        for arg in arguments {
            payload.extend_from_slice(format!("${}\r\n", arg.len()).as_bytes());
            payload.extend_from_slice(arg.as_bytes());
            payload.extend_from_slice(b"\r\n");
        }
        // Never include a Valkey response or credentials in an error.
        timeout(IO_TIMEOUT, stream.write_all(&payload))
            .await
            .map_err(|_| HandError::Transport)?
            .map_err(|_| HandError::Transport)?;
        let mut marker = [0u8; 1];
        timeout(IO_TIMEOUT, stream.read_exact(&mut marker))
            .await
            .map_err(|_| HandError::Transport)?
            .map_err(|_| HandError::Transport)?;
        let success = match marker[0] {
            b'+' => {
                let mut value = [0u8; 4];
                timeout(IO_TIMEOUT, stream.read_exact(&mut value))
                    .await
                    .map_err(|_| HandError::Transport)?
                    .map_err(|_| HandError::Transport)?;
                &value == b"OK\r\n"
            }
            b':' => {
                let mut value = [0u8; 3];
                timeout(IO_TIMEOUT, stream.read_exact(&mut value))
                    .await
                    .map_err(|_| HandError::Transport)?
                    .map_err(|_| HandError::Transport)?;
                &value == b"1\r\n" || &value == b"0\r\n"
            }
            _ => false,
        };
        if success {
            Ok(())
        } else {
            Err(HandError::Transport)
        }
    }

    async fn connected(&self) -> Result<TcpStream, HandError> {
        let mut stream = timeout(
            IO_TIMEOUT,
            TcpStream::connect((self.host.as_str(), self.port)),
        )
        .await
        .map_err(|_| HandError::Transport)?
        .map_err(|_| HandError::Transport)?;
        Self::command(&mut stream, &["AUTH", &self.username, &self.password]).await?;
        Ok(stream)
    }

    pub async fn announce(&self) -> Result<(), HandError> {
        let mut stream = self.connected().await?;
        Self::command(&mut stream, &["SET", &self.inventory_key, &self.inventory]).await?;
        Self::command(&mut stream, &["SET", &self.lease_key, "1", "EX", "20"]).await?;
        Ok(())
    }

    pub async fn withdraw(&self) -> Result<(), HandError> {
        let mut stream = self.connected().await?;
        Self::command(&mut stream, &["DEL", &self.lease_key]).await
    }

    pub fn launch(self: Arc<Self>, mut stop: watch::Receiver<bool>) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            loop {
                if self.announce().await.is_err() {
                    // A missing lease makes Gateway refuse the service, not bypass auth.
                    eprintln!("Rust SigNoz discovery lease update failed");
                }
                tokio::select! {
                    () = sleep(RENEW_INTERVAL) => {},
                    changed = stop.changed() => {
                        if changed.is_err() || *stop.borrow() { break; }
                    },
                }
            }
            if self.withdraw().await.is_err() {
                eprintln!("Rust SigNoz discovery lease withdraw failed");
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn disabled_skips_valkey_and_rejects_unsafe_config() {
        let config = DiscoveryConfig {
            enabled: false,
            valkey_url: "".into(),
            username: "".into(),
            password: "".into(),
            namespace: "".into(),
            environment: "".into(),
        };
        assert!(
            DiscoveryRegistry::new(config.clone(), "not-instance")
                .unwrap()
                .is_none()
        );
        let mut enabled = config;
        enabled.enabled = true;
        enabled.valkey_url = "redis://user:pass@valkey:6379/0".into();
        enabled.username = "default".into();
        enabled.password = "secret".into();
        enabled.namespace = "briareus:v1".into();
        enabled.environment = "production".into();
        assert!(DiscoveryRegistry::new(enabled, "a".repeat(32).as_str()).is_err());
    }
}
