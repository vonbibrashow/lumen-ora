# Architecture Overview

This document describes the layer architecture of Lumen Ora, the rationale for each layer, and how the layers interact. It is the starting point for understanding the system.

For deeper dives, see:
- `seL4-policy-model.md` — the capability model and formal specification of the Policy Layer
- `ai-orchestration.md` — the inference layer design and tool call routing

---

## The Core Premise

Every design decision in Lumen Ora flows from one central argument: **the graphical shell is not fundamental to an operating system; it is one historically-dominant choice of interface.** Replace the graphical shell with a language model operating through a structured tool call interface, and the constraints that have shaped OS design for 40 years dissolve.

The consequences are significant:
- A compositor, window manager, and application framework are no longer needed. The AI is the application manager.
- The system does not need to arbitrate between competing GUI applications. It arbitrates between tool calls.
- Security policy can be expressed as capability grants to the AI layer, which is a cleaner model than discretionary access control or even mandatory access control as traditionally implemented — because the policy is applied at the point where the AI makes requests, not dispersed across the filesystem.

This is the premise. The architecture exists to realize it safely.

---

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                   User (voice / text input)                          │
│           via Context Shell (PTY) or audio pipeline                  │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ natural language / voice
┌─────────────────────────▼───────────────────────────────────────────┐
│                  AI Orchestration Layer                               │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────────┐ │
│  │  Inference      │  │  Tool Call       │  │  Session Memory     │ │
│  │  Runtime        │  │  Router          │  │  Manager            │ │
│  │  (llama.cpp)    │  │  (JSON-RPC)      │  │  (context window    │ │
│  │                 │  │                  │  │   + persistent DB)  │ │
│  └─────────────────┘  └──────────────────┘  └─────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Model Router: small model (fast) ←→ large model (reasoning)   │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ tool call requests (JSON-RPC)
┌─────────────────────────▼───────────────────────────────────────────┐
│                      Policy Layer                                     │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────────┐ │
│  │  Policy Engine  │  │  Capability      │  │  Audit Log          │ │
│  │  Daemon         │  │  Store           │  │  (append-only)      │ │
│  │  (Rust)         │  │  (granted caps)  │  │                     │ │
│  └─────────────────┘  └──────────────────┘  └─────────────────────┘ │
│                                                                       │
│  "What the AI is allowed to do, when, and with what resources"       │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ IPC (seL4 capabilities / Genode RPC)
┌─────────────────────────▼───────────────────────────────────────────┐
│                   Genode Framework                                    │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────────────┐│
│  │  File System │  │  Network Stack  │  │  Legacy Linux Compat     ││
│  │  Component   │  │  Component      │  │  (Sculpt-style VFS +     ││
│  │              │  │                 │  │   Linux kernel port)     ││
│  └──────────────┘  └─────────────────┘  └──────────────────────────┘│
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────────────┐│
│  │  Driver      │  │  Minimal        │  │  Process Manager         ││
│  │  Components  │  │  Compositor     │  │  Component               ││
│  │              │  │  (framebuffer)  │  │                          ││
│  └──────────────┘  └─────────────────┘  └──────────────────────────┘│
└─────────────────────────┬───────────────────────────────────────────┘
                          │ seL4 IPC / capability invocations
┌─────────────────────────▼───────────────────────────────────────────┐
│                      seL4 Microkernel                                 │
│  Formally verified · Capability-based IPC · Hardware enforcement     │
│  Trusted Computing Base: ~10,000 lines of C · Machine-checked proofs │
└─────────────────────────┬───────────────────────────────────────────┘
                          │
              Physical hardware (x86-64 / ARM64 / NPU)
```

---

## Layer Descriptions

### seL4 Microkernel

seL4 is the foundation. It provides two things that nothing else provides:

1. **Formal verification.** The seL4 microkernel has been formally proven correct down to the binary level for the ARM and RISC-V implementations. Its C implementation is proven to match its abstract mathematical specification. This is not "we have tests" — it is machine-checked proof. The kernel cannot be made to violate its capability model by any input, including crafted IPC messages or buggy userspace code.

2. **Capability-based IPC.** Every interaction between Genode components, and between the Policy Layer and the OS, goes through seL4 capabilities. A capability is an unforgeable token that grants the holder a specific right to a specific kernel object. If the Policy Layer does not hold a capability, it cannot pass one to the AI layer. If the AI layer does not hold a capability, it cannot invoke the corresponding system resource. The kernel enforces this at the hardware level.

The seL4 Trusted Computing Base is approximately 10,000 lines of C. This is the smallest kernel that can claim formal verification of a useful feature set.

**Why seL4 and not a conventional microkernel?** Conventional microkernels (L4, QNX, Zircon) provide process isolation but do not provide formal verification. In a system where an AI's tool calls are the primary path to system resources, "we have isolation and it's probably correct" is insufficient. We need "we have isolation and we have a mathematical proof that it is correct."

### Genode Framework

Genode provides what seL4 does not: a usable OS personality. seL4 is a microkernel — it provides IPC, capabilities, and scheduler, and nothing else. Genode runs on top of seL4 and provides device drivers, file systems, network stacks, and the software component model that makes a real system.

Key Genode concepts relevant to Lumen Ora:

- **Component model.** Every OS service runs as an isolated component. The file system is a component. The network stack is a component. The GPU driver is a component. They communicate only through Genode RPC (built on seL4 IPC). A bug in one component cannot corrupt another.
- **No ambient authority.** Components only have the capabilities they are explicitly given when they are started. There is no concept of "root" or a process that can access everything.
- **Sculpt compatibility.** Genode's Sculpt architecture provides a Linux binary compatibility environment: a virtual file system and a ported Linux kernel running as a Genode component, able to run unmodified Linux ELF binaries. This is how legacy applications run on Lumen Ora.

The minimal compositor in Genode uses a direct framebuffer rendering approach. It holds approximately 25–60 MB of GPU memory. It renders text output and one optional legacy application surface. It does not implement a compositing window manager.

### Policy Layer

The Policy Layer is the most architecturally novel component of Lumen Ora and the one with the most security significance.

Its job: sit between the AI Orchestration Layer's tool call requests and the Genode components that fulfill them. Evaluate every request against a set of rules. Grant or deny. Log everything.

**Why a separate layer?** One could imagine building policy rules into the AI model itself (via fine-tuning) or building them into the Genode components (access controls on individual services). Both approaches have problems.

Policy-in-model is not auditable. You cannot inspect what rules a model will apply to a novel input. You cannot formally verify it. You cannot update it without retraining.

Policy-in-components is dispersed. Access controls on individual Genode components are the right approach for preventing compromised components from exceeding their authority, but they do not provide a unified view of "what has the AI done and what is it allowed to do." You want a single enforcement point.

The Policy Layer is that enforcement point. It has a formal specification (TLA+) for its rule evaluation semantics. It writes an append-only audit log. It is audited by two maintainers including one Safety Subcommittee member for any change. It is the one component whose correctness must be trusted above all others (aside from seL4 itself).

See `seL4-policy-model.md` for the formal specification.

### AI Orchestration Layer

The inference runtime (llama.cpp) runs here. This layer takes natural language input, converts it to model input via the system prompt, runs inference, parses the model's response for tool calls, forwards tool calls to the Policy Layer, receives results, and generates output.

Three sub-components:

**Inference Runtime:** llama.cpp, compiled with the appropriate backend for the target hardware (CUDA for NVIDIA GPUs, Metal for Apple Silicon, Vulkan for cross-platform GPU, BLAS for CPU-only). The runtime is responsible for loading the model, managing the KV cache, and performing inference. It exposes a JSON-RPC interface to the Tool Call Router.

**Tool Call Router:** Receives tool call requests from the model's structured output, validates them against the JSON Schema definitions in `docs/inference/tool-schema.md`, forwards valid requests to the Policy Layer daemon via IPC, and receives results. The router is the boundary between inference and policy.

**Session Memory Manager:** Manages the model's context window and a persistent database of session summaries. When a context window is about to overflow, the manager summarizes older context and writes it to the database. When a new session starts, the manager loads relevant summaries. This is what gives the system the appearance of persistent memory across sessions.

See `ai-orchestration.md` for the detailed design of this layer.

### Context Shell

The Context Shell is the user-facing component. It is a PTY-intercepting terminal wrapper that sits between the user's terminal and the AI layer. In the final Lumen Ora architecture, it is replaced by a voice/text input component with its own hardware interface. In the prototype, it is a terminal application.

The Context Shell handles:
- User input collection (text, with voice transcription in later milestones)
- Display of model output (streaming, with formatting)
- High-stakes command detection (surfacing when the AI is about to do something potentially destructive)
- Session management (start, save, resume, end)

---

## Key Design Decisions and Their Rationale

### Decision 1: Why seL4 instead of Linux kernel hardening?

The threat model for Lumen Ora is different from a conventional OS. The AI layer, by design, has broad access to system capabilities — broader than a typical application. If the AI layer is compromised (via adversarial inputs, prompt injection, or model misbehavior), the blast radius must be contained.

Linux kernel hardening (namespaces, seccomp, SELinux, AppArmor) reduces the blast radius but does not bound it formally. seL4's formal verification provides a hard, proven bound: the AI can only do what its capabilities allow, and the kernel cannot be made to grant it more. This is the right foundation for a system that runs AI tool calls as a primary interface.

### Decision 2: Why Genode instead of a conventional Linux userspace?

We need the Sculpt-style component isolation for the same reason we need seL4. A compromised OS component should not be able to affect other components. Genode's component model provides this. A conventional Linux userspace does not — shared libraries, the filesystem, signals, and many other mechanisms create covert channels between processes.

The practical cost of Genode is a higher implementation effort and a less familiar programming model. The benefit is that every OS service is isolated by construction.

### Decision 3: Why not run the AI model inside the seL4/Genode system?

In the target architecture, the inference runtime runs as a Genode component. In the 90-day prototype, it runs as a Linux userspace process, because setting up llama.cpp inside Genode is a significant porting effort that would delay the prototype milestone without providing proof-of-concept value.

### Decision 4: Why is the Policy Layer in userspace and not the kernel?

The Policy Layer is complex. Kernel code must be minimal. The seL4 kernel is formally verified; adding policy enforcement to the kernel would invalidate the verification and massively increase the TCB.

The Policy Layer runs as a Genode component with privileged access to the capability store. It is isolated from the AI layer by the Genode component model and from the OS components it mediates by seL4 capabilities. This provides strong isolation without requiring the Policy Layer to be kernel code.

### Decision 5: Why Rust for the Policy Layer?

Memory safety without garbage collection. The Policy Layer is performance-sensitive (it is in the critical path of every tool call) and security-critical (a vulnerability in the Policy Layer is a P0 incident). Rust provides memory safety guarantees at the type level, without the runtime unpredictability of a garbage collector. C or C++ would also work but require more careful auditing for memory safety. Go, Python, or similar are ruled out for the performance-sensitive and GC reasons.

---

## Resource Overhead Comparison

See `docs/resource-analysis.md` for the full numbers. Summary:

| Component | Lumen Ora | Windows 11 OEM | macOS 15 | Ubuntu 24.04 LTS |
|-----------|-----------|----------------|----------|------------------|
| Base RAM at idle | 200–400 MB | 5,000–7,000 MB | 3,000–5,000 MB | 800–1,500 MB |
| GPU memory (compositor) | 25–60 MB | 300–600 MB | 250–900 MB | 100–400 MB |
| Background processes | ~15 | 150+ | 100+ | 60+ |

The 4–6 GB difference between Lumen Ora and Windows 11 is not cosmetic. On a 16 GB machine, it is the difference between being able to run Qwen2.5-14B at interactive speed (requires ~10 GB) and being limited to a 7B model.

---

## What This Architecture Does Not Solve

Be honest about limitations:

1. **Hardware bring-up is hard.** seL4 and Genode support is limited compared to Linux. Bring-up for new hardware requires porting drivers, which is skilled, time-consuming work. This is a real barrier to the breadth of hardware we can support.

2. **The AI layer is not formally verified.** seL4 is. Genode's isolation properties are strong. The Policy Layer will be formally specified. But the AI model itself — the part that decides what tool calls to make — is a neural network, not a verified program. We are betting heavily on the Policy Layer to catch misbehavior, not on the model to always behave correctly.

3. **Legacy application compatibility is limited.** The Sculpt-style compatibility environment runs unmodified Linux ELF binaries, but not all of them, and GPU acceleration for legacy apps requires additional work. Users who depend on specific Linux applications may find them missing or degraded.

4. **The prototype is not the final architecture.** The 90-day prototype runs on NixOS, not seL4/Genode. Its security properties are prototype-level. Do not draw conclusions about the target architecture from the prototype's security posture.
