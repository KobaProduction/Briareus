//! JWA ES512 verification using the existing AWS-LC cryptographic backend.
//! Coordinates and the JOSE signature use the fixed-width P-521 encoding.
use aws_lc_rs::signature::{ECDSA_P521_SHA512_FIXED, UnparsedPublicKey};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use serde_json::Value;

use crate::TokenError;

const INVALID_SIGNATURE: TokenError = TokenError {
    reason: "invalid_signature",
};

/// Check the intended usage and exact algorithm of a public JWK.
pub(crate) fn check_key_policy(jwk: &Value, algorithm: &str) -> Result<(), TokenError> {
    let key = jwk.as_object().ok_or(INVALID_SIGNATURE)?;
    if key
        .get("alg")
        .is_some_and(|v| v.as_str() != Some(algorithm))
        || key.get("use").is_some_and(|v| v.as_str() != Some("sig"))
        || key.get("key_ops").is_some_and(|v| {
            !v.as_array().is_some_and(|ops| {
                ops.iter().all(Value::is_string)
                    && ops.iter().any(|op| op.as_str() == Some("verify"))
            })
        })
    {
        return Err(INVALID_SIGNATURE);
    }
    Ok(())
}

/// Verify an ES512 JWS signing input against a P-521 public JWK. This function
/// verifies only the signature; callers must separately enforce their token
/// type's issuer, audience, timestamp, nonce and other claim requirements.
pub fn verify_es512(jwk: &Value, input: &[u8], signature: &[u8]) -> Result<(), TokenError> {
    check_key_policy(jwk, "ES512")?;
    if jwk.get("kty").and_then(Value::as_str) != Some("EC")
        || jwk.get("crv").and_then(Value::as_str) != Some("P-521")
        || signature.len() != 132
    {
        return Err(INVALID_SIGNATURE);
    }
    let coordinate = |name| -> Result<[u8; 66], TokenError> {
        let value = jwk
            .get(name)
            .and_then(Value::as_str)
            .ok_or(INVALID_SIGNATURE)?;
        URL_SAFE_NO_PAD
            .decode(value)
            .map_err(|_| INVALID_SIGNATURE)?
            .try_into()
            .map_err(|_| INVALID_SIGNATURE)
    };
    let mut point = [0u8; 133];
    point[0] = 4;
    point[1..67].copy_from_slice(&coordinate("x")?);
    point[67..].copy_from_slice(&coordinate("y")?);
    UnparsedPublicKey::new(&ECDSA_P521_SHA512_FIXED, point)
        .verify(input, signature)
        .map_err(|_| INVALID_SIGNATURE)
}
