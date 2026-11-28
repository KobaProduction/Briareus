//! Launch admission for the three deployment boundaries. Public release is an
//! explicit image command, not an operator-controlled authentication switch.
use std::{env, net::IpAddr};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GatewayMode {
    LocalShadow,
    PrivatePreview,
    Public,
}

pub fn configured_mode(
    shadow: bool,
    preview: bool,
    public: bool,
    ip: IpAddr,
    discovery: bool,
    oidc: bool,
) -> anyhow::Result<GatewayMode> {
    let container_bind = ip == IpAddr::V4(std::net::Ipv4Addr::UNSPECIFIED);
    match (shadow, preview, public) {
        (true, false, false) if ip.is_loopback() => Ok(GatewayMode::LocalShadow),
        (false, true, false) if container_bind && discovery && oidc => {
            Ok(GatewayMode::PrivatePreview)
        }
        (false, false, true) if container_bind && discovery && oidc => Ok(GatewayMode::Public),
        _ => anyhow::bail!(
            "Rust Gateway requires one explicit launch mode with its required network and identity configuration"
        ),
    }
}

fn flag(name: &str) -> anyhow::Result<bool> {
    match env::var(name) {
        Err(env::VarError::NotPresent) => Ok(false),
        Ok(value) if value == "true" => Ok(true),
        Ok(value) if value == "false" => Ok(false),
        _ => anyhow::bail!("Invalid {name} mode flag"),
    }
}

fn required(name: &str) -> anyhow::Result<String> {
    let value = env::var(name).map_err(|_| anyhow::anyhow!("{name} is required"))?;
    anyhow::ensure!(
        !value.trim().is_empty() && value.trim() == value,
        "{name} must be configured"
    );
    Ok(value)
}

fn external_https(value: &str) -> bool {
    url::Url::parse(value).is_ok_and(|url| {
        url.scheme() == "https"
            && match url.host() {
                Some(url::Host::Domain(host)) => {
                    let host = host.trim_end_matches('.');
                    !host.eq_ignore_ascii_case("localhost") && !host.ends_with(".localhost")
                }
                Some(url::Host::Ipv4(address)) => {
                    !address.is_loopback() && !address.is_unspecified()
                }
                Some(url::Host::Ipv6(address)) => {
                    !address.is_loopback()
                        && !address.is_unspecified()
                        && address
                            .to_ipv4_mapped()
                            .is_none_or(|ip| !ip.is_loopback() && !ip.is_unspecified())
                }
                None => false,
            }
            && url.username().is_empty()
            && url.password().is_none()
            && url.query().is_none()
            && url.fragment().is_none()
    })
}

pub struct RuntimeConfig {
    pub mode: GatewayMode,
    pub ip: IpAddr,
    pub port: u16,
    pub node: String,
    pub api: String,
    pub ui: String,
}

impl RuntimeConfig {
    pub fn from_env() -> anyhow::Result<Self> {
        let arguments: Vec<_> = env::args().skip(1).collect();
        anyhow::ensure!(
            arguments.is_empty() || arguments == ["--public"],
            "Unknown Gateway launch argument"
        );
        let ip: IpAddr = env::var("BIND_HOST")
            .unwrap_or_else(|_| "127.0.0.1".into())
            .parse()
            .map_err(|_| anyhow::anyhow!("Invalid BIND_HOST"))?;
        let mode = configured_mode(
            flag("RUST_GATEWAY_SHADOW_ONLY")?,
            flag("GATEWAY_PRIVATE_PREVIEW")?,
            arguments == ["--public"],
            ip,
            env::var("VALKEY_PASSWORD").is_ok_and(|v| !v.trim().is_empty()),
            env::var("OIDC_ISSUER_URL").is_ok_and(|v| !v.trim().is_empty()),
        )?;
        if mode != GatewayMode::LocalShadow {
            anyhow::ensure!(
                env::var_os("GATEWAY_SHADOW_TARGETS_JSON").is_none(),
                "Deployed Gateway forbids shadow fixture target overrides"
            );
        }
        let port: u16 = env::var("PORT")
            .unwrap_or_else(|_| "18082".into())
            .parse()
            .map_err(|_| anyhow::anyhow!("Invalid PORT"))?;
        anyhow::ensure!(port != 0, "Invalid PORT");
        let config = Self {
            mode,
            ip,
            port,
            node: required("BRIAREUS_NODE_ID")?,
            api: required("CONTROL_PANEL_URL")?,
            ui: required("CONTROL_PANEL_UI_URL")?,
        };
        config.validate_deployed()?;
        Ok(config)
    }

    fn validate_deployed(&self) -> anyhow::Result<()> {
        if self.mode == GatewayMode::LocalShadow {
            return Ok(());
        }
        // Preserve the deployed resource-server contract. JWT mode needs
        // no client secret. Introspection mode validates the existing pair
        // in ShadowOidc::from_env without reading or renaming it externally.
        for key in [
            "OIDC_ISSUER_URL",
            "OIDC_AUDIENCE",
            "BRIAREUS_SERVICE_TOKEN",
            "VALKEY_PASSWORD",
            "DEPLOYMENT_ENVIRONMENT",
        ] {
            required(key)?;
        }
        let origin = env::var("SERVICE_URL_GATEWAY")
            .or_else(|_| env::var("MCP_PUBLIC_BASE_URL"))
            .map_err(|_| anyhow::anyhow!("Public origin required"))?;
        crate::auth::canonical_public_origin(&origin)?;
        if self.mode == GatewayMode::Public {
            anyhow::ensure!(
                self.port == 8000,
                "Public Gateway must use the private service port 8000"
            );
            anyhow::ensure!(
                matches!(
                    required("DEPLOYMENT_ENVIRONMENT")?.as_str(),
                    "production" | "staging"
                ),
                "Public Gateway requires production or staging deployment"
            );
            anyhow::ensure!(
                external_https(&origin) && external_https(&required("OIDC_ISSUER_URL")?),
                "Public Gateway requires HTTPS public origin and issuer"
            );
            anyhow::ensure!(
                self.api == "http://control-panel-api:8000"
                    && self.ui == "http://control-panel-ui:8080",
                "Public Gateway requires canonical private Control Panel endpoints"
            );
            anyhow::ensure!(
                required("VALKEY_URL")? == "redis://valkey:6379/0",
                "Public Gateway requires canonical private Valkey endpoint"
            );
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::Ipv4Addr;

    #[test]
    fn only_explicit_and_unmixed_modes_are_admitted() {
        let local = Ipv4Addr::LOCALHOST.into();
        let any = Ipv4Addr::UNSPECIFIED.into();
        for bits in 0..8 {
            let (s, p, r) = (bits & 1 != 0, bits & 2 != 0, bits & 4 != 0);
            for address in [local, any] {
                for discovery in [false, true] {
                    for oidc in [false, true] {
                        let expected = match (bits, address, discovery, oidc) {
                            (1, a, _, _) if a == local => Some(GatewayMode::LocalShadow),
                            (2, a, true, true) if a == any => Some(GatewayMode::PrivatePreview),
                            (4, a, true, true) if a == any => Some(GatewayMode::Public),
                            _ => None,
                        };
                        assert_eq!(
                            configured_mode(s, p, r, address, discovery, oidc).ok(),
                            expected
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn public_origins_cannot_be_insecure_or_loopback() {
        assert!(external_https("https://auth.example/realms/briareus"));
        for url in [
            "http://auth.example",
            "https://localhost",
            "https://127.0.0.1",
            "https://127.0.0.2",
            "https://localhost.",
            "https://0.0.0.0",
            "https://[::ffff:127.0.0.1]",
            "https://example.localhost",
            "https://[::1]",
            "https://user:pass@auth.example",
            "https://auth.example?x=y",
            "https://auth.example#fragment",
        ] {
            assert!(!external_https(url), "{url}");
        }
    }
}
