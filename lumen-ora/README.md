# Lumen Ora

> *Lumen* — light, clarity. *Ora* — to speak, to petition. The OS you speak to. The OS that illuminates.

**An AI-native operating system where the AI is not a feature — it is the interface.**

---

## What This Is

Most computers today work the same way they did in 1984: you click icons, navigate folders, toggle settings buried in menus, and switch between applications that do not talk to each other. AI has been bolted on top of this — a chatbot in a sidebar, a suggestion in a search box, a copilot in a text editor. The underlying OS remains a GUI built for a mouse.

Lumen Ora is a different premise: **what if you built the operating system from scratch, knowing that the interface would be voice and text from day one?**

There are no windows to manage. No taskbar. No app store to browse. You tell the system what you want — in plain language or by voice — and the OS figures out how to do it. The AI layer is not running on top of the OS. It *is* the OS's primary interface layer, with direct access to hardware, memory, the file system, and running processes. Legacy Linux software runs inside isolated compatibility containers, accessible the same way everything else is: by asking.

This is not a voice assistant. It is not a terminal with autocomplete. It is a full operating system, redesigned around the assumption that local AI inference is fast enough to be the primary UX primitive — and that traditional OS overhead is the main thing standing in the way of that being true.

---

## Why It Is Different

Every mainstream OS treats the graphical shell — the compositor, the window manager, the file manager, the notification center — as infrastructure too fundamental to question. These components consume 2–7 GB of RAM and hundreds of megabytes of GPU memory before you open a single application. On a machine with 16 GB of RAM and a capable NPU, that overhead is not neutral: it is directly subtracting from the memory available to run a local language model, and competing with inference for memory bandwidth.

Lumen Ora eliminates that overhead entirely.

| What traditional OSes run at idle | What Lumen Ora runs at idle |
|---|---|
| Desktop compositor (DWM, WindowServer, Mutter) | Minimal framebuffer renderer (text + one legacy surface) |
| Window manager, taskbar, file manager shell | Nothing — the AI is the shell |
| Telemetry, cloud sync, update daemons | Nothing |
| Font cache, icon cache, thumbnail service | Embedded font atlas, nothing else |
| App store agents, Electron system UI | Nothing |
| OS-integrated AI assistant competing for NPU | The inference runtime, with exclusive NPU access |

**The result:** Lumen Ora consumes roughly 200–400 MB of RAM at idle. A Windows 11 OEM install consumes 5–7 GB. That difference — 4–6 GB on a 16 GB machine — is the difference between running an 8B parameter model and a 14B parameter model at interactive speed. It is a capability tier jump, not a tuning improvement.

---

## What Using It Looks Like

```
[Lumen Ora — Snapdragon X Elite / 16GB / NPU active]

> I need to write a cover letter for the senior SRE role at the posting
  I saved last Tuesday. Use my resume from Documents.

  Searching saved context... found job posting (Acme Corp, SRE, 2025-05-13).
  Loading resume from /home/user/Documents/resume-2025.pdf...
  Drafting cover letter. ~8 seconds.

  [cover letter text appears inline]

  Saved to /home/user/Documents/cover-letter-acme-sre.txt.
  Want me to adjust the tone, emphasize a different skill set, or send it?

> Make the second paragraph more concise and drop the Kubernetes reference —
  they're a Nomad shop.

  Done. Updated version saved. Here is the revised paragraph:

  [revised paragraph]

  Anything else before I close this context?

> Run the background disk usage analysis I set up last week and show me
  anything over 10GB.

  Running storage-audit (last configured 2025-05-11)...

  /home/user/Videos       47.2 GB
  /var/lib/docker         18.6 GB
  /home/user/Downloads    11.4 GB

  Docker is using 18.6 GB. Want me to prune stopped containers and
  dangling images? Estimated recoverable: ~12 GB.

> Yes, prune it. And remind me to review the Videos folder this weekend.

  Pruning Docker... done. Recovered 11.8 GB.
  Reminder set: Saturday 09:00 — review /home/user/Videos.
```

The session above runs entirely locally. No cloud call. No application switching. The model (Qwen2.5 14B at Q4_K_M) maintains context across tasks, has access to the file system and process runner through structured tool calls defined in the orchestration layer, and the entire exchange takes approximately 45 seconds on the target hardware.

---

## How It Works

Lumen Ora is a layered architecture. Each layer has a narrow, auditable contract with the layer above it.

```
┌─────────────────────────────────────────────────────┐
│              User (voice / text input)               │
├─────────────────────────────────────────────────────┤
│          AI Orchestration Layer                      │
│  Local inference runtime · Tool call router          │
│  Session memory · Multi-model coordinator            │
├─────────────────────────────────────────────────────┤
│              Policy Layer                            │
│  Capability grants · Audit log · Sandboxing rules    │
│  "What the AI is allowed to do and when"             │
├─────────────────────────────────────────────────────┤
│         Genode Framework (OS personality)            │
│  Component isolation · Driver subsystems             │
│  Legacy Linux compatibility (Sculpt-style)           │
├─────────────────────────────────────────────────────┤
│              seL4 Microkernel                        │
│  Formally verified · Capability-based IPC            │
│  Hardware resource enforcement                       │
└─────────────────────────────────────────────────────┘
                Hardware (x86 / ARM / NPU)
```

**seL4** provides the security foundation. Its formal verification means the kernel cannot be subverted by a compromised component — including a compromised AI response. Every capability the AI has must be explicitly granted through the Policy Layer.

**Genode** provides the OS personality: device drivers, file systems, networking, and the legacy Linux compatibility environment (based on Genode's Sculpt architecture), each running as isolated components that can fail independently.

**The Policy Layer** is the critical interface between the AI and the system. Every action the AI Orchestration Layer takes — reading a file, running a process, sending a network request — passes through an explicit capability grant. Users configure these grants. The AI cannot escalate its own privileges. Grants are audited and logged.

**The AI Orchestration Layer** is where inference happens. The local language model runs here, with direct access to hardware via the Policy Layer's grants. It handles: natural language understanding, tool dispatch (file I/O, process execution, network calls, device control), session memory management, multi-turn context, and model routing (smaller fast model for quick queries, larger model for reasoning-heavy tasks).

**The minimal compositor** renders text output and one optional legacy application surface. It holds approximately 25–60 MB of GPU memory versus 250–900 MB for traditional OS compositors. On integrated/unified memory hardware, this freed bandwidth is directly available to inference.

---

## Hardware Target

Lumen Ora is designed for commodity hardware. No specialized accelerators required, though NPUs are a first-class citizen.

**Minimum viable (usable, 7-8B model):**
- x86-64 or ARM64 processor with AVX2 / NEON
- 16 GB RAM (dual-channel DDR5 preferred for bandwidth)
- 50 GB storage

**Recommended (14B model at interactive speed):**
- Snapdragon X Elite, AMD Ryzen AI 300, Intel Lunar Lake, or equivalent with NPU
- 16 GB LPDDR5x unified memory
- 100 GB NVMe storage

**High capability (32B model or dedicated GPU inference):**
- 32 GB RAM
- Optional: dedicated GPU with 8–12 GB VRAM (NVIDIA RTX 40-series or AMD RX 7000-series)

The NPU, when present, is allocated exclusively to the inference runtime. No OS features compete for it.

---

## Current Status

**Pre-alpha. Design and architecture phase.**

This repository currently contains:
- Architecture documentation and design rationale
- Research on resource overhead and inference viability (see `/docs/resource-analysis.md`)
- Prototype notes for the Policy Layer capability model

**Nothing here boots yet.** The first milestone is a minimal prototype that can boot on real hardware, load a language model, and accept text input. That is the 90-day goal.

We are being honest about this because we think the open source ecosystem deserves projects that are clear about what stage they are at. If you came here hoping to download a working OS, you are early. If you came here hoping to help build one, you are right on time.

---

## Roadmap

### 90-day goal: The Minimal Kernel (Milestone 0)
Boot a Genode/seL4 system on a Snapdragon X Elite development board and an x86-64 machine. Load a quantized 7B model via llama.cpp. Accept text input through a serial/framebuffer terminal. Execute one structured tool call (read a file and return its contents in a response). Demonstrate the Policy Layer rejecting an unauthorized capability request.

This is proof of concept, not product. The goal is to confirm that the stack is viable and the performance numbers hold up on real hardware.

### 6-month goal: Usable for a Developer
Voice input. Persistent session memory. File system access (read/write) through the Policy Layer. Basic legacy Linux app execution. Network access with per-session grants. Reproducible build system for the full stack.

A developer should be able to use this as their primary machine for a workday, with reasonable friction, and get useful work done.

### 12-month goal: Beta
Multiple model support (fast routing between small and large models). NPU acceleration across Qualcomm, AMD, and Intel NPU hardware. Audio I/O for voice-primary use. User-configurable Policy profiles ("work mode," "offline mode," "high trust mode"). A documented API for writing native Lumen Ora applications (which are just policy-granted tool suites, not GUI apps).

### Longer term
Arm-native builds targeting Raspberry Pi class hardware (making capable local AI accessible at the low end). A weight-sharing cooperative (see "Why Open Source?"). Support for specialized hardware (robot controllers, embedded inference). A formal security audit of the Policy Layer.

---

## Contributing

Lumen Ora has two contribution tracks. They require different skills and operate somewhat independently.

### Track 1: OS and Systems Engineering

This is the seL4/Genode layer, the Policy Layer, driver work, the compiler toolchain, performance engineering, and the legacy Linux compatibility environment.

**What you need to know:** C, C++, some Rust. Experience with embedded systems, OS internals, or formally verified software is valuable. Familiarity with Genode's component model is a strong plus. Comfort reading seL4 capability theory documentation is required for Policy Layer work.

**How to get started:**
1. Read the architecture documentation in `/docs/architecture/`
2. Set up the Genode development environment (see `/docs/dev-setup/genode.md`)
3. Look at issues tagged `os-layer` or `policy-layer`
4. The first good contribution area: the Policy Layer capability model needs formal specification. If you have experience with formal methods (Isabelle/HOL, TLA+, Alloy), this is an open invitation.

### Track 2: AI Model and Behavior Engineering

This is the inference runtime integration, the tool call schema, prompt engineering, session memory architecture, model routing logic, and behavior evaluation.

**What you need to know:** Python. Experience with llama.cpp, MLX, or ggml backends. Understanding of quantization trade-offs (GGUF formats, K-quants). Familiarity with structured output and tool-use patterns in language models. Experience evaluating model behavior is valuable.

**How to get started:**
1. Read `/docs/inference/runtime-design.md` and `/docs/inference/tool-schema.md`
2. Set up the inference development environment (see `/docs/dev-setup/inference.md`) — this works on a standard Linux machine without the full OS stack
3. Look at issues tagged `inference` or `behavior`
4. The first good contribution area: the tool call schema needs formal JSON Schema definitions with security-relevant constraints (e.g., path traversal prevention at the schema level, not just policy enforcement). This is tractable and important.

### General contribution guidelines
- Open an issue before starting significant work. Design discussions happen there.
- All code changes require a corresponding test or documented rationale for why testing is not applicable.
- The Policy Layer is safety-critical. Changes to it require two maintainer reviews.
- Be specific about hardware in bug reports. "It is slow" is not a bug report. "Qwen2.5 14B Q4_K_M decodes at 6 tok/s on Snapdragon X Elite, expected 18+ tok/s" is.

---

## Why Open Source?

Three reasons, in decreasing order of idealism.

**First:** An operating system that mediates between a language model and your hardware, your files, and your network is an extraordinary amount of trust to place in any single organization. The Policy Layer in particular — the thing that decides what the AI is and is not allowed to do — must be auditable by anyone who uses the system. Closed-source AI-native OSes are a category of product that should not exist. The code that governs what an AI can do to your machine should be readable by the person who owns the machine.

**Second:** The model weights that matter for local inference are being developed across a global research community — Llama, Mistral, Gemma, Qwen, Phi. Lumen Ora does not intend to train its own general-purpose base model; it intends to be the best possible runtime environment for the models that already exist and the models that will be released in the next two years. That relationship works best as an open ecosystem.

**Third:** The hardware optimization work — NPU backends, quantization-aware inference paths, driver-level memory management — is deeply platform-specific and moves fast. A proprietary project cannot sustain that across Qualcomm, AMD, Intel, NVIDIA, and Apple Silicon simultaneously. The community can.

**License:** Core OS code and the Policy Layer are licensed under MPL 2.0. Any fine-tuned model weights released as part of this project are licensed under RAIL (Responsible AI License), which permits broad use while prohibiting specific harmful applications. We are explicit about the distinction: MPL 2.0 covers the code that runs models; RAIL covers the model artifacts themselves. Base model weights from third parties (Llama, Mistral, etc.) are governed by their own licenses and we do not modify those terms.

---

## Install (Placeholder)

There is nothing to install yet. When the Milestone 0 build is ready, this section will contain:

```bash
# Download the Lumen Ora image for your hardware
curl -L https://lumenos.org/releases/m0/lumen-ora-x86_64-m0.img.zst | zstd -d > lumen-ora.img

# Write to USB (replace /dev/sdX with your drive — be careful)
sudo dd if=lumen-ora.img of=/dev/sdX bs=4M status=progress && sync

# Boot from USB. The system will load the default 7B model on first boot.
# No other setup required.
```

For Snapdragon X Elite (arm64):
```bash
curl -L https://lumenos.org/releases/m0/lumen-ora-arm64-snapdragon-m0.img.zst | zstd -d > lumen-ora.img
# Same dd command as above
```

If you want to follow development before the first release:
- Watch this repository
- Join the discussion in GitHub Discussions (not Discord — we prefer async and indexed)
- The mailing list for architecture decisions is `arch@lumenos.org` (not yet active)

---

## Who Is Building This

Lumen Ora was started by [@ericvonbibra](https://github.com/ericvonbibra).

This is early. The contributor list is short. That is expected for a project at this stage, and it will change.

---

*Lumen Ora is not affiliated with any AI company, hardware vendor, or OS vendor. It does not have a business model yet. It has a design goal: make local AI inference the primary OS primitive, on hardware people already own, with security properties that can be formally verified and governance that can be publicly audited.*
