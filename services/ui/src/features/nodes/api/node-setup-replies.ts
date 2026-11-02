import type { ManagedNode } from "@/entities/node";
import type { NodeSetup } from "../model/node-replies";
import {
  replyBoolean,
  replyBudget,
  replyChoice,
  replyInstant,
  replyLimits,
  replyNumber,
  replyRecord,
  replyString,
  replyUuid,
} from "./node-reply-values";
function publicKey(value: unknown): string {
  const key = replyString(value, 4096);
  if (!/^-----BEGIN PUBLIC KEY-----\r?\n[A-Za-z0-9+/=\r\n]+-----END PUBLIC KEY-----\s*$/.test(key))
    throw Error("NODE_SETUP_INVALID");
  return key;
}
function journalTarget(value: unknown): string {
  const target = replyString(value, 512),
    match = /^(\[[^\]\s]+\]|[^:\s/?#@]+):(\d+)$/.exec(target);
  if (!match || target.length < 3 || target.includes("://")) throw Error("NODE_SETUP_INVALID");
  const port = Number(match[2]);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw Error("NODE_SETUP_INVALID");
  return target;
}
/** The server validates X509 contents and certificate validity. The browser
 * accepts only the bounded public PEM transport shape; it never installs trust
 * or treats this reply as a verified live TLS connection. */
function journalCertificate(value: unknown): string {
  const certificate = replyString(value, 65536);
  if (
    !certificate ||
    certificate.includes("PRIVATE KEY") ||
    Array.from(certificate).some((character) => character.charCodeAt(0) > 127)
  )
    throw Error("NODE_SETUP_INVALID");
  const certificates = [
    ...certificate.matchAll(
      /-----BEGIN CERTIFICATE-----\s+([A-Za-z0-9+/=\s]+?)-----END CERTIFICATE-----/g,
    ),
  ];
  if (certificates.length < 1 || certificates.length > 16) throw Error("NODE_SETUP_INVALID");
  for (const match of certificates) {
    const body = match[1];
    if (!body || atob(body.replace(/\s/g, "")).charCodeAt(0) !== 48)
      throw Error("NODE_SETUP_INVALID");
  }
  return certificate;
}
function setupRecord(value: unknown): NodeSetup["node_record"] {
  const node = replyRecord(value),
    scope = replyRecord(node.scope);
  const kind = replyChoice(scope.kind, ["personal", "team", "shared"]),
    owner = scope.owner_uuid === null ? null : replyUuid(scope.owner_uuid);
  if ((kind === "shared") !== (owner === null)) throw Error("NODE_SETUP_INVALID");
  return {
    id: replyUuid(node.id),
    name: replyString(node.name, 128),
    scope: { kind, owner_uuid: owner },
    budget: replyBudget(node.budget),
    enabled: replyBoolean(node.enabled),
    shared_use: replyBoolean(node.shared_use),
    shared_manage: replyBoolean(node.shared_manage),
    created_at: replyInstant(node.created_at),
  };
}
export function decodeNodeSetup(value: unknown, expected: ManagedNode): { setup: NodeSetup } {
  const input = replyRecord(replyRecord(value).setup),
    journal = replyRecord(input.journal);
  if (
    Object.keys(journal).length !== 2 ||
    !Object.hasOwn(journal, "target") ||
    !Object.hasOwn(journal, "ca_certificate")
  )
    throw Error("NODE_SETUP_INVALID");
  const setup: NodeSetup = {
    node_record: setupRecord(input.node_record),
    core_verify_key: publicKey(input.core_verify_key),
    gateway_verify_key: publicKey(input.gateway_verify_key),
    runtime_uid: replyNumber(input.runtime_uid, 2000, 2 ** 31 - 1),
    runtime_user: replyString(input.runtime_user, 128),
    runtime_gid: replyNumber(input.runtime_gid, 2000, 2 ** 31 - 1),
    rootless_budget: replyLimits(input.rootless_budget),
    endpoint: replyString(input.endpoint),
    origin_approved: replyBoolean(input.origin_approved),
    journal: {
      target: journalTarget(journal.target),
      ca_certificate: journalCertificate(journal.ca_certificate),
    },
  };
  if (
    setup.node_record.id !== expected.id ||
    setup.endpoint !== expected.endpoint ||
    setup.runtime_uid !== expected.runtime_uid ||
    setup.runtime_gid !== expected.runtime_uid
  )
    throw Error("NODE_RESPONSE_SCOPE_INVALID");
  return { setup };
}
