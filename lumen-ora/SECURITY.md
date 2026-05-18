# Security Policy

## Overview

Lumen Ora sits at an unusual intersection: it is an operating system whose primary interface is a language model with direct access to the host's hardware, file system, and network stack. Security vulnerabilities here are not merely software bugs — they can represent AI behavior that bypasses intended policy controls, or policy controls that fail to enforce their stated invariants.

We take security reports seriously and respond to them on the timeline described below.

---

## What We Consider a Security Vulnerability

### Category A: Policy Layer Bypasses
Anything that allows the AI layer to perform an action that the Policy Layer is configured to deny. This includes:
- Tool calls that reach the filesystem, network, or process runner without going through the policy engine
- Policy rules that can be circumvented through crafted inputs (prompt injection that escapes into tool calls, path traversal in file access rules, etc.)
- Audit log gaps — actions that are performed but not recorded
- Privilege escalation: the AI granting itself capabilities it was not explicitly given

These are our most serious vulnerabilities. We treat Policy Layer bypasses as P0 regardless of how they are achieved.

### Category B: Inference Layer Vulnerabilities
- Model behavior that consistently violates the system's stated safety rules regardless of Policy Layer configuration
- Prompt injection via untrusted content (files, web pages, or other user data loaded into the model's context) that causes the model to issue unauthorized tool calls
- Deserialization or parsing vulnerabilities in the inference bridge that allow arbitrary code execution

### Category C: OS and Kernel Vulnerabilities
- seL4 capability violations (capability leaks, capability forgery)
- Genode component isolation failures
- Privilege escalation via the compatibility environment (Linux compat containers escaping their isolation)
- Memory safety issues in safety-critical components (Policy Layer daemon, inference bridge)

### Not in Scope (for this policy)

The following are out of scope for our security policy, though we still welcome bug reports through normal issue tracking:
- Theoretical attacks with no practical exploit path on our supported hardware
- Vulnerabilities in third-party base model weights (report these to the upstream model maintainers)
- Vulnerabilities in llama.cpp or other upstream dependencies (report these upstream; we will apply patches)
- Social engineering attacks (no software patch can address these)
- Physical access attacks on the hardware itself

---

## Reporting a Vulnerability

**Do not report security vulnerabilities through public GitHub issues.**

Send security reports to: `security@lumenos.org`

PGP public key for encrypted reports:

```
-----BEGIN PGP PUBLIC KEY BLOCK-----
[Key will be published here when the project's security infrastructure is established.
Until then, please use Signal or encrypted email negotiated via direct contact with
@ericvonbibra on GitHub.]
-----END PGP PUBLIC KEY BLOCK-----
```

### What to include in your report

1. **Category:** Which category above does this fall into?
2. **Description:** A clear description of the vulnerability, what it allows an attacker to do, and what assumptions it requires (e.g., "requires the attacker to be able to supply a crafted file that gets loaded into model context").
3. **Reproduction steps:** The minimum steps needed to reproduce the issue. If this requires specific hardware, note that.
4. **Impact assessment:** Your assessment of the severity and likely exploitation difficulty.
5. **Suggested fix (optional):** If you have a proposed fix, include it. This is helpful but not required.

You may report anonymously if you prefer. We will not ask for your identity unless you choose to be credited.

---

## Our Response Timeline

| Action | Target Timeline |
|--------|----------------|
| Acknowledge receipt of report | 48 hours |
| Initial triage and severity assessment | 7 days |
| Status update (confirmed / not confirmed / need more info) | 14 days |
| Fix developed and reviewed | 30 days for P0/P1; 90 days for P2/P3 |
| Public disclosure | After fix is released, or 90 days from report (whichever comes first) |

For P0 vulnerabilities (Policy Layer bypasses), we may release an emergency patch outside of the normal release schedule.

If we cannot meet a timeline above, we will notify you and explain why.

---

## Severity Classification

We use a four-tier severity scale:

**P0 — Critical**
Any Policy Layer bypass. Any vulnerability that allows the AI to perform an action the user has explicitly denied. Any seL4 capability violation. These are treated as active emergencies.

**P1 — High**
Remote code execution without user interaction. Prompt injection that consistently causes unauthorized tool calls. Memory safety vulnerabilities in the inference bridge that allow code execution.

**P2 — Medium**
Vulnerabilities that require attacker-controlled content in the model's context. Audit log gaps that do not involve active bypasses. Information disclosure through the inference layer.

**P3 — Low**
Theoretical vulnerabilities with significant practical barriers. Denial-of-service via resource exhaustion. Minor information disclosure.

---

## Disclosure Policy

We follow a coordinated disclosure model:

1. The reporter has the right to publish their findings. We ask for 90 days from the date of our acknowledgment before public disclosure — sufficient time to develop, test, and release a fix.

2. If 90 days pass without a fix, the reporter is free to disclose. We will note this in our public incident report.

3. We will credit reporters in our security advisories unless they request anonymity.

4. We will not pursue legal action against reporters who act in good faith and follow this policy.

5. If a vulnerability is being actively exploited in the wild, we will accelerate disclosure and notify affected users as quickly as possible.

---

## Security Architecture: What We Have and What We Don't

**What we have (design intent, not yet fully implemented):**
- seL4's formal verification provides kernel-level guarantees that capability rules are enforced at the hardware boundary
- Genode's component model provides userspace isolation between OS components
- The Policy Layer is designed to be the sole gateway between AI tool calls and system resources
- All capability grants are logged to an append-only audit log

**What we don't have yet (prototype limitations):**
- The 90-day prototype runs on Linux/NixOS, not seL4. The Policy Layer daemon in the prototype is a userspace process, not kernel-enforced.
- The prototype's isolation guarantees are therefore weaker than the target architecture's. Vulnerabilities in the prototype may not be exploitable in the production seL4 architecture.
- Formal verification of the Policy Layer itself (distinct from seL4 verification) is planned but not yet complete.

When reporting vulnerabilities, please note whether you are testing against the prototype or the production architecture, as this affects severity classification.

---

## Bug Bounty

There is no bug bounty program at this stage. We are a volunteer project. We will provide public credit, a spot in SECURITY-CONTRIBUTORS.md, and our genuine gratitude. If and when the project has revenue, we intend to establish a formal bounty program.

---

## Security Contacts

Primary: `security@lumenos.org`
Backup: GitHub Security Advisories (use the "Report a vulnerability" button on the repository page)
Escalation: Direct contact with the Safety Subcommittee chair (see GOVERNANCE.md for current membership)

---

*This policy was last updated: 2026-05-19*
