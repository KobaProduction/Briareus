export interface ModuleArtifact {
  key: string;
  name: string;
  lifecycle: "stateless" | "sessionful";
  workspace: boolean;
  node_adapter: boolean;
  inputs: { dockerfile: string; paths: string[]; platform: string };
  minimum_limits: import("./types").ResourceLimits;
  default_limits: import("./types").ResourceLimits;
}
export interface ModuleImage {
  id: string;
  module: string;
  source_commit: string;
  input_fingerprint: string;
  image: string;
  platform: string;
  state: "published";
  created_at: string;
}
export interface LogicalModule {
  key: string;
  name: string;
  components: string[];
}
export interface ModuleCatalog {
  modules: LogicalModule[];
  artifacts: ModuleArtifact[];
  releases: ModuleImage[];
}
