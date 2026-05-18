---
name: Bug report
about: Something is broken — behavior that does not match what is documented or expected
title: "[BUG] "
labels: bug, needs-triage
assignees: ''
---

## Summary

<!-- One sentence: what is broken? -->

## Component

Which part of the system is affected?

- [ ] Policy Layer (policy-engine daemon, capability enforcement, audit log)
- [ ] Context Shell (PTY wrapper, user interaction, high-stakes detection)
- [ ] Inference Bridge (llama.cpp integration, tool call routing, streaming)
- [ ] Genode component (driver, component isolation, compatibility environment)
- [ ] seL4 integration (capability model, kernel interface)
- [ ] Documentation (wrong, misleading, or missing information)
- [ ] Build system / development environment
- [ ] Other: <!-- describe -->

## Hardware / Software Configuration

**This section is mandatory for performance bugs and OS-layer bugs.**

- CPU / SoC: <!-- e.g., AMD Ryzen 7 5800X, Snapdragon X Elite X1E-80-100 -->
- RAM: <!-- e.g., 32 GB DDR5-5600 dual-channel -->
- GPU / NPU: <!-- e.g., NVIDIA RTX 4070, Qualcomm Hexagon NPU -->
- OS (host, for prototype testing): <!-- e.g., NixOS 24.11, Ubuntu 24.04 -->
- Kernel version: <!-- e.g., Linux 6.12.1 -->
- Model being used: <!-- e.g., Qwen2.5-14B-Instruct-Q4_K_M.gguf -->
- llama.cpp version / commit: <!-- e.g., b4512 -->
- Lumen Ora commit: <!-- run `git rev-parse HEAD` -->

## Steps to Reproduce

<!-- Be precise. The goal is that any contributor can follow these steps and see the same bug. -->

1.
2.
3.

## Expected Behavior

<!-- What should happen? Cite documentation or the README if relevant. -->

## Actual Behavior

<!-- What actually happens? Include exact error messages, not paraphrases. -->

## Logs

<!-- Paste relevant log output here. For Policy Layer bugs, include the audit log entries. -->

<details>
<summary>Log output</summary>

```
paste logs here
```

</details>

## Performance Numbers (if relevant)

<!-- If this is a performance bug: -->
- Observed throughput: <!-- e.g., 4.2 tok/s -->
- Expected throughput: <!-- e.g., 18+ tok/s per docs/resource-analysis.md -->
- Measurement method: <!-- e.g., llama.cpp built-in timing, time to first token measured manually -->

## Additional Context

<!-- Anything else that would help — screenshots, related issues, what you tried to fix it. -->

---

**Before submitting:** Have you searched existing issues for this bug? Many bugs in a pre-alpha project have already been reported.
