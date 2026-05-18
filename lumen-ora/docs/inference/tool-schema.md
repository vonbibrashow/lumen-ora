# Tool Call JSON Schema

This document is the authoritative definition of the tool call interface between the AI Orchestration Layer and the Policy Layer. It specifies:

1. The envelope format for all tool calls
2. Each tool type's schema (arguments, return types, error types)
3. The audit log event schema

**This is a stable API.** Changes to this schema require a Model RFC and a deprecation period. Consumers of the audit log format can rely on its stability.

Current schema version: `0.1` (prototype, subject to change before v1.0)

---

## Envelope Format

Every tool call produced by the model and every result returned to it uses the same envelope format.

### Tool Call (model → Policy Layer)

```json
{
  "schema_version": "0.1",
  "session_id": "sess-a1b2c3d4",
  "turn_id": "turn-42",
  "call_id": "tc-001",
  "reasoning": "The user wants me to read their resume. I have fs:read:/home/user/ capability.",
  "tool": "fs_read",
  "arguments": { ... }
}
```

Fields:
- `schema_version` (string, required): Schema version. Must be `"0.1"` for the current version.
- `session_id` (string, required): Session identifier. Assigned at session start, stable for the session lifetime.
- `turn_id` (string, required): Turn identifier. Increments with each user-AI exchange.
- `call_id` (string, required): Unique identifier for this specific tool call within the turn. Format: `tc-NNN` where NNN is a monotonically increasing integer.
- `reasoning` (string, required for write/spawn/network/device calls, optional for read calls): The model's stated reasoning for this call. Included in the audit log.
- `tool` (string, required): The tool name. Must match one of the tool names defined in this document.
- `arguments` (object, required): Tool-specific arguments. See per-tool schemas below.

### Tool Result (Policy Layer → model)

```json
{
  "schema_version": "0.1",
  "call_id": "tc-001",
  "status": "granted",
  "result": { ... },
  "policy_rule": null,
  "latency_ms": 12
}
```

Fields:
- `call_id`: Matches the call_id of the request.
- `status`: One of: `"granted"`, `"denied"`, `"high_stakes_pending"`, `"confirmed"`, `"rejected"`, `"error"`.
- `result`: Tool-specific result object. Null if status is `"denied"` or `"rejected"`.
- `policy_rule`: If status is `"denied"`, the ID of the Policy Layer rule that produced the denial. Null otherwise.
- `latency_ms`: Time from Policy Layer receipt to result, in milliseconds.

---

## Tool Definitions

### `fs_read`

Read a file or a portion of a file.

**Arguments:**
```json
{
  "path": "/home/user/Documents/resume-2025.pdf",
  "encoding": "text",
  "offset_bytes": 0,
  "max_bytes": 1048576
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Absolute path. Path traversal sequences (`..`, `//`, symlinks outside scope) are validated by the Policy Layer. |
| `encoding` | enum | no | `"text"` (UTF-8, default), `"binary"` (base64-encoded), `"lines"` (array of strings) |
| `offset_bytes` | integer | no | Byte offset to start reading from. Default 0. |
| `max_bytes` | integer | no | Maximum bytes to read. Default 65536. Hard limit: 10 MB. |

**Result:**
```json
{
  "path": "/home/user/Documents/resume-2025.pdf",
  "content": "...",
  "encoding": "text",
  "size_bytes": 4096,
  "mime_type": "application/pdf",
  "truncated": false
}
```

**Policy requirements:** Active `fs:<scope>:read` capability where `<scope>` contains the requested path.

**Security notes:** The path is normalized and validated before the read. Content is returned as-is; the model is responsible for interpreting it appropriately. PDF parsing (extracting text from binary PDF) is done by the Policy Layer using a sandboxed parser before returning the text content to the model.

---

### `fs_write`

Write content to a file. Creates the file if it does not exist (if `create` permission is held).

**Arguments:**
```json
{
  "path": "/home/user/Documents/cover-letter.txt",
  "content": "Dear Hiring Manager...",
  "encoding": "text",
  "mode": "overwrite",
  "create_parents": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Absolute path. |
| `content` | string | yes | Content to write. For binary: base64-encoded string. |
| `encoding` | enum | no | `"text"` (default), `"binary"` |
| `mode` | enum | no | `"overwrite"` (default), `"append"`, `"create_only"` (fail if file exists) |
| `create_parents` | boolean | no | Create parent directories if they don't exist. Default false. Requires `create` permission on parent path. |

**Result:**
```json
{
  "path": "/home/user/Documents/cover-letter.txt",
  "bytes_written": 1247,
  "created": false
}
```

**Policy requirements:** Active `fs:<scope>:write` capability. For new files: also `fs:<scope>:create`. For parent creation: `fs:<parent_scope>:create`.

**High-stakes classification:** Write to existing file with `mode: "overwrite"` is classified as high-stakes if the file is larger than 1 KB. (The existing content will be lost.)

---

### `fs_delete`

Delete a file or directory.

**Arguments:**
```json
{
  "path": "/tmp/lumen-scratch/work.txt",
  "recursive": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Absolute path. |
| `recursive` | boolean | no | If true, delete directory and all contents. Default false (will fail on non-empty directories). |

**Result:**
```json
{
  "path": "/tmp/lumen-scratch/work.txt",
  "deleted": true,
  "bytes_freed": 2048
}
```

**Policy requirements:** Active `fs:<scope>:delete` capability.

**High-stakes classification:** ALWAYS classified as high-stakes. Always requires user confirmation.

---

### `fs_list`

List the contents of a directory.

**Arguments:**
```json
{
  "path": "/home/user/Documents",
  "include_hidden": false,
  "max_entries": 1000,
  "pattern": "*.pdf"
}
```

**Result:**
```json
{
  "path": "/home/user/Documents",
  "entries": [
    {"name": "resume-2025.pdf", "type": "file", "size_bytes": 4096, "modified": "2025-05-13T14:22:00Z"},
    {"name": "Projects", "type": "directory", "modified": "2025-05-01T09:00:00Z"}
  ],
  "truncated": false
}
```

**Policy requirements:** Active `fs:<scope>:list` capability.

---

### `net_request`

Make an outbound HTTP/HTTPS request.

**Arguments:**
```json
{
  "url": "https://api.example.com/data",
  "method": "GET",
  "headers": {"Accept": "application/json"},
  "body": null,
  "timeout_seconds": 30,
  "follow_redirects": true,
  "max_response_bytes": 1048576
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | yes | Full URL. Must be HTTPS unless capability explicitly permits HTTP. |
| `method` | enum | yes | `"GET"`, `"POST"`, `"PUT"`, `"PATCH"`, `"DELETE"`, `"HEAD"` |
| `headers` | object | no | Request headers. `Authorization` headers are redacted in the audit log. |
| `body` | string or null | no | Request body. Required for POST/PUT/PATCH. |
| `timeout_seconds` | integer | no | Request timeout. Default 30, max 300. |
| `follow_redirects` | boolean | no | Follow HTTP redirects. Default true, max 5 redirects. |
| `max_response_bytes` | integer | no | Response size limit. Default 1 MB, max 50 MB. |

**Result:**
```json
{
  "status": 200,
  "headers": {"Content-Type": "application/json"},
  "body": "{\"data\": ...}",
  "url_final": "https://api.example.com/data",
  "bytes_received": 1024
}
```

**Policy requirements:** Active `net:egress:<scope>` capability matching the request URL.

**High-stakes classification:** All POST/PUT/PATCH/DELETE requests are high-stakes.

**Audit log:** The full URL, method, and response status are logged. Request body and response body are NOT logged by default (may contain sensitive user data). Header values are logged except `Authorization`, `Cookie`, and `Set-Cookie`.

---

### `proc_spawn`

Spawn a subprocess.

**Arguments:**
```json
{
  "executable": "/usr/bin/git",
  "arguments": ["clone", "https://github.com/example/repo", "/tmp/repo"],
  "working_directory": "/tmp",
  "environment": {"GIT_TERMINAL_PROMPT": "0"},
  "stdin": null,
  "capture_stdout": true,
  "capture_stderr": true,
  "timeout_seconds": 120,
  "resource_limits": {
    "max_cpu_pct": 50,
    "max_memory_mb": 512
  }
}
```

**Result:**
```json
{
  "pid": 12345,
  "exit_code": 0,
  "stdout": "Cloning into '/tmp/repo'...\ndone.",
  "stderr": "",
  "runtime_ms": 3420,
  "resource_usage": {
    "cpu_pct_peak": 12,
    "memory_mb_peak": 48
  }
}
```

**Policy requirements:** Active `proc:spawn:<executable>` capability matching the requested executable path.

**High-stakes classification:** Spawning any process with arguments containing strings matching: `--rm`, `drop`, `delete`, `destroy`, `format`, `wipe`, `truncate` (case-insensitive) is classified as high-stakes.

**Security:** The spawned process does not inherit any AI layer capabilities. The environment is restricted to the explicitly provided `environment` dict merged with a minimal safe environment (PATH limited to standard system paths, no AI layer environment variables).

---

### `ui_notify`

Send a notification to the user.

**Arguments:**
```json
{
  "message": "Backup completed: 2.3 GB archived.",
  "severity": "info",
  "persistent": false
}
```

**Result:**
```json
{"delivered": true}
```

**Policy requirements:** Active `ui:notify:text-only` capability.

---

### `ui_prompt`

Ask the user a question and wait for their response.

**Arguments:**
```json
{
  "question": "The Docker prune will recover approximately 11.8 GB. Proceed?",
  "options": ["yes", "no", "show me what will be deleted first"],
  "timeout_seconds": 300
}
```

**Result:**
```json
{
  "response": "yes",
  "response_time_seconds": 4
}
```

**Policy requirements:** Active `ui:prompt:` capability.

---

## Audit Log Event Schema

Every tool call, regardless of outcome, produces an audit log event. The audit log is an append-only file at `/var/log/lumen-ora/audit.log` (JSONL format — one JSON object per line).

### Event Schema

```json
{
  "schema_version": "0.1",
  "timestamp_monotonic": 1716134400000,
  "timestamp_wall": "2026-05-19T12:00:00.000Z",
  "session_id": "sess-a1b2c3d4",
  "turn_id": "turn-42",
  "call_id": "tc-001",
  "tool": "fs_read",
  "decision": "granted",
  "policy_rule_applied": null,
  "latency_policy_ms": 2,
  "latency_total_ms": 15,
  "redacted_args": {
    "path": "/home/user/Documents/resume-2025.pdf",
    "encoding": "text"
  },
  "redacted_result": {
    "size_bytes": 4096,
    "truncated": false
  }
}
```

Fields:
- `timestamp_monotonic`: Monotonic clock in milliseconds since boot. Guaranteed to be strictly increasing.
- `timestamp_wall`: Wall clock time in ISO 8601 format.
- `decision`: One of `"granted"`, `"denied"`, `"high_stakes_pending"`, `"confirmed"`, `"rejected"`, `"error"`.
- `policy_rule_applied`: If `decision` is `"denied"`, the ID of the rule that denied it.
- `redacted_args`: Tool call arguments with sensitive values redacted. See per-tool schema for what is redacted.
- `redacted_result`: Result with file content, network response bodies, and other sensitive data removed.

**What is never logged:**
- File content (only file metadata: path, size, mime type)
- Network request/response bodies
- Authorization headers
- Process stdout/stderr content (only exit code and resource usage)
- Model reasoning text
- The content of `ui_prompt` responses

**What is always logged:**
- Every tool call, every decision, every policy rule invocation
- File paths accessed (not content)
- Network URLs and HTTP methods and status codes (not bodies)
- Process executables and argument lists (not stdout/stderr)
- Session ID, turn ID, call ID
- All timing data

The audit log is designed so that a security auditor can reconstruct exactly what the AI did during a session without being able to read the user's file contents or private data.

### Audit Log Integrity

Each audit event includes a HMAC-SHA256 computed over the event JSON using a key derived from the session's private key. This allows offline verification that the audit log has not been tampered with.

The audit log rotation policy: rotate when log exceeds 100 MB, keep 30 days of rotated logs, compress rotated logs with zstd.
