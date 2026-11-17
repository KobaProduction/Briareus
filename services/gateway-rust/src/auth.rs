//! Local shadow OIDC adapter. JWT validation is performed by shared Rust code,
//! and no verified call may yet reach a provider until proxy-session parity.
use axum::http::{HeaderMap, StatusCode, header};
use briareus_oidc_verifier_rs::{
    ExternalTokenVerifier, IntrospectionVerifier, JwtTokenVerifier, OidcSettings, RolesFormat,
};
use std::env;

#[derive(Clone)]
pub struct ShadowOidc {
    pub verifier: Option<ExternalTokenVerifier>,
    public_base_url: Option<String>,
    public_host: Option<String>,
    issuer: Option<String>,
    scopes: Vec<String>,
}

impl ShadowOidc {
    pub fn from_env(required_role: &str) -> anyhow::Result<Self> {
        let Some(issuer) = env::var("OIDC_ISSUER_URL").ok() else {
            return Ok(Self {
                verifier: None,
                public_base_url: None,
                public_host: None,
                issuer: None,
                scopes: Vec::new(),
            }); // Only shadow. Fail closed on calls.
        };
        let mode = env::var("OIDC_TOKEN_VERIFICATION").unwrap_or_else(|_| "jwt".into());
        let roles_format = match env::var("OIDC_ROLES_FORMAT").as_deref() {
            Ok("organization_grants") => RolesFormat::OrganizationGrants,
            Err(_) | Ok("list") => RolesFormat::List,
            _ => anyhow::bail!("Invalid OIDC_ROLES_FORMAT"),
        };
        let roles_claim_path = serde_json::from_str::<Vec<String>>(
            &env::var("OIDC_ROLES_CLAIM_PATH").unwrap_or_else(|_| "[\"roles\"]".into()),
        )?;
        let algorithms = env::var("OIDC_JWT_ALGORITHMS")
            .unwrap_or_else(|_| "RS256".into())
            .split(',')
            .map(|value| value.trim().to_owned())
            .collect();
        let public_base_url =
            env::var("SERVICE_URL_GATEWAY").or_else(|_| env::var("MCP_PUBLIC_BASE_URL"))?;
        let (public_base_url, public_host) = canonical_public_origin(&public_base_url)?;
        let scopes: Vec<String> = env::var("OIDC_SCOPES")
            .unwrap_or_else(|_| "openid,profile,email,offline_access".into())
            .split(',')
            .map(str::trim)
            .map(str::to_owned)
            .filter(|value| !value.is_empty())
            .collect();
        anyhow::ensure!(
            scopes.iter().any(|scope| scope == "openid"),
            "OIDC_SCOPES must include openid"
        );
        let settings = OidcSettings {
            issuer: issuer.clone(),
            audience: env::var("OIDC_AUDIENCE")?,
            required_role: required_role.to_owned(),
            roles_claim_path,
            roles_format,
            roles_organization_id: env::var("OIDC_ROLES_ORGANIZATION_ID").unwrap_or_default(),
            algorithms,
        };
        let verifier = match mode.as_str() {
            "jwt" => ExternalTokenVerifier::Jwt(JwtTokenVerifier::new(settings)?),
            "introspection" => ExternalTokenVerifier::Introspection(IntrospectionVerifier::new(
                settings,
                env::var("OIDC_INTROSPECTION_CLIENT_ID")?,
                env::var("OIDC_INTROSPECTION_CLIENT_SECRET")?,
            )?),
            _ => anyhow::bail!("Unsupported OIDC_TOKEN_VERIFICATION"),
        };
        Ok(Self {
            verifier: Some(verifier),
            public_base_url: Some(public_base_url),
            public_host: Some(public_host),
            issuer: Some(issuer),
            scopes,
        })
    }
}

fn canonical_public_origin(value: &str) -> anyhow::Result<(String, String)> {
    let parsed = url::Url::parse(value)?;
    let local = parsed.host_str().is_some_and(|host| {
        matches!(host, "localhost" | "127.0.0.1" | "[::1]") || host.ends_with(".localhost")
    });
    anyhow::ensure!(
        (parsed.scheme() == "https" || (parsed.scheme() == "http" && local))
            && parsed.host().is_some()
            && parsed.username().is_empty()
            && parsed.password().is_none()
            && parsed.query().is_none()
            && parsed.fragment().is_none()
            && parsed.path() == "/"
            && value.is_ascii()
            && value.trim() == value
            && !value.bytes().any(|c| c.is_ascii_whitespace() || c < 32)
            && !value.contains(['*', ',', '%'])
            && !value.trim_end_matches('/').ends_with(':'),
        "Gateway requires one validated HTTPS public origin"
    );
    let without_slash = value.trim_end_matches('/');
    let host = without_slash
        .strip_prefix(&format!("{}://", parsed.scheme()))
        .ok_or_else(|| anyhow::anyhow!("Invalid canonical origin"))?;
    anyhow::ensure!(!host.is_empty(), "Empty canonical public host");
    Ok((without_slash.to_owned(), host.to_owned()))
}

impl ShadowOidc {
    /// Mirror Python's exact MCP Host/Origin policy derived from the public URL.
    pub fn validate_mcp_headers(&self, headers: &HeaderMap) -> Result<(), StatusCode> {
        let Some(host) = self.public_host.as_deref() else {
            // Loopback-only shadow without OAuth has no public resource URL.
            // The route will still fail closed with 401 for every bearer.
            return Ok(());
        };
        let mut hosts = headers.get_all(header::HOST).iter();
        if hosts.next().and_then(|v| v.to_str().ok()) != Some(host) || hosts.next().is_some() {
            return Err(StatusCode::MISDIRECTED_REQUEST);
        }
        let mut origins = headers.get_all(header::ORIGIN).iter();
        if let Some(value) = origins.next()
            && value.to_str().ok() != self.public_base_url.as_deref()
        {
            return Err(StatusCode::FORBIDDEN);
        }
        if origins.next().is_some() {
            return Err(StatusCode::FORBIDDEN);
        }
        Ok(())
    }

    pub fn public_host(&self) -> Option<&str> {
        self.public_host.as_deref()
    }

    pub fn public_origin(&self) -> Option<&str> {
        self.public_base_url.as_deref()
    }

    pub fn challenge(
        &self,
        service: &briareus_service_discovery_rs::ServiceIdentity,
    ) -> Option<String> {
        let base = self.public_base_url.as_ref()?;
        // Match FastMCP RemoteAuthProvider's RFC 9728 challenge exactly.
        let metadata = format!(
            "{base}/.well-known/oauth-protected-resource{}",
            service.mcp_path()
        );
        Some(format!(
            "Bearer scope=\"{}\", resource_metadata=\"{metadata}\"",
            self.scopes.join(" ")
        ))
    }

    pub fn resource_metadata(
        &self,
        service: &briareus_service_discovery_rs::ServiceIdentity,
    ) -> Option<serde_json::Value> {
        let base = self.public_base_url.as_ref()?;
        let issuer = self.issuer.as_ref()?;
        Some(serde_json::json!({
            "resource": format!("{base}{}", service.mcp_path()),
            "authorization_servers": [issuer],
            "scopes_supported": self.scopes,
            "bearer_methods_supported": ["header"],
            "resource_name": format!("Briareus {}", service.name),
        }))
    }
}

#[cfg(test)]
mod public_origin_tests {
    use super::canonical_public_origin;

    #[test]
    fn accepts_only_one_exact_canonical_origin() {
        for (value, host) in [
            ("https://node.example", "node.example"),
            ("https://node.example:8443", "node.example:8443"),
            ("http://localhost:18080", "localhost:18080"),
            ("http://127.0.0.1:18080", "127.0.0.1:18080"),
        ] {
            assert_eq!(
                canonical_public_origin(value).unwrap(),
                (value.into(), host.into())
            );
        }
        for value in [
            "http://node.example",
            "https://node.example/path",
            "https://user:pass@node.example",
            "https://node.example?query=yes",
            "https://node.example#fragment",
            "https://*.example",
            "https://node.example:invalid-port",
            "https://node.example:",
            "https://node.example,https://attacker.example",
            "",
        ] {
            assert!(canonical_public_origin(value).is_err(), "{value}");
        }
    }
}
