import type { ModuleArtifact, ModuleCatalog, ModuleImage, LogicalModule } from "@/entities/node";
import {
  replyArray,
  replyBoolean,
  replyChoice,
  replyInstant,
  replyLimits,
  replyRecord,
  replyString,
  replyUuid,
} from "./node-reply-values";
function logicalModule(value: unknown): LogicalModule {
  const item = replyRecord(value);
  return {
    key: replyString(item.key, 128),
    name: replyString(item.name, 128),
    components: replyArray(item.components, (value) => replyString(value, 128)),
  };
}
function artifact(value: unknown): ModuleArtifact {
  const item = replyRecord(value),
    inputs = replyRecord(item.inputs);
  return {
    key: replyString(item.key, 128),
    name: replyString(item.name, 128),
    lifecycle: replyChoice(item.lifecycle, ["stateless", "sessionful"]),
    workspace: replyBoolean(item.workspace),
    node_adapter: replyBoolean(item.node_adapter),
    inputs: {
      dockerfile: replyString(inputs.dockerfile),
      paths: replyArray(inputs.paths, (value) => replyString(value)),
      platform: replyString(inputs.platform, 128),
    },
    minimum_limits: replyLimits(item.minimum_limits),
    default_limits: replyLimits(item.default_limits),
  };
}
function image(value: unknown): ModuleImage {
  const item = replyRecord(value),
    reference = replyString(item.image, 512),
    commit = replyString(item.source_commit, 40),
    fingerprint = replyString(item.input_fingerprint, 64);
  if (
    !/^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$/.test(reference) ||
    !/^[a-f0-9]{40}$/.test(commit) ||
    !/^[a-f0-9]{64}$/.test(fingerprint)
  )
    throw Error("NODE_RESPONSE_INVALID");
  return {
    id: replyUuid(item.id),
    module: replyString(item.module, 128),
    source_commit: commit,
    input_fingerprint: fingerprint,
    image: reference,
    platform: replyString(item.platform, 128),
    state: replyChoice(item.state, ["published"]),
    created_at: replyInstant(item.created_at),
  };
}
export function decodeModuleCatalog(value: unknown): ModuleCatalog {
  const catalog = replyRecord(value);
  return {
    modules: replyArray(catalog.modules, logicalModule),
    artifacts: replyArray(catalog.artifacts, artifact),
    releases: replyArray(catalog.releases, image),
  };
}
