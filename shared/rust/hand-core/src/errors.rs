use thiserror::Error;

/// Safe, bounded descriptions; never include provider bodies, bearer tokens or URLs.
#[derive(Debug, Error)]
pub enum HandError {
    #[error("invalid arguments: {0}")]
    Invalid(String),
    #[error("provider account not found or disabled")]
    AccountUnavailable,
    #[error("provider authentication was rejected (HTTP 401)")]
    Unauthorized,
    #[error("provider access denied (HTTP 403); verify account permissions and resource scope")]
    Forbidden,
    #[error("upstream request failed with HTTP {0}")]
    UpstreamStatus(u16),
    #[error("upstream request failed or timed out")]
    Transport,
    #[error("upstream returned an invalid or oversized JSON response")]
    InvalidResponse,
    #[error("invalid provider URL or TLS configuration")]
    Configuration,
    #[error("Control Panel service token is required")]
    MissingToken,
}
