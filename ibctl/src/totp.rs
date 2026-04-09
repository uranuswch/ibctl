//! TOTP (Time-based One-Time Password) generation for two-factor authentication.
//!
//! The primary implementation shells out to `oathtool`, piping the secret via
//! stdin to avoid exposing it in /proc/PID/cmdline.

use crate::config::TotpProvider;
use crate::types::TotpCode;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum TotpError {
    #[error("failed to execute oathtool: {0}")]
    ExecutionFailed(#[from] std::io::Error),
    #[error("oathtool returned non-zero exit code: {0}")]
    OathtoolFailed(String),
    #[error("invalid base32 TOTP secret")]
    InvalidBase32,
    #[error("TOTP secret is empty after decoding")]
    EmptySecret,
    #[error("system clock is before the Unix epoch")]
    SystemTimeBeforeEpoch,
}

/// Trait for TOTP code generation providers.
pub trait TotpCodeGenerator: Send + Sync {
    /// Generate a 6-digit TOTP code from a base32-encoded secret.
    fn generate(&self, secret: &str) -> Result<TotpCode, TotpError>;
}

/// TOTP provider that shells out to the `oathtool` command-line utility.
///
/// The secret is piped via stdin (not passed as a command-line argument)
/// to prevent exposure in /proc/PID/cmdline.
pub struct OathtoolProvider;

impl TotpCodeGenerator for OathtoolProvider {
    fn generate(&self, secret: &str) -> Result<TotpCode, TotpError> {
        use std::io::Write;
        use std::process::{Command, Stdio};

        let mut child = Command::new("oathtool")
            .args(["--totp", "--base32", "-"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;

        // Write secret to stdin and close it
        if let Some(mut stdin) = child.stdin.take() {
            stdin.write_all(secret.as_bytes())?;
        }

        let output = child.wait_with_output()?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(TotpError::OathtoolFailed(stderr.to_string()));
        }

        let code = String::from_utf8_lossy(&output.stdout).trim().to_string();
        log::debug!("Generated TOTP code (length={})", code.len());
        Ok(TotpCode::new(code))
    }
}

/// Decode an RFC 4648 base32 TOTP secret with permissive parsing.
///
/// Matches `oathtool --base32`'s tolerance: whitespace is stripped, lowercase
/// input is accepted (normalized to uppercase), and padding is optional.
fn decode_secret(secret: &str) -> Result<Vec<u8>, TotpError> {
    let normalized: String = secret
        .chars()
        .filter(|c| !c.is_whitespace())
        .collect::<String>()
        .to_ascii_uppercase();

    let key = base32::decode(base32::Alphabet::Rfc4648 { padding: false }, &normalized)
        .ok_or(TotpError::InvalidBase32)?;

    if key.is_empty() {
        return Err(TotpError::EmptySecret);
    }
    Ok(key)
}

/// Current Unix time in seconds. Separate so callers can mock time in tests.
fn current_unix_time() -> Result<u64, TotpError> {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .map_err(|_| TotpError::SystemTimeBeforeEpoch)
}

/// Compute an RFC 6238 TOTP code at a specific Unix time.
///
/// IB uses SHA-1, a 30-second step, and 6 digits — the same defaults as
/// `oathtool --totp`.
fn generate_at(key: &[u8], unix_time: u64) -> String {
    use totp_lite::{totp_custom, Sha1, DEFAULT_STEP};
    totp_custom::<Sha1>(DEFAULT_STEP, 6, key, unix_time)
}

/// TOTP provider that generates codes in-process using RFC 6238
/// (HMAC-SHA1, 30-second step, 6 digits).
pub struct BuiltinProvider;

impl TotpCodeGenerator for BuiltinProvider {
    fn generate(&self, secret: &str) -> Result<TotpCode, TotpError> {
        let key = decode_secret(secret)?;
        let now = current_unix_time()?;
        let code = generate_at(&key, now);
        log::debug!("Generated TOTP code (length={})", code.len());
        Ok(TotpCode::new(code))
    }
}

/// Factory function to create a TOTP code generator by provider type.
pub fn create_provider(provider: TotpProvider) -> Box<dyn TotpCodeGenerator> {
    match provider {
        TotpProvider::Oathtool => Box::new(OathtoolProvider),
        TotpProvider::Builtin => Box::new(BuiltinProvider),
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;
    use crate::config::TotpProvider;

    // RFC 6238 Appendix B: shared secret for SHA-1 is ASCII "12345678901234567890"
    const RFC_SECRET: &[u8] = b"12345678901234567890";
    // Base32 (RFC 4648) encoding of RFC_SECRET
    const RFC_SECRET_BASE32: &str = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";

    // --- RFC 6238 Appendix B vectors (SHA-1, 6-digit truncation) -------------

    #[test]
    fn rfc6238_vector_t59() {
        assert_eq!(generate_at(RFC_SECRET, 59), "287082");
    }

    #[test]
    fn rfc6238_vector_t1111111109() {
        assert_eq!(generate_at(RFC_SECRET, 1111111109), "081804");
    }

    #[test]
    fn rfc6238_vector_t1111111111() {
        assert_eq!(generate_at(RFC_SECRET, 1111111111), "050471");
    }

    #[test]
    fn rfc6238_vector_t1234567890() {
        assert_eq!(generate_at(RFC_SECRET, 1234567890), "005924");
    }

    #[test]
    fn rfc6238_vector_t2000000000() {
        assert_eq!(generate_at(RFC_SECRET, 2000000000), "279037");
    }

    // --- Base32 normalization ------------------------------------------------

    #[test]
    fn decode_secret_canonical_uppercase() {
        assert_eq!(decode_secret(RFC_SECRET_BASE32).unwrap(), RFC_SECRET);
    }

    #[test]
    fn decode_secret_accepts_lowercase() {
        let lower = RFC_SECRET_BASE32.to_ascii_lowercase();
        assert_eq!(decode_secret(&lower).unwrap(), RFC_SECRET);
    }

    #[test]
    fn decode_secret_strips_whitespace() {
        let spaced = "GEZD GNBV GY3T QOJQ\tGEZD GNBV GY3T QOJQ\n";
        assert_eq!(decode_secret(spaced).unwrap(), RFC_SECRET);
    }

    // --- Error paths ---------------------------------------------------------

    #[test]
    fn decode_secret_rejects_invalid_base32() {
        assert!(matches!(
            decode_secret("!!not-base32!!"),
            Err(TotpError::InvalidBase32)
        ));
    }

    #[test]
    fn decode_secret_rejects_empty_string() {
        assert!(matches!(decode_secret(""), Err(TotpError::EmptySecret)));
    }

    #[test]
    fn decode_secret_rejects_whitespace_only() {
        assert!(matches!(
            decode_secret("   \n\t  "),
            Err(TotpError::EmptySecret)
        ));
    }

    // --- BuiltinProvider end-to-end ------------------------------------------

    #[test]
    fn builtin_provider_returns_six_ascii_digits() {
        let provider = BuiltinProvider;
        let code = provider.generate(RFC_SECRET_BASE32).unwrap();
        let code_str = code.into_inner();
        assert_eq!(code_str.len(), 6);
        assert!(code_str.chars().all(|c| c.is_ascii_digit()));
    }

    #[test]
    fn create_provider_builtin_produces_valid_code() {
        let provider = create_provider(TotpProvider::Builtin);
        let code = provider.generate(RFC_SECRET_BASE32).unwrap();
        let code_str = code.into_inner();
        assert_eq!(code_str.len(), 6);
        assert!(code_str.chars().all(|c| c.is_ascii_digit()));
    }

    #[test]
    fn create_provider_oathtool_variant_still_constructs() {
        // Smoke test: we don't invoke oathtool here (no binary guarantee), but
        // constructing the provider must succeed.
        let _ = create_provider(TotpProvider::Oathtool);
    }
}
