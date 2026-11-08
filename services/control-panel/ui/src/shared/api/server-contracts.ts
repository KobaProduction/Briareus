/** Control Panel views over Server MCP; wire types stay independent from table widgets. */
export interface DiskUsage { total_bytes: number; used_bytes: number; free_bytes: number }
export interface WorkspaceStatistics {
  root?: string
  free_bytes?: number
  used_bytes?: number
  total_bytes?: number
  free_display?: string
  used_display?: string
  total_display?: string
  files?: number
  size_bytes?: number
  size_display?: string
}
export interface FileEntry {
  path: string
  name: string
  type: "directory" | "file"
  size_bytes: number
  modified_at_ns: number
  mime_type?: string
}
export interface FileListing {
  path: string
  entries: FileEntry[]
  count: number
  total: number
  offset: number
  limit: number
  truncated: boolean
}
export interface FileDeletion { path: string; deleted?: boolean; already_absent?: boolean }
export interface ContainerResources {
  available: boolean
  cpu_cores: number | null
  memory_bytes: number | null
  pids_limit: number | null
  pids_current: number | null
  zombie_processes: number
}
export type TerminalJobStatus = "running" | "cancelling" | "completed" | "failed" | "interrupted" | "cancelled" | "timed_out"
export interface TerminalStatus {
  resources?: ContainerResources
  uid: number
  gid: number
  groups: Array<{ gid: number; name: string }>
  home: string
  workspace_root: string
  shell: string
  workspaces: number
  jobs: Partial<Record<TerminalJobStatus, number>>
  disk: DiskUsage
  tools: Record<string, string>
  serial_devices: Array<{ path: string; readable: boolean; writable: boolean }>
  ssh_public_keys: string[]
  git_configured: boolean
}
export interface TerminalWorkspace { workspace_id: string; path: string; modified_at: string; active_jobs: number }
export interface TerminalJob {
  job_id: string
  workspace_id: string
  label: string
  command: string
  cwd: string
  interactive: boolean
  state: TerminalJobStatus
  pid: number | null
  exit_code: number | null
  signal: number | null
  created_at: string
  started_at: string
  ended_at: string | null
  duration_seconds: number
  output_bytes: number
  output_truncated: boolean
  timeout_seconds: number
}
export interface TerminalOutput {
  job_id: string
  cursor: number
  next_cursor: number
  output: string
  total_output_bytes: number
  state: TerminalJobStatus
  eof: boolean
  output_truncated: boolean
}
export interface TerminalState { status: TerminalStatus; workspaces: TerminalWorkspace[]; jobs: TerminalJob[] }
export interface TerminalJobState { job: TerminalJob; tail: TerminalOutput }
export interface TerminalJobDeletion { job_id: string; deleted: boolean; reason: string; freed_bytes: number }
export interface TerminalWorkspaceDeletion { workspace_id: string; deleted: boolean; reason: string; freed_bytes: number }
export interface TerminalCleanup {
  dry_run: boolean
  older_than_hours: number
  job_ids: string[]
  count: number
  candidate_bytes: number
  freed_bytes: number
  reason: string
}
