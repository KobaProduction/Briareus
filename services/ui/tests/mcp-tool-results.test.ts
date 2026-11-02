import { describe, expect, it } from "bun:test";
import { completeAnalysisOperation, updateAnalysisArgument } from "../src/features/analysis";
import { analysisTools } from "../src/features/analysis/api/tool-results";
import { browserInventory, browserPreview, browserSnapshot } from "../src/entities/browser";
import {
  downloadFileChunks,
  type FileWorkspacePort,
  readFileView,
  uploadFileChunks,
} from "../src/features/files";
import { mcpValue, operationValue } from "../src/shared/lib/transport";
import type { FileWriteChunk } from "../src/features/files/model/contracts";

function unexpectedFileOperation(): never {
  throw new Error("UNEXPECTED_FILE_OPERATION");
}
function fileWorkspace(overrides: Partial<FileWorkspacePort>): FileWorkspacePort {
  return {
    info: unexpectedFileOperation,
    list: unexpectedFileOperation,
    read: unexpectedFileOperation,
    hash: unexpectedFileOperation,
    write: unexpectedFileOperation,
    ...overrides,
  };
}
function fileInformation(size: number) {
  return {
    path: "file",
    name: "file",
    type: "file",
    size_bytes: size,
    modified_at_ns: 0,
  } satisfies Awaited<ReturnType<FileWorkspacePort["info"]>>;
}
function fileChunk() {
  return {
    path: "file",
    offset: 0,
    bytes_read: 1,
    next_offset: 1,
    size_bytes: 1,
    eof: true,
    bytes: new Uint8Array([0]),
  };
}

describe("shared MCP result boundary", () => {
  it("unwraps structured results and JSON content without depending on a browser", () => {
    expect(
      mcpValue({ structuredContent: { result: { result: { pages: [] } } } }, browserInventory),
    ).toEqual({
      pages: [],
      canReopen: false,
    });
    expect(
      mcpValue(
        {
          content: [
            { type: "text", text: "description" },
            { type: "text", text: '{"pages":[]}' },
          ],
        },
        browserInventory,
      ),
    ).toEqual({ pages: [], canReopen: false });
    expect(() =>
      mcpValue(
        { isError: true, content: [null, { type: "text", text: "permission denied" }] },
        browserInventory,
      ),
    ).toThrow("permission denied");
    expect(() => operationValue({ state: "running" }, browserInventory)).toThrow(
      "MCP_OPERATION_INVALID",
    );
  });
  it("rejects invalid browser collections and binds previews to the selected page", () => {
    expect(() => browserInventory({ pages: [{ page_id: "p", url: 4 }] })).toThrow(
      "BROWSER_PAGE_INVALID",
    );
    expect(() =>
      browserSnapshot({
        page_id: "p",
        url: "https://example.com",
        elements: [{ text: "missing ref" }],
      }),
    ).toThrow("BROWSER_ELEMENT_INVALID");
    expect(
      browserPreview({ page_id: "other", mime_type: "image/png", data_base64: "AA==" }, "p"),
    ).toBe("");
    expect(browserPreview({ page_id: "p", mime_type: "image/png", data_base64: "AA==" }, "p")).toBe(
      "data:image/png;base64,AA==",
    );
  });
  it("validates analysis input and tools while retaining provider-owned schemas", () => {
    expect(
      analysisTools({
        tools: [
          {
            name: "read",
            inputSchema: { properties: { path: { type: "string" } }, required: ["path"] },
          },
        ],
      }),
    ).toEqual([
      {
        name: "read",
        title: undefined,
        description: undefined,
        inputProperties: ["path"],
        inputSchemaText: JSON.stringify(
          { properties: { path: { type: "string" } }, required: ["path"] },
          null,
          2,
        ),
      },
    ]);
    expect(() => analysisTools([{ name: 5 }])).toThrow("ANALYSIS_TOOL_INVALID");
    expect(() => updateAnalysisArgument("[]", "path", "file")).toThrow("MCP_RESULT_INVALID");
  });
});

describe("scope-bound file transfers", () => {
  it("never publishes a preview after scope changes during its metadata check", async () => {
    let current = true;
    const call = fileWorkspace({
      read: async () => fileChunk(),
      info: async () => {
        current = false;
        return fileInformation(1);
      },
    });
    expect(await readFileView("file_read", "file", call, () => current)).toBeNull();
  });
  it("does not download beyond the bounded UI transfer size", async () => {
    let reads = 0;
    const call = fileWorkspace({
      info: async () => {
        reads++;
        return fileInformation(64 * 1024 * 1024 + 1);
      },
    });
    await expect(downloadFileChunks("large", call, () => true)).rejects.toThrow("64 MiB");
    expect(reads).toBe(1);
  });
  it("stops a transfer after an in-flight chunk when the workspace changes", async () => {
    let current = true,
      reads = 0;
    const call = fileWorkspace({
      info: async () => fileInformation(24000),
      read: async () => {
        reads++;
        current = false;
        return fileChunk();
      },
    });
    expect(await downloadFileChunks("file", call, () => current)).toBeNull();
    expect(reads).toBe(1);
  });
  it("preserves chunk offsets and sends a truncating write for an empty file", async () => {
    const commands: FileWriteChunk[] = [];
    const call = fileWorkspace({
      write: async (args) => {
        commands.push(args);
        return {
          path: args.path,
          bytes_written: args.bytes.length,
          next_offset: args.offset + args.bytes.length,
          size_bytes: args.offset + args.bytes.length,
        };
      },
    });
    expect(await uploadFileChunks("empty", new Uint8Array(), call, () => true)).toBe(true);
    expect(commands).toEqual([
      { path: "empty", bytes: new Uint8Array(), offset: 0, truncate: true, create_parents: true },
    ]);
    commands.length = 0;
    expect(await uploadFileChunks("data", new Uint8Array(12289), call, () => true)).toBe(true);
    expect(commands.map((command) => [command.offset, command.truncate])).toEqual([
      [0, true],
      [12288, false],
    ]);
  });
});

describe("analysis polling scope", () => {
  it("does not query an old operation after the identity changes while waiting", async () => {
    let current = true,
      polls = 0;
    const result = await completeAnalysisOperation(
      { operation_id: "op", tool: "read", state: "running" },
      {
        current: () => current,
        wait: async () => {
          current = false;
        },
        progress: () => {},
        poll: async () => {
          polls++;
          return { operation_id: "op", tool: "read", state: "completed", result: "done" };
        },
      },
    );
    expect(result).toBeNull();
    expect(polls).toBe(0);
  });
});
