---
name: Model RFC (Request for Comments)
about: Propose a change to model behavior, the tool call schema, default Policy Layer rules, or the prompt format
title: "[RFC] "
labels: rfc, model-behavior, needs-safety-review
assignees: ''
---

<!-- ─────────────────────────────────────────────────────────────────────────
     READ THIS BEFORE FILING

     Model RFCs are for changes that affect HOW THE AI BEHAVES. This includes:
     - New tool types or changes to existing tool schemas
     - New or modified Policy Layer default rules
     - Changes to the system prompt or prompt format
     - Changes to model routing logic (when to use small vs. large model)
     - Changes to how session memory is managed
     - Any change to the audit log format

     These changes go through a different, more deliberate process than code changes.
     The full process is documented in GOVERNANCE.md. At a high level:
     1. RFC filed → Safety Subcommittee reviews (21 days)
     2. If approved for beta: 60-day beta with telemetry opt-in
     3. Telemetry analysis → Steering Council vote on making it default
     4. Default deployment

     If you are not sure whether your change needs an RFC, ask in GitHub Discussions first.
     ───────────────────────────────────────────────────────────────────────── -->

## RFC Title

<!-- A short, descriptive name for this change. This becomes the RFC's canonical name. -->

## Author(s)

<!-- Your GitHub username(s). -->

## Status

<!-- Leave this as "Draft" when first filed. The Safety Subcommittee will update it. -->

`Draft`

## Summary

<!-- 1-3 sentences: what are you proposing to change and why? -->

## Background and Motivation

<!-- What problem does this change solve? What user need or safety concern drives it?
     Be specific. "This would be nicer" is not sufficient motivation for a behavioral change.
     "In observed sessions, users frequently encounter X because the system does Y by default,
     which causes them to Z" is sufficient motivation. -->

## Detailed Proposal

### What changes

<!-- Describe the change precisely. If this is a new Policy Rule, write out the rule text.
     If this is a change to the tool call schema, show the before and after JSON Schema.
     If this is a prompt format change, show the before and after prompt structure.
     Be specific enough that a contributor could implement this from your description alone. -->

### What stays the same

<!-- Explicitly state what is NOT changing. This prevents misunderstandings during review. -->

### Example interaction (required for behavioral changes)

<!-- Show a before/after example of a user interaction that this change affects.
     Show at least one case where the new behavior is better.
     Show at least one edge case where the behavior might be surprising. -->

**Before:**
```
User: [user input]
System: [current behavior]
```

**After:**
```
User: [user input]
System: [proposed behavior]
```

## Security Analysis

<!-- This section is mandatory. The Safety Subcommittee will scrutinize it. -->

**Does this change expand the AI's capabilities?**
<!-- If yes: what new things can the AI do that it couldn't before? Are they gated by
     Policy Layer rules? Which rules? -->

**Attack surface analysis:**
<!-- What is the worst-case outcome if this change is exploited through prompt injection
     or a compromised model response? -->

**Policy Layer interaction:**
<!-- Does this change require new Policy Layer rules? Does it affect existing rules?
     If it modifies capability grants, which capabilities and under what conditions? -->

**Audit log implications:**
<!-- Does this change affect what gets logged? If yes, how? -->

**Reversibility:**
<!-- If this change turns out to have negative consequences, how easy is it to roll back?
     What is the impact on users who adopted the new behavior during beta? -->

## Telemetry Proposal

<!-- During the 60-day beta, what signals will we collect to evaluate whether this change
     is working as intended? Be specific. "User satisfaction" is not a telemetry signal.
     "Rate at which tool calls with the new parameter type are rejected by the Policy Layer
     vs. the old parameter type" is a telemetry signal.

     All telemetry must be opt-in and documented. Do not propose collecting anything a
     user would not expect or consent to. -->

Proposed telemetry signals:
1.
2.
3.

Proposed success criteria for graduation to default:
<!-- What numbers need to look like for this to become the default after the 60-day beta? -->

## Alternatives Considered

<!-- What other approaches did you consider? Why did you choose this one? -->

## Implementation Plan

<!-- Who is going to implement this? What is the rough effort estimate?
     Does this depend on any other RFC or code change? -->

## Open Questions

<!-- List anything you are uncertain about and would like feedback on. This is a good place
     to note areas where you want Safety Subcommittee guidance. -->

---

<!-- ─────────────────────────────────────────────────────────────────────────
     FOR SAFETY SUBCOMMITTEE USE ONLY
     (do not fill this in — it will be updated during review)
     ───────────────────────────────────────────────────────────────────────── -->

## Safety Subcommittee Review

**Review assigned to:**
**Review deadline:**
**Decision:**
**Notes:**
