//! Shared V1 Valkey inventory and short-lived instance registration for Rust Hands.
//! No provider-specific service identity or user grant authority.
use std::{sync::Arc, time::Duration};

use serde::{Deserialize, Serialize};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
    sync::watch,
    time::{sleep, timeout},
};
use url::Url;

#[derive(Debug, thiserror::Error)]
pub enum DiscoveryError {
    #[error("Invalid service discovery configuration")]
    Configuration,
    #[error("Service discovery transport unavailable")]
    Transport,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ServiceIdentity {
    pub id: String,
    pub name: String,
    pub group: String,
}

impl ServiceIdentity {
    pub fn new(id: &str, name: &str, group: &str) -> Result<Self, DiscoveryError> {
        let valid_slug = |slug: &str, max: usize| {
            !slug.is_empty()
                && slug.len() <= max
                && slug.as_bytes()[0].is_ascii_lowercase()
                && slug
                    .bytes()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
        };
        if !valid_slug(id, 54)
            || !valid_slug(group, 63)
            || matches!(group, "api" | "admin" | "health")
            || name.trim().is_empty()
            || name.len() > 80
        {
            return Err(DiscoveryError::Configuration);
        }
        Ok(Self {
            id: id.to_owned(),
            name: name.to_owned(),
            group: group.to_owned(),
        })
    }

    pub fn mcp_path(&self) -> String {
        if self.id == self.group {
            format!("/{}/mcp", self.group)
        } else {
            format!("/{}/{}/mcp", self.group, self.id)
        }
    }

    pub fn internal_origin(&self) -> String {
        format!("http://{}-mcp-hand:8000", self.id)
    }
}

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
    pub fn new(
        config: DiscoveryConfig,
        service: &ServiceIdentity,
        instance_id: &str,
    ) -> Result<Option<Self>, DiscoveryError> {
        if !config.enabled {
            return Ok(None);
        }
        let url = Url::parse(&config.valkey_url).map_err(|_| DiscoveryError::Configuration)?;
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
            return Err(DiscoveryError::Configuration);
        }
        let prefix = format!("{}:services:{}:", config.namespace, config.environment);
        Ok(Some(Self {
            host: url.host_str().unwrap().to_owned(),
            port: url.port().unwrap_or(6379),
            username: config.username,
            password: config.password,
            inventory_key: format!("{prefix}inventory:{}", service.id),
            lease_key: format!("{prefix}lease:{}:{instance_id}", service.id),
            inventory: serde_json::to_string(service).map_err(|_| DiscoveryError::Configuration)?,
        }))
    }

    async fn command(stream: &mut TcpStream, arguments: &[&str]) -> Result<(), DiscoveryError> {
        let mut payload = format!("*{}\r\n", arguments.len()).into_bytes();
        for arg in arguments {
            payload.extend_from_slice(format!("${}\r\n", arg.len()).as_bytes());
            payload.extend_from_slice(arg.as_bytes());
            payload.extend_from_slice(b"\r\n");
        }
        // Never include a Valkey response or credentials in an error.
        timeout(IO_TIMEOUT, stream.write_all(&payload))
            .await
            .map_err(|_| DiscoveryError::Transport)?
            .map_err(|_| DiscoveryError::Transport)?;
        let mut marker = [0u8; 1];
        timeout(IO_TIMEOUT, stream.read_exact(&mut marker))
            .await
            .map_err(|_| DiscoveryError::Transport)?
            .map_err(|_| DiscoveryError::Transport)?;
        let success = match marker[0] {
            b'+' => {
                let mut value = [0u8; 4];
                timeout(IO_TIMEOUT, stream.read_exact(&mut value))
                    .await
                    .map_err(|_| DiscoveryError::Transport)?
                    .map_err(|_| DiscoveryError::Transport)?;
                &value == b"OK\r\n"
            }
            b':' => {
                let mut value = [0u8; 3];
                timeout(IO_TIMEOUT, stream.read_exact(&mut value))
                    .await
                    .map_err(|_| DiscoveryError::Transport)?
                    .map_err(|_| DiscoveryError::Transport)?;
                &value == b"1\r\n" || &value == b"0\r\n"
            }
            _ => false,
        };
        if success {
            Ok(())
        } else {
            Err(DiscoveryError::Transport)
        }
    }

    async fn connected(&self) -> Result<TcpStream, DiscoveryError> {
        let mut stream = timeout(
            IO_TIMEOUT,
            TcpStream::connect((self.host.as_str(), self.port)),
        )
        .await
        .map_err(|_| DiscoveryError::Transport)?
        .map_err(|_| DiscoveryError::Transport)?;
        Self::command(&mut stream, &["AUTH", &self.username, &self.password]).await?;
        Ok(stream)
    }

    pub async fn announce(&self) -> Result<(), DiscoveryError> {
        let mut stream = self.connected().await?;
        Self::command(&mut stream, &["SET", &self.inventory_key, &self.inventory]).await?;
        Self::command(&mut stream, &["SET", &self.lease_key, "1", "EX", "20"]).await?;
        Ok(())
    }

    pub async fn withdraw(&self) -> Result<(), DiscoveryError> {
        let mut stream = self.connected().await?;
        Self::command(&mut stream, &["DEL", &self.lease_key]).await
    }

    pub fn launch(self: Arc<Self>, mut stop: watch::Receiver<bool>) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            loop {
                if self.announce().await.is_err() {
                    // A missing lease makes Gateway refuse the service, not bypass auth.
                    eprintln!("Rust service discovery lease update failed");
                }
                tokio::select! {
                    () = sleep(RENEW_INTERVAL) => {},
                    changed = stop.changed() => {
                        if changed.is_err() || *stop.borrow() { break; }
                    },
                }
            }
            if self.withdraw().await.is_err() {
                eprintln!("Rust service discovery lease withdraw failed");
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn identity_is_provider_generic_and_fail_closed() {
        let github = ServiceIdentity::new("github", "GitHub", "svc").unwrap();
        assert_eq!(github.id, "github");
        assert_eq!(github.mcp_path(), "/svc/github/mcp");
        assert_eq!(
            ServiceIdentity::new("server", "Server", "server")
                .unwrap()
                .mcp_path(),
            "/server/mcp"
        );
        assert_eq!(github.internal_origin(), "http://github-mcp-hand:8000");
        assert!(ServiceIdentity::new("GITHUB", "GitHub", "svc").is_err());
        assert!(ServiceIdentity::new("github", "GitHub", "admin").is_err());
        assert!(ServiceIdentity::new("github", "", "svc").is_err());
    }

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
            DiscoveryRegistry::new(
                config.clone(),
                &ServiceIdentity::new("github", "GitHub", "svc").unwrap(),
                "not-instance",
            )
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
        assert!(
            DiscoveryRegistry::new(
                enabled,
                &ServiceIdentity::new("github", "GitHub", "svc").unwrap(),
                "a".repeat(32).as_str()
            )
            .is_err()
        );
    }
}

/// Read-only discovery snapshot client used by the Gateway. It owns no leases.
/// SCAN is bounded and results require an independent HTTP /health/discovery probe.
#[derive(Clone)]
pub struct DiscoveryReader {
    host: String,
    port: u16,
    username: String,
    password: String,
    prefix: String,
}

impl DiscoveryReader {
    pub fn new(config: &DiscoveryConfig) -> Result<Self, DiscoveryError> {
        let url = Url::parse(&config.valkey_url).map_err(|_| DiscoveryError::Configuration)?;
        if url.scheme() != "redis"
            || url.username() != ""
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || url.host_str().is_none()
            || url.path() != "/0"
            || config.password.is_empty()
            || config.username.is_empty()
            || config.namespace.is_empty()
            || config.environment.is_empty()
            || !config
                .namespace
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, b':' | b'-' | b'_'))
            || !config
                .environment
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_'))
        {
            return Err(DiscoveryError::Configuration);
        }
        Ok(Self {
            host: url.host_str().unwrap().to_owned(),
            port: url.port().unwrap_or(6379),
            username: config.username.clone(),
            password: config.password.clone(),
            prefix: format!("{}:services:{}:", config.namespace, config.environment),
        })
    }

    async fn connect(&self) -> Result<tokio::io::BufReader<TcpStream>, DiscoveryError> {
        let stream = timeout(
            IO_TIMEOUT,
            TcpStream::connect((self.host.as_str(), self.port)),
        )
        .await
        .map_err(|_| DiscoveryError::Transport)?
        .map_err(|_| DiscoveryError::Transport)?;
        let mut stream = tokio::io::BufReader::new(stream);
        self.send(&mut stream, &["AUTH", &self.username, &self.password])
            .await?;
        let answer = Self::line(&mut stream).await?;
        if answer != b"+OK" {
            return Err(DiscoveryError::Transport);
        }
        Ok(stream)
    }

    async fn send(
        &self,
        stream: &mut tokio::io::BufReader<TcpStream>,
        arguments: &[&str],
    ) -> Result<(), DiscoveryError> {
        let mut data = format!("*{}\r\n", arguments.len()).into_bytes();
        for arg in arguments {
            if arg.len() > 1024 {
                return Err(DiscoveryError::Configuration);
            }
            data.extend_from_slice(format!("${}\r\n", arg.len()).as_bytes());
            data.extend_from_slice(arg.as_bytes());
            data.extend_from_slice(b"\r\n");
        }
        timeout(IO_TIMEOUT, stream.get_mut().write_all(&data))
            .await
            .map_err(|_| DiscoveryError::Transport)?
            .map_err(|_| DiscoveryError::Transport)
    }

    async fn line(stream: &mut tokio::io::BufReader<TcpStream>) -> Result<Vec<u8>, DiscoveryError> {
        let mut line = Vec::with_capacity(32);
        for _ in 0..512 {
            let mut one = [0u8];
            timeout(IO_TIMEOUT, stream.read_exact(&mut one))
                .await
                .map_err(|_| DiscoveryError::Transport)?
                .map_err(|_| DiscoveryError::Transport)?;
            line.push(one[0]);
            if line.ends_with(b"\r\n") {
                line.truncate(line.len() - 2);
                return Ok(line);
            }
        }
        Err(DiscoveryError::Transport)
    }

    async fn bulk(
        stream: &mut tokio::io::BufReader<TcpStream>,
    ) -> Result<Option<String>, DiscoveryError> {
        let length = Self::line(stream).await?;
        if length == b"$-1" {
            return Ok(None);
        }
        let size = std::str::from_utf8(length.strip_prefix(b"$").ok_or(DiscoveryError::Transport)?)
            .ok()
            .and_then(|n| n.parse::<usize>().ok())
            .filter(|n| *n <= 8192)
            .ok_or(DiscoveryError::Transport)?;
        let mut bytes = vec![0; size + 2];
        timeout(IO_TIMEOUT, stream.read_exact(&mut bytes))
            .await
            .map_err(|_| DiscoveryError::Transport)?
            .map_err(|_| DiscoveryError::Transport)?;
        if !bytes.ends_with(b"\r\n") {
            return Err(DiscoveryError::Transport);
        }
        bytes.truncate(size);
        String::from_utf8(bytes)
            .map(Some)
            .map_err(|_| DiscoveryError::Transport)
    }

    /// Redis SCAN in bounded pages; a partial snapshot fails closed rather than
    /// silently claiming a provider is absent or allowing stale access.
    async fn scan(&self, pattern: &str, limit: usize) -> Result<Vec<String>, DiscoveryError> {
        let mut stream = self.connect().await?;
        let mut cursor = "0".to_owned();
        let mut keys = std::collections::BTreeSet::new();
        for _ in 0..128 {
            self.send(
                &mut stream,
                &["SCAN", &cursor, "MATCH", pattern, "COUNT", "100"],
            )
            .await?;
            if Self::line(&mut stream).await? != b"*2" {
                return Err(DiscoveryError::Transport);
            }
            let next = Self::bulk(&mut stream)
                .await?
                .ok_or(DiscoveryError::Transport)?;
            if next.len() > 24 || !next.bytes().all(|c| c.is_ascii_digit()) {
                return Err(DiscoveryError::Transport);
            }
            let count = Self::line(&mut stream).await?;
            let count =
                std::str::from_utf8(count.strip_prefix(b"*").ok_or(DiscoveryError::Transport)?)
                    .ok()
                    .and_then(|n| n.parse::<usize>().ok())
                    .filter(|n| *n <= 1024)
                    .ok_or(DiscoveryError::Transport)?;
            for _ in 0..count {
                let key = Self::bulk(&mut stream)
                    .await?
                    .ok_or(DiscoveryError::Transport)?;
                if !key.starts_with(&self.prefix) {
                    return Err(DiscoveryError::Transport);
                }
                keys.insert(key);
                if keys.len() > limit {
                    return Err(DiscoveryError::Transport);
                }
            }
            if next == "0" {
                return Ok(keys.into_iter().collect());
            }
            cursor = next;
        }
        Err(DiscoveryError::Transport)
    }

    pub async fn active_services(
        &self,
    ) -> Result<std::collections::BTreeSet<String>, DiscoveryError> {
        let prefix = format!("{}lease:", self.prefix);
        let keys = self.scan(&(prefix.clone() + "*"), 3000).await?;
        let mut ids = std::collections::BTreeSet::new();
        for key in keys {
            let Some((id, instance)) = key
                .strip_prefix(&prefix)
                .and_then(|value| value.split_once(':'))
            else {
                return Err(DiscoveryError::Transport);
            };
            if !instance.is_empty() && ServiceIdentity::new(id, "candidate", "svc").is_ok() {
                ids.insert(id.to_owned());
            }
        }
        Ok(ids)
    }

    pub async fn inventory(&self) -> Result<Vec<ServiceIdentity>, DiscoveryError> {
        let prefix = format!("{}inventory:", self.prefix);
        let keys = self.scan(&(prefix.clone() + "*"), 1000).await?;
        let mut stream = self.connect().await?;
        let mut services = Vec::new();
        for key in keys {
            self.send(&mut stream, &["GET", &key]).await?;
            let Some(payload) = Self::bulk(&mut stream).await? else {
                continue;
            };
            let identity: ServiceIdentity =
                serde_json::from_str(&payload).map_err(|_| DiscoveryError::Transport)?;
            let checked = ServiceIdentity::new(&identity.id, &identity.name, &identity.group)?;
            if key != prefix.clone() + &checked.id {
                return Err(DiscoveryError::Transport);
            }
            services.push(checked);
        }
        Ok(services)
    }
}

#[cfg(test)]
mod reader_contracts {
    use super::*;
    use tokio::io::{AsyncBufReadExt, BufReader};

    async fn read_command(stream: &mut BufReader<TcpStream>) -> Option<Vec<String>> {
        let mut line = String::new();
        stream.read_line(&mut line).await.ok()?;
        if !line.starts_with('*') {
            return None;
        }
        let len: usize = line[1..].trim().parse().ok()?;
        let mut values = Vec::new();
        for _ in 0..len {
            line.clear();
            stream.read_line(&mut line).await.ok()?;
            let count: usize = line.strip_prefix('$')?.trim().parse().ok()?;
            let mut buf = vec![0; count + 2];
            stream.read_exact(&mut buf).await.ok()?;
            if !buf.ends_with(b"\r\n") {
                return None;
            }
            buf.truncate(count);
            values.push(String::from_utf8(buf).ok()?);
        }
        Some(values)
    }

    #[tokio::test]
    async fn authenticates_and_discovers_live_lease_and_inventory() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            for _ in 0..4 {
                let (stream, _) = listener.accept().await.unwrap();
                tokio::spawn(async move {
                    let mut stream = BufReader::new(stream);
                    while let Some(values) = read_command(&mut stream).await {
                        let answer = match values.as_slice() {
                            [op, user, pwd]
                                if op == "AUTH" && user == "default" && pwd == "fixture" =>
                            {
                                b"+OK\r\n".to_vec()
                            }
                            [op, _, _, pattern, _, _]
                                if op == "SCAN" && pattern.ends_with("lease:*") =>
                            {
                                let key = "briareus:v1:services:test:lease:github:abcdef";
                                format!("*2\r\n$1\r\n0\r\n*1\r\n${}\r\n{}\r\n", key.len(), key)
                                    .into_bytes()
                            }
                            [op, _, _, pattern, _, _]
                                if op == "SCAN" && pattern.ends_with("inventory:*") =>
                            {
                                let key = "briareus:v1:services:test:inventory:github";
                                format!("*2\r\n$1\r\n0\r\n*1\r\n${}\r\n{}\r\n", key.len(), key)
                                    .into_bytes()
                            }
                            [op, key] if op == "GET" && key.ends_with("inventory:github") => {
                                let data = r#"{"id":"github","name":"GitHub","group":"svc"}"#;
                                format!("${}\r\n{}\r\n", data.len(), data).into_bytes()
                            }
                            _ => b"-ERROR\r\n".to_vec(),
                        };
                        if stream.get_mut().write_all(&answer).await.is_err() {
                            break;
                        }
                    }
                });
            }
        });
        let client = DiscoveryReader::new(&DiscoveryConfig {
            enabled: true,
            valkey_url: format!("redis://127.0.0.1:{port}/0"),
            username: "default".into(),
            password: "fixture".into(),
            namespace: "briareus:v1".into(),
            environment: "test".into(),
        })
        .unwrap();
        assert_eq!(
            client.active_services().await.unwrap(),
            ["github".to_owned()].into()
        );
        assert_eq!(
            client.inventory().await.unwrap(),
            vec![ServiceIdentity::new("github", "GitHub", "svc").unwrap()]
        );
        server.abort();
    }
}
