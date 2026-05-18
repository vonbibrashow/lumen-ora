# Policy Engine — Prototype Component

The Policy Engine prototype is a Rust userspace daemon that intercepts tool call requests from the AI layer and enforces the 10 starter policy rules. In the final Lumen Ora architecture, this daemon runs as a Genode component with seL4 capability enforcement at the hardware boundary. In the 90-day prototype, it runs as a Linux userspace process on NixOS.

**Important:** The prototype's security guarantees are weaker than the final architecture. The prototype Policy Engine is a process on a conventional Linux system — it can be bypassed by a sufficiently privileged process. Its purpose is to validate the rule logic, audit log format, and IPC interface, not to provide production-grade enforcement.

---

## Status

Weeks 1–4 of the build plan (see `../README.md`). Currently: scaffolding in progress.

---

## What This Component Does

1. Opens a Unix domain socket at `/run/lumen-ora/policy.sock`
2. Listens for tool call requests from the Inference Bridge
3. For each request:
   a. Checks the active capability store for the session
   b. Evaluates the request against the 10 default policy rules
   c. Returns `granted`, `denied`, or `high_stakes_pending`
   d. Writes an audit log entry regardless of decision
4. Manages capability grants and revocations (via IPC from the Context Shell)
5. Exposes a read-only status endpoint for the Context Shell to display active capabilities

---

## Source Layout

```
policy-engine/
  src/
    main.rs               -- startup, socket listener, signal handling
    ipc.rs                -- JSON-RPC message parsing and dispatch
    capability_store.rs   -- in-memory capability store with session scoping
    audit.rs              -- append-only audit log writer
    rules/
      mod.rs              -- PolicyRule trait, rule registry, evaluation loop
      rule_01_fs_scope.rs
      rule_02_path_traversal.rs
      rule_03_net_egress.rs
      rule_04_proc_spawn.rs
      rule_05_no_escalation.rs
      rule_06_audit_append_only.rs
      rule_07_high_stakes_confirm.rs
      rule_08_symlink_scope.rs
      rule_09_spawn_no_inherit.rs
      rule_10_session_boundary.rs
  tests/
    policy_rules.rs       -- integration tests for each rule (happy path + denial)
    audit_log.rs          -- audit log format and integrity tests
    ipc.rs                -- IPC message format tests
  Cargo.toml
  config.toml.example
```

---

## The PolicyRule Trait

```rust
pub trait PolicyRule: Send + Sync {
    /// Human-readable rule ID (e.g., "RULE_01_FS_SCOPE")
    fn id(&self) -> &'static str;

    /// Human-readable description of what this rule enforces
    fn description(&self) -> &'static str;

    /// Whether this rule can be overridden by user configuration
    fn overridable(&self) -> bool;

    /// Evaluate a tool call request.
    /// Returns Ok(()) if the rule permits the request,
    /// Err(DenialReason) if it should be denied.
    /// Rules that require user confirmation return Err(DenialReason::HighStakes).
    fn evaluate(
        &self,
        request: &ToolCallRequest,
        capabilities: &CapabilityStore,
        session: &Session,
    ) -> Result<(), DenialReason>;
}
```

Rules are evaluated in order (Rule 1 through Rule 10). The first denial short-circuits — subsequent rules are not evaluated. Hardcoded rules (Rules 2, 5, 6, 8, 9) run first regardless of order.

---

## Building

```bash
cd prototype/policy-engine
cargo build --release

# Or build as part of the workspace:
cd prototype
cargo build --release --workspace
```

---

## Running Standalone (Testing)

```bash
# Run with default config
./target/release/policy-engine

# Run with custom config
./target/release/policy-engine --config /path/to/config.toml

# Run with verbose logging (shows all rule evaluations)
RUST_LOG=policy_engine=debug ./target/release/policy-engine
```

---

## Testing

```bash
cargo test -p policy-engine

# Run with test output visible
cargo test -p policy-engine -- --nocapture
```

Every rule must have:
1. A test that confirms it correctly denies a prohibited action
2. A test that confirms it correctly permits a permitted action
3. At least one edge case test (e.g., path traversal attempt, capability boundary)

---

## IPC Message Format

See `../../docs/inference/tool-schema.md` for the full tool call and result schemas. The Policy Engine implements the `Policy Layer` side of that protocol.

Requests arrive on the Unix socket as newline-delimited JSON. Responses are written back as newline-delimited JSON. The `call_id` field links requests to responses.

---

## Audit Log

The audit log is written to the path configured in `config.toml` (default: `/var/log/lumen-ora/audit.log`). See `../../docs/inference/tool-schema.md` for the audit event schema.

In the prototype, the audit log is not integrity-protected (no HMAC). Integrity protection (HMAC-SHA256) is on the roadmap for Week 6.

---

## Contributing

See `../../CONTRIBUTING.md` for general contribution requirements. Additional requirements for the Policy Engine:

- Every new rule requires a TLA+ specification (even a draft). See `../../docs/architecture/seL4-policy-model.md` for the specification format.
- Policy Engine changes require two maintainer reviews.
- Do not merge changes that make any existing test fail. The test suite is the minimum safety bar.
