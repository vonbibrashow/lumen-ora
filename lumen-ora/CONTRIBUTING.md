# Contributing to Lumen Ora

Thank you for your interest in contributing. This document explains how the project works and how to get involved effectively.

Lumen Ora is a pre-alpha project. That means some processes described here are aspirational — we are building the governance and contribution infrastructure alongside the software. If something in this document is wrong or missing, opening an issue to fix it is itself a valuable contribution.

---

## Table of Contents

1. [Before You Start](#before-you-start)
2. [Contribution Tracks](#contribution-tracks)
3. [Development Environment Setup](#development-environment-setup)
4. [Opening Issues](#opening-issues)
5. [Submitting Pull Requests](#submitting-pull-requests)
6. [Code Standards](#code-standards)
7. [The Policy Layer: Special Rules](#the-policy-layer-special-rules)
8. [Documentation Contributions](#documentation-contributions)
9. [Model and Behavior Contributions](#model-and-behavior-contributions)
10. [Community Standards](#community-standards)

---

## Before You Start

**Open an issue before starting significant work.** "Significant" means anything that will take more than a few hours or that changes an API, architecture decision, or policy rule. This is not bureaucracy — it prevents you from spending days on something that conflicts with a pending design decision, or that duplicates work already in progress elsewhere.

The issue does not need to be a formal proposal. A short description of what you want to do and why is enough to start a conversation.

**Read the architecture documentation first.** The decisions made in `docs/architecture/` are foundational. Pull requests that contradict those decisions without a corresponding architecture discussion will not be merged.

**Be specific about your hardware.** Many bugs and performance issues are hardware-specific. When reporting problems or testing changes, always include: CPU/SoC model, RAM size and type (e.g., LPDDR5x 16 GB), OS and kernel version, and the model name, size, and quantization format (e.g., Qwen2.5-14B-Q4_K_M).

---

## Contribution Tracks

Lumen Ora has two main contribution tracks. They are relatively independent during the prototype phase but converge at the Policy Layer.

### Track 1: OS and Systems Engineering

This track covers everything below the AI Orchestration Layer: the seL4 microkernel configuration and integration, Genode component development, the Policy Layer daemon, device drivers, the compatibility environment for Linux applications, and the minimal compositor.

**Skills needed:**
- C, C++, Rust (Rust is preferred for new Policy Layer code)
- Familiarity with OS internals: capability-based security, IPC, memory management
- For seL4 work: comfort reading the seL4 Reference Manual and understanding capability theory
- For Genode work: familiarity with Genode's component model (the Genode Foundations book at genodians.org is the best starting point)
- For formal methods work: Isabelle/HOL, TLA+, or Alloy

**Current open areas:**
- Policy Layer capability model: formal specification of the 10 starter rules
- Genode component scaffolding for the inference bridge
- seL4 capability grant/revoke protocol design

**Good first issues:** Look for issues tagged `good-first-issue` and `os-layer`.

### Track 2: AI Model and Behavior Engineering

This track covers the inference runtime integration, tool call schema design, prompt engineering, session memory architecture, model routing, and behavior evaluation.

**Skills needed:**
- Python, with some Rust for performance-critical components
- Experience with llama.cpp (building from source, understanding GGUF formats)
- Understanding of quantization formats (K-quants, imatrix, EXL2)
- Experience designing structured output schemas for language models
- Experience evaluating model behavior against defined criteria

**Current open areas:**
- Tool call JSON Schema with security-relevant constraints (path traversal prevention, etc.)
- Latency benchmarking across hardware targets
- Behavior evaluation harness design
- Model routing logic (when to use the small model vs. the large model)

**Good first issues:** Look for issues tagged `good-first-issue` and `inference`.

---

## Development Environment Setup

See the `docs/dev-setup/` directory for environment setup guides:

- `docs/dev-setup/genode.md` — Genode/seL4 development (Linux host required)
- `docs/dev-setup/inference.md` — Inference layer development (Linux, macOS, or Windows with WSL2)
- `docs/dev-setup/windows.md` — Full WSL2-based setup for Windows contributors

The inference development environment is the easier starting point. It works on any machine with 16 GB of RAM and does not require the full OS stack.

---

## Opening Issues

Use the issue templates in `.github/ISSUE_TEMPLATE/`:

- **Bug report** — for things that are broken
- **Feature request** — for things you want to add
- **Model RFC** — for proposing changes to model behavior, the tool call schema, or the Policy Layer rules

A few things that make issues more useful:

- **For bugs:** Include the exact command or action, the expected behavior, the actual behavior, your hardware/software configuration, and any relevant log output.
- **For feature requests:** Explain the user-facing problem you are solving, not just the implementation you want. "Add a flag to disable audit logging" is less useful than "When running automated tests, the audit log fills up with noise that makes debugging harder — I need a way to suppress it in test environments."
- **For Policy Layer changes:** These require the Model RFC template. See the template for details.

---

## Submitting Pull Requests

1. **Fork the repository** and create a branch with a descriptive name (`policy/add-network-egress-rule`, `inference/llama-cpp-v0.8-compat`, `docs/genode-setup-fix`).

2. **Keep changes focused.** A PR that adds a feature and also reformats code and also fixes two unrelated bugs is hard to review. Split things up.

3. **Write a meaningful PR description.** Use the PR template. Explain what changed and why. If your PR closes an issue, link it (`Closes #42`).

4. **Add tests.** Code changes without tests require a documented rationale in the PR description for why tests are not applicable. "I didn't have time" is not a rationale.

5. **Update documentation** if your change affects the architecture, the tool call schema, the Policy Layer rules, or the development environment setup.

6. **Policy Layer changes require two maintainer reviews.** See below.

7. **Sign your commits.** We require GPG-signed commits for any changes to the Policy Layer. For other components, signed commits are strongly encouraged but not yet mandatory.

### Review timeline

We aim to provide initial review within 7 days. If your PR has been open for more than 14 days without any response, ping the relevant maintainer (see GOVERNANCE.md for the current list) in the PR comments.

---

## Code Standards

### Rust (Policy Layer and Inference Bridge)
- Use `cargo fmt` and `cargo clippy` before submitting. CI will check both.
- Avoid `unwrap()` in paths that handle user input or untrusted data. Use `?` or explicit error handling.
- Safety-critical code (anything in the Policy Layer that enforces a rule) requires a comment explaining the invariant being maintained.
- Prefer `thiserror` for error types in library code and `anyhow` in binary code.

### C/C++ (Genode components, seL4 integration)
- Follow Genode's coding style (documented at genodians.org).
- No dynamic allocation in kernel-adjacent code. Prefer static allocation with bounded sizes.
- Use Genode's `Constructible<>` and arena allocators rather than `new`/`delete`.

### Python (inference tooling, evaluation harness)
- Python 3.11 or later.
- Type annotations on all public functions.
- Use `ruff` for linting and formatting.
- No `subprocess.shell=True` in code that processes user input.

### General
- No hard-coded paths, credentials, or configuration values. Use environment variables or configuration files.
- No telemetry, analytics, or network calls that are not documented and user-visible.
- Commit messages: imperative mood, under 72 characters for the first line. Body explains the "why."

---

## The Policy Layer: Special Rules

The Policy Layer is the component that determines what the AI is allowed to do. It is the most security-critical component in the system. Changes to it have special requirements.

**Two maintainer reviews are required.** At least one of the reviewers must be a member of the Safety Subcommittee (see GOVERNANCE.md).

**Policy rules must be formally specified.** Every rule in the Policy Engine must have a corresponding TLA+ specification. The specification does not need to be machine-checked before the first prototype, but it must be written. This is not optional.

**Audit log format is stable.** Once the audit log format is defined (in `docs/inference/tool-schema.md`), it is treated as a stable API. Changes to the format require a deprecation period and version bumping.

**No silent failures.** The Policy Layer must either grant a capability, deny it with a logged reason, or enter a safe error state. It must never silently grant capabilities or fail open.

**Test coverage requirement.** Every policy rule must have at least one test case that confirms the rule correctly denies a prohibited action and at least one test case that confirms the rule correctly permits a permitted action.

---

## Documentation Contributions

Documentation contributions are valuable and do not require the same process as code changes. However:

- Factual corrections (fixing wrong information) can be PRed directly.
- Significant additions to architecture documentation should be discussed in an issue first, especially if they contradict or extend existing design decisions.
- The `docs/` directory is the authoritative source. Do not add documentation in wiki pages, external documents, or PR descriptions that should be in `docs/`.

---

## Model and Behavior Contributions

Changes to how the model behaves — prompt structure, tool call schema, routing logic, default Policy rules — require the Model RFC process. See GOVERNANCE.md for the full RFC process and `.github/ISSUE_TEMPLATE/model_rfc.md` for the template.

The Model RFC process exists because behavioral changes to an AI-native OS can have subtle and non-obvious effects. A change that looks like a UX improvement might introduce a security regression or change the system's behavior in ways that users who relied on the old behavior find disruptive.

---

## Community Standards

Lumen Ora follows a simple code of conduct: treat other contributors as professionals. Specific expectations:

- Technical disagreements should be resolved with evidence and argument, not social pressure or volume.
- Criticism of code, designs, and ideas is welcome. Criticism of people is not.
- If you are frustrated with a review or a decision, state your disagreement clearly and explain your reasoning. Escalation paths are documented in GOVERNANCE.md.
- Off-topic discussions, self-promotion, and spam are not welcome in issue threads or pull request comments.

Violations of these standards should be reported to `conduct@lumenos.org`. The Steering Council is responsible for enforcement (see GOVERNANCE.md).

---

Questions? Open an issue or post in GitHub Discussions. We prefer written, asynchronous communication over chat — it creates a searchable record and is more accessible across time zones.
