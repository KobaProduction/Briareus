//! Local shadow OIDC adapter. JWT validation is performed by shared Rust code,
//! and no verified call may yet reach a provider until proxy-session parity.
use briareus_oidc_verifier_rs::{
    ExternalTokenVerifier, IntrospectionVerifier, JwtTokenVerifier, OidcSettings, RolesFormat,
};
use std::env;

#[derive(Clone)]
pub struct ShadowOidc {
    pub verifier: Option<ExternalTokenVerifier>,
    public_base_url: Option<String>,
    issuer: Option<String>,
    scopes: Vec<String>,
}

impl ShadowOidc {
    pub fn from_env(required_role: &str) -> anyhow::Result<Self> {
        let Some(issuer) = env::var("OIDC_ISSUER_URL").ok() else {
            return Ok(Self {
                verifier: None,
                public_base_url: None,
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
        let public_base_url = env::var("MCP_PUBLIC_BASE_URL").unwrap_or_default();
        let public_origin = url::Url::parse(&public_base_url)?;
        anyhow::ensure!(
            matches!(public_origin.scheme(), "http" | "https")
                && public_origin.host().is_some()
                && public_origin.username().is_empty()
                && public_origin.password().is_none()
                && public_origin.query().is_none()
                && public_origin.fragment().is_none()
                && public_origin.path() == "/",
            "MCP_PUBLIC_BASE_URL must be an origin without credentials"
        );
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
            public_base_url: Some(public_base_url.trim_end_matches('/').to_owned()),
            issuer: Some(issuer),
            scopes,
        })
    }
}

impl ShadowOidc {
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
