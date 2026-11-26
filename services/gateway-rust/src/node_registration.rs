//! Provider-specific, idempotent node-role provisioning owned by Gateway startup.
use std::time::Duration;

use futures_util::StreamExt;
use reqwest::{Client, StatusCode, redirect::Policy};
use serde::Deserialize;
use serde_json::{Value, json};

use crate::auth::canonical_public_origin;

const MAX_RESPONSE: usize = 65536;
const SERVICE: &str = "/zitadel.project.v2.ProjectService/";

#[derive(Deserialize)]
struct Role {
    #[serde(rename = "projectId")]
    project_id: String,
    key: String,
}

#[derive(Deserialize)]
struct Roles {
    #[serde(rename = "projectRoles", default)]
    project_roles: Vec<Role>,
}

#[derive(Deserialize)]
struct Created {
    #[serde(rename = "creationDate")]
    creation_date: String,
}

async fn call(
    client: &Client,
    origin: &str,
    token: &str,
    operation: &str,
    body: Value,
) -> anyhow::Result<(StatusCode, Vec<u8>)> {
    let response = client
        .post(format!("{origin}{SERVICE}{operation}"))
        .bearer_auth(token)
        .header("Connect-Protocol-Version", "1")
        .json(&body)
        .send()
        .await
        .map_err(|_| anyhow::anyhow!("Node role provisioning request failed"))?;
    let status = response.status();
    if status != StatusCode::OK {
        return Ok((status, Vec::new()));
    }
    let mut result = Vec::new();
    let mut chunks = response.bytes_stream();
    while let Some(chunk) = chunks.next().await {
        let chunk = chunk.map_err(|_| anyhow::anyhow!("Node role provisioning response failed"))?;
        anyhow::ensure!(
            result.len() + chunk.len() <= MAX_RESPONSE,
            "Node role provisioning response exceeds limit"
        );
        result.extend_from_slice(&chunk);
    }
    Ok((status, result))
}

pub async fn ensure_node_role(
    issuer: &str,
    project_id: &str,
    node: &str,
    token: &str,
) -> anyhow::Result<bool> {
    let (origin, _) = canonical_public_origin(issuer)?;
    let valid_node_char = |c: u8| c.is_ascii_lowercase() || c.is_ascii_digit();
    anyhow::ensure!(
        !node.is_empty()
            && node.len() <= 63
            && node.as_bytes().first().is_some_and(|c| valid_node_char(*c))
            && node.as_bytes().last().is_some_and(|c| valid_node_char(*c))
            && node.bytes().all(|c| valid_node_char(c) || c == b'-'),
        "Invalid node role identifier"
    );
    anyhow::ensure!(
        !project_id.is_empty()
            && project_id.len() <= 200
            && project_id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'.' | b'-')),
        "Invalid provisioning project"
    );
    anyhow::ensure!(
        !token.is_empty() && !token.chars().any(char::is_whitespace),
        "Protected node provisioning credential required"
    );
    let client = Client::builder()
        .redirect(Policy::none())
        .no_proxy()
        .timeout(Duration::from_secs(10))
        .build()?;
    let (status, body) = call(&client, &origin, token, "ListProjectRoles", json!({
        "projectId":project_id,"filters":[{"roleKeyFilter":{"key":node,"method":"TEXT_FILTER_METHOD_EQUALS"}}],
    })).await?;
    anyhow::ensure!(
        status == StatusCode::OK,
        "Node role lookup rejected ({status})"
    );
    let roles: Roles = serde_json::from_slice(&body)
        .map_err(|_| anyhow::anyhow!("Invalid node role lookup response"))?;
    if roles
        .project_roles
        .iter()
        .any(|role| role.project_id == project_id && role.key == node)
    {
        return Ok(false);
    }
    let display_name = format!("{}{}", node[..1].to_ascii_uppercase(), &node[1..]);
    let (status, body) = call(
        &client,
        &origin,
        token,
        "AddProjectRole",
        json!({
            "projectId":project_id,"roleKey":node,"displayName":display_name,"group":"Nodes",
        }),
    )
    .await?;
    if status == StatusCode::CONFLICT {
        return Ok(false);
    }
    anyhow::ensure!(
        status == StatusCode::OK,
        "Node role creation rejected ({status})"
    );
    let created: Created = serde_json::from_slice(&body)
        .map_err(|_| anyhow::anyhow!("Invalid node role creation receipt"))?;
    chrono::DateTime::parse_from_rfc3339(&created.creation_date)
        .map_err(|_| anyhow::anyhow!("Invalid node role creation date"))?;
    Ok(true)
}
