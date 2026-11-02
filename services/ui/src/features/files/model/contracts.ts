/** Application operations over one current, owner-authorized project workspace. */
export interface FileEntry {
  path: string;
  name: string;
  type: "file" | "directory";
  size_bytes: number;
  modified_at_ns: number;
  mime_type?: string;
}
export type FileInformation = FileEntry;
export interface FilePage {
  path: string;
  entries: FileEntry[];
  count: number;
  total: number;
  offset: number;
  limit: number;
  truncated: boolean;
}
export interface FileChunk {
  path: string;
  offset: number;
  bytes_read: number;
  next_offset: number;
  size_bytes: number;
  eof: boolean;
  bytes: Uint8Array<ArrayBuffer>;
}
export interface FileHash {
  path: string;
  sha256: string;
}
export interface FileWriteReceipt {
  path: string;
  bytes_written: number;
  next_offset: number;
  size_bytes: number;
}
export interface FileListQuery {
  path: string;
  offset: number;
  limit: number;
}
export interface FileReadQuery {
  path: string;
  offset: number;
  length: number;
}
export interface FileWriteChunk {
  path: string;
  bytes: Uint8Array;
  offset: number;
  truncate: boolean;
  create_parents: boolean;
}
export interface FileWorkspacePort {
  info(path: string): Promise<FileInformation>;
  list(query: FileListQuery): Promise<FilePage>;
  read(query: FileReadQuery): Promise<FileChunk>;
  hash(path: string): Promise<FileHash>;
  write(chunk: FileWriteChunk): Promise<FileWriteReceipt>;
}
