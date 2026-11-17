//! Native SigNoz query implementation, deliberately independent of the MCP transport.
//! Request shapes match the existing V1 Python Hand; use a mock directory/HTTP
//! endpoint for parity tests before enabling any live rollout.
use briareus_hand_core::{AccountDirectory, HandError, JsonHttp};
use chrono::DateTime;
use reqwest::Method;
use serde_json::{Value, json};

pub struct SigNozApi<D> {
    directory: D,
}

impl<D: AccountDirectory> SigNozApi<D> {
    pub fn new(directory: D) -> Self {
        Self { directory }
    }

    pub async fn sources(&self) -> Result<Value, HandError> {
        self.directory.sources().await
    }

    pub async fn connection(&self, account_id: &str) -> Result<Value, HandError> {
        let account = self.directory.resolve(account_id).await?;
        let mut safe = account.public();
        safe.as_object_mut()
            .ok_or(HandError::InvalidResponse)?
            .insert("credential_configured".into(), json!(true));
        Ok(safe)
    }

    async fn provider_request(
        &self,
        account_id: &str,
        method: Method,
        path: &[&str],
        query: &[(&str, &str)],
        payload: Option<&Value>,
    ) -> Result<Value, HandError> {
        let account = self.directory.resolve(account_id).await?;
        let client = JsonHttp::new(
            &account.base_url,
            "SIGNOZ-API-KEY",
            &account.credential,
            account.verify_tls,
            account.ca_cert_pem.as_deref(),
        )?;
        client.json(method, path, query, payload).await
    }

    pub async fn query_range(&self, account_id: &str, payload: &Value) -> Result<Value, HandError> {
        if !payload.is_object() {
            return Err(HandError::Invalid("query must be a JSON object".into()));
        }
        self.provider_request(
            account_id,
            Method::POST,
            &["api", "v5", "query_range"],
            &[],
            Some(payload),
        )
        .await
    }

    pub async fn search_logs(
        &self,
        account_id: &str,
        start_ms: i64,
        end_ms: i64,
        filter: &str,
        limit: i64,
        offset: i64,
    ) -> Result<Value, HandError> {
        let payload = logs_payload(start_ms, end_ms, filter, limit, offset)?;
        self.query_range(account_id, &payload).await
    }

    pub async fn search_traces(
        &self,
        account_id: &str,
        start_ms: i64,
        end_ms: i64,
        filter: &str,
        limit: i64,
        offset: i64,
    ) -> Result<Value, HandError> {
        let payload = traces_payload(start_ms, end_ms, filter, limit, offset)?;
        self.query_range(account_id, &payload).await
    }

    pub async fn list_services(
        &self,
        account_id: &str,
        start: &str,
        end: &str,
    ) -> Result<Value, HandError> {
        let start_ns = service_timestamp_ns(start)?;
        let end_ns = service_timestamp_ns(end)?;
        if end_ns <= start_ns {
            return Err(HandError::Invalid(
                "service time range requires end after start".into(),
            ));
        }
        self.provider_request(
            account_id,
            Method::POST,
            &["api", "v1", "services"],
            &[],
            Some(&json!({"start":start_ns.to_string(), "end":end_ns.to_string()})),
        )
        .await
    }

    pub async fn field_keys(
        &self,
        account_id: &str,
        signal: &str,
        search_text: &str,
        metric_name: &str,
    ) -> Result<Value, HandError> {
        let mut query = vec![("signal", signal)];
        if !search_text.is_empty() {
            query.push(("searchText", search_text));
        }
        if !metric_name.is_empty() {
            query.push(("metricName", metric_name));
        }
        self.provider_request(
            account_id,
            Method::GET,
            &["api", "v1", "fields", "keys"],
            &query,
            None,
        )
        .await
    }

    pub async fn field_values(
        &self,
        account_id: &str,
        signal: &str,
        name: &str,
        search_text: &str,
        metric_name: &str,
    ) -> Result<Value, HandError> {
        let mut query = vec![("signal", signal), ("name", name)];
        if !search_text.is_empty() {
            query.push(("searchText", search_text));
        }
        if !metric_name.is_empty() {
            query.push(("metricName", metric_name));
        }
        self.provider_request(
            account_id,
            Method::GET,
            &["api", "v1", "fields", "values"],
            &query,
            None,
        )
        .await
    }
}

fn validate_range(start_ms: i64, end_ms: i64, limit: i64, offset: i64) -> Result<(), HandError> {
    if start_ms <= 0 || end_ms <= start_ms {
        return Err(HandError::Invalid(
            "start_ms and end_ms must define a positive time range".into(),
        ));
    }
    if !(1..=500).contains(&limit) {
        return Err(HandError::Invalid("limit must be between 1 and 500".into()));
    }
    if offset < 0 {
        return Err(HandError::Invalid("offset must be >= 0".into()));
    }
    Ok(())
}

pub fn logs_payload(
    start_ms: i64,
    end_ms: i64,
    filter_expression: &str,
    limit: i64,
    offset: i64,
) -> Result<Value, HandError> {
    validate_range(start_ms, end_ms, limit, offset)?;
    Ok(json!({
        "schemaVersion":"v1",
        "start":start_ms, "end":end_ms,
        "requestType":"raw",
        "compositeQuery":{"queries":[{
            "type":"builder_query",
            "spec":{
                "name":"A", "signal":"logs", "disabled":false,
                "filter":{"expression":filter_expression},
                "limit":limit, "offset":offset,
                "order":[
                    {"key":{"name":"timestamp"},"direction":"desc"},
                    {"key":{"name":"id"},"direction":"desc"}
                ],
                "having":{"expression":""}
            }
        }]},
        "formatOptions":{"formatTableResultForUI":false,"fillGaps":false},
        "variables":{}
    }))
}

const TRACE_FIELDS: [(&str, &str, &str); 13] = [
    ("timestamp", "number", "span"),
    ("trace_id", "string", "span"),
    ("span_id", "string", "span"),
    ("parent_span_id", "string", "span"),
    ("name", "string", "span"),
    ("service.name", "string", "resource"),
    ("kind_string", "string", "span"),
    ("duration_nano", "number", "span"),
    ("has_error", "bool", "span"),
    ("status_code_string", "string", "span"),
    ("status_message", "string", "span"),
    ("response_status_code", "string", "span"),
    ("http_method", "string", "span"),
];

pub fn traces_payload(
    start_ms: i64,
    end_ms: i64,
    filter_expression: &str,
    limit: i64,
    offset: i64,
) -> Result<Value, HandError> {
    validate_range(start_ms, end_ms, limit, offset)?;
    let fields: Vec<Value> = TRACE_FIELDS.iter().map(|(name, kind, context)| {
        json!({"name":name,"fieldDataType":kind,"signal":"traces","fieldContext":context})
    }).collect();
    Ok(json!({
        "schemaVersion":"v1",
        "start":start_ms,"end":end_ms,
        "requestType":"raw",
        "compositeQuery":{"queries":[{
            "type":"builder_query",
            "spec":{
                "name":"A","signal":"traces","disabled":false,
                "filter":{"expression":filter_expression},
                "limit":limit,"offset":offset,
                "order":[{"key":{"name":"timestamp"},"direction":"desc"}],
                "having":{"expression":""},
                "selectFields":fields
            }
        }]},
        "formatOptions":{"formatTableResultForUI":false,"fillGaps":false},
        "variables":{}
    }))
}

/// Normalizes SigNoz service windows to signed post-epoch nanoseconds.
/// Recognizes exactly 10/13/16/19-digit Unix timestamps and RFC3339 offsets.
/// For parity with Python datetime, subsecond precision is microseconds.
pub fn service_timestamp_ns(value: &str) -> Result<i128, HandError> {
    let text = value.trim();
    let result = if text.bytes().all(|byte| byte.is_ascii_digit()) && !text.is_empty() {
        let multiplier: i128 = match text.len() {
            10 => 1_000_000_000,
            13 => 1_000_000,
            16 => 1_000,
            19 => 1,
            _ => return Err(HandError::Invalid(
                "service timestamps must use 10/13/16/19-digit Unix units or timezone-aware ISO 8601".into()
            )),
        };
        text.parse::<i128>()
            .map_err(|_| HandError::Invalid("invalid Unix timestamp".into()))?
            .checked_mul(multiplier)
            .ok_or_else(|| HandError::Invalid("service timestamp overflow".into()))?
    } else {
        let parsed = DateTime::parse_from_rfc3339(text).map_err(|_| {
            HandError::Invalid("service timestamps require timezone-aware ISO 8601".into())
        })?;
        i128::from(parsed.timestamp()) * 1_000_000_000
            + i128::from(parsed.timestamp_subsec_nanos() / 1_000) * 1_000
    };
    if result <= 0 {
        return Err(HandError::Invalid(
            "service timestamps must be after the Unix epoch".into(),
        ));
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timestamp_unit_and_offset_parity() {
        let expected = 1_794_355_200_000_000_000_i128;
        for sample in [
            "2026-11-11T00:00:00Z",
            "2026-11-11T01:00:00+01:00",
            "1794355200",
            "1794355200000",
            "1794355200000000",
            "1794355200000000000",
        ] {
            assert_eq!(service_timestamp_ns(sample).unwrap(), expected, "{sample}");
        }
        assert_eq!(
            service_timestamp_ns("2026-11-11T00:00:00.123456Z").unwrap(),
            expected + 123_456_000
        );
        for invalid in ["2026-11-11", "bad", "17943552000", "0", ""] {
            assert!(service_timestamp_ns(invalid).is_err(), "{invalid}");
        }
    }

    #[test]
    fn query_payloads_keep_python_wire_shapes() {
        let logs = logs_payload(1, 2, "service.name = 'api'", 42, 3).unwrap();
        assert_eq!(
            logs["compositeQuery"]["queries"][0]["spec"]["filter"]["expression"],
            "service.name = 'api'"
        );
        assert_eq!(
            logs["compositeQuery"]["queries"][0]["spec"]["order"][1]["key"]["name"],
            "id"
        );
        assert_eq!(logs["requestType"], "raw");
        let traces = traces_payload(1, 2, "", 100, 0).unwrap();
        let fields = traces["compositeQuery"]["queries"][0]["spec"]["selectFields"]
            .as_array()
            .unwrap();
        assert_eq!(fields.len(), 13);
        assert_eq!(fields[5]["name"], "service.name");
        assert_eq!(fields[5]["fieldContext"], "resource");
        for invalid in [
            (0, 1, 100, 0),
            (2, 1, 100, 0),
            (1, 2, 0, 0),
            (1, 2, 501, 0),
            (1, 2, 100, -1),
        ] {
            assert!(logs_payload(invalid.0, invalid.1, "", invalid.2, invalid.3).is_err());
            assert!(traces_payload(invalid.0, invalid.1, "", invalid.2, invalid.3).is_err());
        }
    }
}
