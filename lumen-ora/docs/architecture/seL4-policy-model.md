# seL4 Capability Model and Policy Layer Specification

This document specifies the capability model that governs what the AI Orchestration Layer is permitted to do, how capabilities are granted and revoked, and how the Policy Layer enforces these grants.

This is a living specification. The current status of formal verification for each section is noted inline. Sections marked `[SPECIFIED, UNVERIFIED]` have a TLA+ specification written but not yet machine-checked. Sections marked `[DRAFT]` have a written specification but it has not been reviewed by the Safety Subcommittee yet.

---

## 1. Foundational Concepts

### 1.1 The seL4 Capability System

An seL4 capability is a hardware-enforced, unforgeable token that grants its holder a specific right to invoke a specific kernel object. "Unforgeable" here has a precise meaning: the seL4 kernel's formal verification proves that no sequence of valid kernel API calls can produce a capability the caller was not explicitly given.

Relevant seL4 capability types for Lumen Ora:

| Capability Type | What It Grants |
|-----------------|----------------|
| `CNode` capability | Right to read/write a specific slot in a capability table |
| `Endpoint` capability | Right to send/receive on a specific IPC endpoint |
| `Frame` capability | Right to map a specific physical memory frame into an address space |
| `TCB` capability | Right to control a specific thread control block |
| `IRQ Handler` capability | Right to receive interrupts from a specific interrupt line |

The Policy Layer holds capabilities to the Genode services (filesystem, network, process manager) and mediates access to them for the AI layer. The AI layer holds capabilities only to the Policy Layer endpoint, not to OS services directly.

### 1.2 The Genode RPC Layer

Genode's component communication is built on seL4 IPC but provides a higher-level RPC interface. Genode sessions abstract seL4 capabilities into service-level objects: a `File_system::Session` is a capability bundle that allows the holder to open, read, write, and close files on a specific file system, within the session's constraints.

The Policy Layer manages Genode sessions on behalf of the AI layer. It opens sessions with OS services under its own identity and forwards requests from the AI layer through those sessions, applying policy checks before each request.

### 1.3 Policy Layer Position

```
AI Orchestration Layer
         │
         │  JSON-RPC (tool call requests)
         ▼
Policy Engine Daemon   ←→   Audit Log (append-only)
         │
         │  Genode RPC / seL4 IPC
         ▼
OS Services (File System, Network, Process Manager, etc.)
         │
         ▼
seL4 Microkernel (enforces capability model at hardware boundary)
```

The Policy Engine Daemon is the only component that:
1. Holds capabilities to OS services
2. Is permitted to create new capabilities for the AI layer
3. Writes to the audit log

No other component in the AI layer can bypass this position, because the seL4 kernel enforces that capabilities cannot be forged.

---

## 2. Capability Taxonomy

Lumen Ora defines six capability classes. Each class covers a family of related system resources.

### 2.1 FileSystem Capabilities

```
fs:<scope>:<permissions>:<constraints>
```

**Scope:** A directory path or path pattern that defines the resource boundary.
**Permissions:** One or more of `read`, `write`, `create`, `delete`, `list`.
**Constraints:** Additional restrictions on the capability (e.g., `max-file-size-mb:100`, `no-executable`).

Examples:
```
fs:/home/user/Documents:read,write,create:max-file-size-mb:100
fs:/home/user:read,list:
fs:/tmp/lumen-scratch:read,write,create,delete:ttl-hours:24
```

**Invariants:**
- A `write` capability on a path does not imply a `read` capability on the same path (though a read capability is usually granted alongside write).
- A `delete` capability on a path does not imply `delete` on its parent directory.
- Path traversal is prevented at the capability level: a capability for `/home/user/Documents` cannot be used to access `/home/user/Documents/../../etc/passwd`. The Policy Layer validates all paths against the capability's scope before forwarding the request.
- `[SPECIFIED, UNVERIFIED]` The path validation logic is formally specified in `spec/policy/fs-path-validation.tla`.

### 2.2 Network Capabilities

```
net:<direction>:<scope>:<constraints>
```

**Direction:** `egress` (outbound connections), `ingress` (inbound listening), `dns` (name resolution only).
**Scope:** Domain pattern, IP range, or port specification.
**Constraints:** `max-bytes-per-session:N`, `no-tls` (block unencrypted connections), `allowed-ports:80,443`.

Examples:
```
net:egress:*.example.com:allowed-ports:443
net:dns::
net:egress:*:allowed-ports:443,80:max-bytes-per-session:10485760
```

**Invariants:**
- Capabilities are per-session unless explicitly marked `persistent`.
- DNS capability does not imply the ability to make TCP/UDP connections to the resolved address.
- The Policy Layer does not inspect TLS payload content (that would require MITM); it enforces at the connection establishment level.

### 2.3 Process Capabilities

```
proc:<type>:<scope>:<constraints>
```

**Type:** `spawn` (launch a new process), `signal` (send a signal to a running process), `query` (read process metadata — PID, resource usage).
**Scope:** For `spawn`: path pattern for the executable. For `signal`: PID or process group.
**Constraints:** `resource-limit-cpu-pct:N`, `resource-limit-mem-mb:N`, `no-network` (spawn without network capability), `max-runtime-seconds:N`.

Examples:
```
proc:spawn:/usr/bin/git:no-network:max-runtime-seconds:300
proc:spawn:/home/user/.local/bin/*::
proc:query:*::
proc:signal:<pid>:SIGTERM,SIGKILL:
```

**Invariants:**
- Spawned processes do not inherit the AI layer's capabilities. They run with only the capabilities explicitly granted to them at spawn time.
- A `spawn` capability does not imply the ability to spawn processes with more privileges than the Policy Layer itself holds.
- `proc:signal` is restricted to the signals listed; the Policy Layer validates the signal before forwarding.

### 2.4 Device Capabilities

```
dev:<device>:<permissions>
```

**Device:** NPU, GPU, camera, microphone, speakers, USB, Bluetooth, TPM.
**Permissions:** `use`, `exclusive` (prevent other components from using the device simultaneously).

Examples:
```
dev:npu:use
dev:microphone:use
dev:camera:use
dev:tpm:use
```

**Invariants:**
- The NPU is allocated to the inference runtime on boot and is not available for other tool calls. This is enforced at the Genode driver level.
- `exclusive` capabilities are revoked when the session ends unless the user has explicitly granted persistent exclusive access.
- Camera and microphone capabilities require explicit, per-session user confirmation. They cannot be granted silently.

### 2.5 User Interaction Capabilities

```
ui:<type>:<scope>
```

**Type:** `notify` (push a notification to the user), `prompt` (ask the user a yes/no question), `display` (render content to the framebuffer).
**Scope:** Content type restrictions.

Examples:
```
ui:notify:text-only
ui:prompt::
ui:display:text-only
```

**Invariants:**
- The AI cannot render arbitrary HTML or executable content via `ui:display`. Only plain text and the defined output format are supported.
- `ui:prompt` blocks the AI's execution thread until the user responds.

### 2.6 Memory and Persistence Capabilities

```
mem:<type>:<scope>:<constraints>
```

**Type:** `session-kv` (key-value store, cleared at session end), `persistent-kv` (key-value store, survives sessions), `session-db` (structured SQLite-like store).
**Scope:** Key prefix or namespace.
**Constraints:** `max-size-kb:N`.

Examples:
```
mem:session-kv:scratchpad:max-size-kb:1024
mem:persistent-kv:user-preferences:max-size-kb:512
```

---

## 3. Policy Rules — Starter Set

The Policy Layer ships with 10 default rules that apply to all sessions unless the user explicitly modifies them. These rules are the baseline safety envelope.

Each rule is specified in a structured format: a human-readable description, a formal TLA+ predicate, the default setting, and the override mechanism.

### Rule 1: No Silent File Writes Outside Scoped Paths

**Description:** The AI may only write to filesystem paths that are within explicitly granted `fs:*:write` capability scopes for the current session. Writes to paths outside the scope are denied with an audit log entry, not silently redirected.

**Formal predicate (TLA+):**
```tla+
RULE_NoSilentWriteOutsideScope ==
  \A req \in ToolCallRequests :
    req.type = "fs_write" =>
      (\E cap \in ActiveCapabilities :
        cap.class = "fs" /\
        IsSubpath(req.path, cap.scope) /\
        "write" \in cap.permissions)
      \/ DenyWithLog(req, "fs_write_out_of_scope")
```
`[DRAFT]`

**Default:** ON
**User override:** The user can expand the write scope by granting a broader `fs:` capability, but cannot disable the rule itself.

### Rule 2: Path Traversal Prevention

**Description:** Any filesystem path provided in a tool call that, after normalization (Unicode normalization, symlink resolution, `..` component resolution), escapes the capability's scope is denied.

**Default:** ON
**User override:** Not overridable. This is a hardcoded invariant.

### Rule 3: Network Egress Requires Explicit Grant

**Description:** Outbound network connections are denied unless the session holds a `net:egress:*` capability. DNS-only access (`net:dns::`) does not allow TCP/UDP connections.

**Default:** ON (no network capability granted by default)
**User override:** User can grant network capabilities per-session or persistently.

### Rule 4: Process Spawn Requires Explicit Grant

**Description:** Spawning new processes is denied unless the session holds a `proc:spawn:*` capability matching the requested executable path.

**Default:** ON (no proc:spawn capability granted by default)
**User override:** User can grant spawn capabilities for specific executables.

### Rule 5: No Capability Self-Escalation

**Description:** The AI layer cannot request capabilities that exceed those the Policy Layer itself holds. The AI cannot grant itself root access, device access to hardware not allocated to it, or access to other users' home directories.

**Default:** ON (hardcoded invariant)
**User override:** Not overridable.

### Rule 6: Audit Log Is Append-Only

**Description:** The AI layer has no capability to read, modify, or delete the audit log. The audit log is written to a filesystem scope that is not within any `fs:*` capability granted to the AI.

**Default:** ON (hardcoded invariant)
**User override:** Not overridable.

### Rule 7: High-Stakes Confirmation Required

**Description:** Tool calls classified as "high-stakes" (see below) require explicit user confirmation before execution. The confirmation is mediated by the Context Shell and blocks the tool call until confirmed or denied.

**High-stakes classification:** A tool call is classified as high-stakes if it:
- Deletes a file or directory
- Spawns a process with `--rm`, `drop`, `delete`, `destroy`, or similar flags in its argument list
- Makes a network request that sends user data (POST, PUT, PATCH with a non-empty body)
- Grants or revokes capabilities
- Modifies system configuration files (any path under `/etc`, `/boot`, or equivalent)

**Default:** ON
**User override:** User can disable confirmation for specific tool call types after an explicit acknowledgment that they understand the risk.

### Rule 8: Symlink Scope Validation

**Description:** When the AI requests access to a symlink, the Policy Layer resolves the symlink and validates that the resolved path is within the capability scope. Access to symlinks that point outside the scope is denied.

**Default:** ON (hardcoded invariant)
**User override:** Not overridable.

### Rule 9: Spawn Inherits No AI Capabilities

**Description:** Processes spawned by the AI through a `proc:spawn` tool call inherit no AI layer capabilities. They run in a capability-stripped environment. If a spawned process needs filesystem or network access, it must be granted separately, explicitly, at spawn time.

**Default:** ON (hardcoded invariant)
**User override:** Not overridable. (The user can grant capabilities to a spawned process at spawn time, but this must be explicit.)

### Rule 10: Session Boundary Enforcement

**Description:** Capabilities granted in one session are not automatically carried forward to the next session. Each session begins with only the capabilities in the user's persistent capability profile. Session-specific capabilities are revoked when the session ends.

**Default:** ON
**User override:** Users can promote a session capability to their persistent profile, but this is an explicit action, not automatic.

---

## 4. Capability Lifecycle

### 4.1 Grant

Capabilities are granted through one of three paths:
1. **Profile load:** At session start, the user's persistent capability profile is loaded into the Policy Layer's capability store.
2. **In-session grant:** During a session, the user explicitly grants a capability (e.g., "yes, you can write to my Downloads folder").
3. **Rule-based auto-grant:** A Policy Layer rule automatically grants a capability based on a condition (e.g., when the user says "open a document in /tmp/scratch, the `fs:/tmp/scratch:read:` capability is auto-granted).

### 4.2 Revoke

Capabilities are revoked through:
1. **Session end:** All session-scoped capabilities are revoked.
2. **Explicit revocation:** The user says "stop accessing the network" or equivalent.
3. **Time-based expiry:** Capabilities with a TTL are revoked when the TTL expires.
4. **Rule violation:** If the AI layer makes a request that violates a hardcoded invariant (Rules 2, 5, 6, 8, 9), the specific capability involved is revoked for the remainder of the session and the event is logged.

### 4.3 Audit

Every capability grant, revocation, and use is logged to the append-only audit log. The log format is defined in `docs/inference/tool-schema.md`. The log includes:
- Timestamp (monotonic and wall clock)
- Session ID
- Tool call type and arguments (sanitized — no content of files, no message bodies)
- Policy decision (granted / denied / high-stakes-pending / confirmed / rejected)
- Rule that produced the decision
- Any capability state changes

---

## 5. Threat Model

The Policy Layer is designed to contain the following threat classes:

**Threat 1: Prompt injection via user content.** A malicious document, webpage, or other file loaded into model context attempts to inject instructions that cause the model to issue unauthorized tool calls. The Policy Layer contains this by enforcing capability checks regardless of the model's stated intent. The model cannot claim a capability it does not hold.

**Threat 2: Model misbehavior.** The model, due to fine-tuning, adversarial inputs, or emergent behavior, attempts to exceed its intended scope. Same containment: capability enforcement is independent of the model's output.

**Threat 3: Policy Layer compromise.** A vulnerability in the Policy Engine Daemon itself. Containment: the Policy Engine Daemon runs as a Genode component. Even if it is compromised, it is isolated from other OS components by Genode's component model. Its capabilities are limited to what it needs to enforce policy. A compromised Policy Layer is a serious incident (the capabilities it holds are broad), which is why it has the most stringent review requirements.

**Threat 4: seL4 vulnerability.** A bug in the formally verified seL4 kernel. The formal verification substantially reduces this risk, but verification can have assumption violations (incorrect model of hardware, incorrect formal specification). Lumen Ora cannot eliminate this risk; it can only note that seL4's TCB is the smallest available and its verification is the strongest available for a production-grade microkernel.

**Out of scope:** Physical access attacks, side-channel attacks on inference, and social engineering of the user.

---

## 6. Formal Specification Status

| Component | Specification Language | Status |
|-----------|----------------------|--------|
| FileSystem capability path validation | TLA+ | DRAFT |
| Network capability scope matching | TLA+ | NOT STARTED |
| Capability grant/revoke lifecycle | TLA+ | NOT STARTED |
| Audit log append invariant | TLA+ | NOT STARTED |
| Rule evaluation order and interaction | TLA+ | NOT STARTED |
| Session boundary enforcement | TLA+ | NOT STARTED |

Contributions to the formal specification are welcome. See `CONTRIBUTING.md` for requirements. If you have experience with Isabelle/HOL, we would also welcome a parallel mechanized proof of the Policy Layer's core invariants.

---

*Specification maintained by the Safety Subcommittee. Last updated: 2026-05-19*
