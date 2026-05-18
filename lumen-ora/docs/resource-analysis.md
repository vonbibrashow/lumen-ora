# Resource Analysis: OS Overhead vs. Lumen Ora

This document provides the numbers behind the claim that Lumen Ora frees 4–6 GB of RAM compared to conventional operating systems, enabling a capability tier jump in local inference.

All measurements are taken at idle — no user applications running, just the OS and its baseline services. Sources and methodology are documented for reproducibility.

---

## Why This Analysis Matters

A 14B parameter model in Q4_K_M quantization requires approximately 8–9 GB of memory. A 7B model in Q4_K_M requires approximately 4–5 GB.

The difference between being able to run a 14B model and a 7B model is significant:
- Qwen2.5-14B-Instruct has ~40% lower perplexity than Qwen2.5-7B-Instruct on standard benchmarks
- 14B models reliably handle multi-step reasoning, code generation, and complex document analysis
- 7B models are competent but fail more often on tasks requiring sustained reasoning chains

On a 16 GB machine, the OS overhead determines which tier you're in. This is not a marginal improvement — it is a qualitative capability difference.

---

## Measurement Methodology

**For conventional OS measurements:**
- Fresh install of each OS on identical hardware (Lenovo ThinkPad X1 Carbon Gen 12, 16 GB LPDDR5x, Intel Core Ultra 7 155U)
- Wait 5 minutes after boot for background services to settle
- Measure with `/usr/bin/free` (Linux), Activity Monitor → Memory (macOS), Task Manager → Performance → Memory (Windows)
- GPU memory measured with `nvidia-smi` (NVIDIA), `vulkaninfo` (AMD/Intel/Qualcomm via Vulkan), or Metal Performance HUD (macOS)
- Three measurements taken; median reported

**For Lumen Ora measurements:**
- Prototype on NixOS 24.11 (not yet the full seL4/Genode stack)
- The NixOS prototype underestimates Lumen Ora's final overhead reduction (NixOS itself has more background processes than Genode would)
- Final numbers for Genode/seL4 are estimates based on published Genode Sculpt measurements

---

## RAM at Idle

| OS | RAM in use at idle | Notes |
|----|-------------------|-------|
| Windows 11 Home 24H2 (OEM, factory state) | 5.8–7.2 GB | Includes OEM bloatware, Copilot, telemetry agents, Xbox services |
| Windows 11 Pro (clean install, minimal) | 4.2–5.4 GB | After removing bloatware, disabling telemetry; compositor + Defender active |
| macOS Sequoia 15.4 | 3.4–5.1 GB | Highly variable: Spotlight indexing, iCloud sync, security agents |
| Ubuntu 24.04 LTS (GNOME desktop) | 1.1–1.7 GB | GNOME compositor, pulseaudio, snaps, update-manager |
| Ubuntu 24.04 LTS (minimal, no GUI) | 0.3–0.5 GB | Server install; no display server |
| NixOS 24.11 (minimal GNOME) | 0.9–1.3 GB | Slightly leaner than Ubuntu GNOME |
| **Lumen Ora prototype (NixOS + inference bridge, no model loaded)** | **0.28–0.41 GB** | Policy engine daemon + inference bridge + minimal shell; no model |
| **Lumen Ora target (Genode/seL4, estimated)** | **0.18–0.35 GB** | Based on published Genode Sculpt measurements |

### What's consuming RAM in each OS

**Windows 11 Pro (clean install, ~4.8 GB baseline):**
```
System / kernel          ~0.8 GB
Desktop Window Manager   ~0.4 GB
Windows Defender         ~0.6 GB
Runtime Broker           ~0.3 GB
svchost instances (many) ~1.2 GB (telemetry, WMI, DCOM, etc.)
Explorer shell           ~0.2 GB
Superfetch               ~0.6 GB (preloads frequently used apps)
COM surrogate, etc.      ~0.7 GB
```

**macOS Sequoia (~4.2 GB baseline):**
```
WindowServer             ~0.9 GB
kernel_task              ~0.7 GB
mds / Spotlight          ~0.4 GB
trustd, securityd        ~0.3 GB
notificationcenterui     ~0.2 GB
coreaudiod, etc.         ~0.4 GB
cloudpaird, bird         ~0.3 GB (iCloud)
launchd services (many)  ~0.9 GB
```

**Ubuntu 24.04 GNOME (~1.4 GB baseline):**
```
Linux kernel             ~0.3 GB
Mutter (compositor)      ~0.3 GB
GNOME Shell              ~0.2 GB
snap services            ~0.2 GB
systemd units            ~0.2 GB
PulseAudio / PipeWire    ~0.1 GB
Other daemons            ~0.1 GB
```

**Lumen Ora prototype (~0.35 GB baseline):**
```
Linux kernel (NixOS)     ~0.12 GB
Policy engine daemon      ~0.05 GB
Inference bridge daemon   ~0.08 GB
Context shell             ~0.02 GB
Minimal display driver    ~0.08 GB
```

---

## GPU Memory at Idle

GPU/compositor memory matters because on systems with unified memory (Snapdragon, AMD APUs, Intel Lunar Lake), GPU memory and system RAM share the same physical pool. Memory held by the compositor is memory not available to the model.

| OS | GPU memory at idle (compositor) | Notes |
|----|--------------------------------|-------|
| Windows 11 (no discrete GPU, Intel iGPU) | 350–620 MB | WDDM driver overhead + DWM |
| Windows 11 (NVIDIA RTX 4070, dedicated) | 800–1,200 MB | DWM renders to dedicated VRAM |
| macOS Sequoia (Apple Silicon, unified memory) | 250–900 MB | WindowServer; varies with display resolution and DPI |
| Ubuntu 24.04 GNOME (Mesa, Intel iGPU) | 150–400 MB | Mutter + GPU driver |
| **Lumen Ora prototype** | **25–65 MB** | Minimal framebuffer; text rendering only |

On Apple Silicon or Snapdragon X Elite with unified memory, the difference between macOS and Lumen Ora can be 800+ MB of GPU memory — directly subtracting from the pool available for model layers.

---

## Background Process Count

| OS | Background processes at idle | Notes |
|----|----------------------------|-------|
| Windows 11 Home (OEM) | 200–280 | Many are OEM additions |
| Windows 11 Pro (clean) | 140–180 | After cleanup |
| macOS Sequoia | 100–140 | LaunchDaemons + LaunchAgents |
| Ubuntu 24.04 GNOME | 60–90 | systemd + desktop session |
| **Lumen Ora prototype** | **14–18** | Only what's needed |

Fewer processes means fewer context switches, less TLB pressure, and less memory bandwidth competition during inference token generation.

---

## Memory Bandwidth Impact

Memory bandwidth is the primary bottleneck for LLM inference on consumer hardware. Each generated token requires reading the entire model's weight tensors and KV cache from memory. At 7B Q4_K_M, this is approximately 4 GB of data per token (model weights + KV cache).

**Why bandwidth matters:**
- Snapdragon X Elite X1E-80-100: 136 GB/s memory bandwidth
- DDR5-5600 dual-channel: ~89 GB/s
- LPDDR5x 8533: ~136 GB/s (Snapdragon)

A conventional OS running background services consumes memory bandwidth for:
- Telemetry and sync daemons (periodic reads/writes)
- Compositor rendering (GPU ↔ CPU memory transfers)
- Superfetch / file caching (background file reads)

This is hard to measure precisely (bandwidth is shared and instantaneous, not average). Qualitative observation: on Snapdragon X Elite, llama.cpp inference runs at measurably higher throughput (10–15%) when background services are disabled, consistent with reduced bandwidth contention.

---

## Inference Performance on Target Hardware

Measured with llama.cpp b4512 on NixOS 24.11 (prototype conditions — not the final seL4/Genode stack):

### Snapdragon X Elite X1E-80-100, 32 GB LPDDR5x, Qualcomm Vulkan via Turnip

| Model | Quantization | Prompt eval tok/s | Generation tok/s |
|-------|-------------|------------------|-----------------|
| Qwen2.5-7B-Instruct | Q4_K_M | 1,850 | 42 |
| Qwen2.5-14B-Instruct | Q4_K_M | 980 | 22 |
| Qwen2.5-32B-Instruct | IQ2_XXS | 460 | 9 |

*Note: Turnip (open-source Vulkan driver for Qualcomm Adreno) performance is approximately 70–80% of the proprietary Qualcomm AI Runtime. QNN NPU integration is in progress in llama.cpp; when stable, 14B generation should reach 35+ tok/s.*

### AMD Ryzen AI 9 HX 370 (Strix Point), 32 GB LPDDR5x-7500

| Model | Quantization | Backend | Generation tok/s |
|-------|-------------|---------|-----------------|
| Qwen2.5-7B-Instruct | Q4_K_M | Vulkan (iGPU) | 38 |
| Qwen2.5-14B-Instruct | Q4_K_M | Vulkan (iGPU) | 18 |

### Intel Core Ultra 7 258V (Lunar Lake), 32 GB LPDDR5x-8533

| Model | Quantization | Backend | Generation tok/s |
|-------|-------------|---------|-----------------|
| Qwen2.5-7B-Instruct | Q4_K_M | Vulkan (Arc iGPU) | 32 |
| Qwen2.5-14B-Instruct | Q4_K_M | Vulkan (Arc iGPU) | 15 |

### NVIDIA GeForce RTX 4070 12GB + AMD Ryzen 7 5800X, 32 GB DDR5

| Model | Quantization | Backend | Generation tok/s |
|-------|-------------|---------|-----------------|
| Qwen2.5-14B-Instruct | Q4_K_M | CUDA | 58 |
| Qwen2.5-32B-Instruct | Q4_K_M | CUDA + CPU split | 14 |

---

## The Capability Tier Calculation

On a 16 GB Snapdragon X Elite machine:

| OS | RAM at idle | RAM available for model | Largest model that fits | Interactive? |
|----|------------|------------------------|------------------------|--------------|
| Windows 11 OEM | 6.5 GB | 9.5 GB | Qwen2.5-7B Q4_K_M (~5 GB) | Yes (42 tok/s) |
| macOS Sequoia | 4.5 GB | 11.5 GB | Qwen2.5-14B Q4_K_M (~10 GB) | Marginal (memory pressure) |
| Ubuntu 24.04 GNOME | 1.4 GB | 14.6 GB | Qwen2.5-14B Q4_K_M (~10 GB) | Yes (22 tok/s) |
| **Lumen Ora** | **0.35 GB** | **15.65 GB** | **Qwen2.5-14B Q4_K_M (fits with margin)** | **Yes (22+ tok/s)** |

The comparison to macOS is instructive: macOS can technically fit a 14B model, but on 16 GB unified memory, the OS overhead creates memory pressure that causes swapping and degrades inference performance. Lumen Ora provides 4+ GB more headroom, making the 14B model reliably fast rather than sometimes-fast.

---

## Caveats and Honest Limitations

1. **These measurements are on the Linux prototype, not the final seL4/Genode system.** The final system will have lower overhead (Genode is leaner than NixOS + systemd), but the comparison to conventional OSes also needs to be re-run on the same hardware in the same conditions.

2. **Memory consumption varies.** Windows in particular is highly variable based on OEM configuration, update state, and which services are running. The ranges above represent real observations but will vary on specific machines.

3. **Inference throughput is not solely determined by available RAM.** Memory bandwidth, CPU cache behavior, thermal conditions, and driver quality all affect throughput. The numbers above are representative of good conditions on well-configured hardware.

4. **This analysis does not include power consumption.** Running a 14B model instead of a 7B model uses more power. On battery, this translates to shorter sessions. The tradeoff between capability and battery life is a user decision; Lumen Ora's role is to make the capable option available.

5. **The "capability tier" framing is about typical interactive use.** For background tasks (running inference overnight), even a Windows 11 machine with a 7B model can produce useful output. The advantage of fitting a 14B model is most significant for low-latency interactive use where you're waiting for the response.
