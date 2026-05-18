---
name: Feature request
about: Propose a new capability, improvement, or change to an existing component
title: "[FEATURE] "
labels: enhancement, needs-triage
assignees: ''
---

## Problem Statement

<!-- What problem does this feature solve? What can't you do today that you want to be able to do?
     Start with the user problem, not the implementation. "I want X" is less useful than "When I try
     to do Y, I can't because Z, which means I have to work around it by doing W, which is slow/unsafe/annoying."
-->

## Proposed Solution

<!-- Your proposal. Be specific. If you have a concrete design in mind, sketch it here. If you are open
     to different implementations, say so. -->

## Component(s) Affected

- [ ] Policy Layer — capability rules, audit log, policy engine daemon
- [ ] Context Shell — PTY wrapper, session management, high-stakes detection
- [ ] Inference Bridge — llama.cpp integration, model routing, tool call schema
- [ ] Tool call schema — new tool type or changes to existing tool definitions
- [ ] Genode layer — OS components, isolation, compatibility environment
- [ ] seL4 integration — capability model, kernel interface
- [ ] Documentation
- [ ] Build system / development environment
- [ ] Other: <!-- describe -->

## Security and Policy Implications

<!-- Every feature that touches the Policy Layer, tool call schema, or the boundary between the AI
     and the system MUST answer these questions. For features that don't touch those areas, this
     section can be "N/A." -->

**Does this feature give the AI access to capabilities it does not currently have?**
<!-- If yes: what capabilities, and why is that acceptable? -->

**Could this feature be used to bypass or weaken the Policy Layer?**
<!-- Be honest. If there is a theoretical attack path, describe it. -->

**Does this feature change the audit log in any way?**
<!-- New events that would be logged, events that would stop being logged, format changes. -->

## Alternatives Considered

<!-- What other approaches did you consider and why did you reject them? Even if your alternatives
     are obviously worse, listing them helps reviewers understand your design space. -->

## Implementation Complexity

Your rough estimate:
- [ ] Small — a few hours for someone familiar with the component
- [ ] Medium — a few days, may require design discussion
- [ ] Large — a significant feature requiring sustained effort or architectural changes
- [ ] Unknown — I am not sure what implementing this would take

## Are you willing to implement this?

- [ ] Yes, I intend to open a PR
- [ ] Yes, with guidance from a maintainer
- [ ] No, I am proposing this for someone else to implement
- [ ] Maybe, depending on the design discussion

## Additional Context

<!-- Links to related issues, prior art in other systems, research papers, benchmarks, or anything
     else that would help the team evaluate this proposal. -->

---

**Note on Policy Layer and model behavior changes:** Feature requests that change what the AI is allowed to do, how the AI behaves by default, or how policy rules are defined should use the **Model RFC** template instead of this one. If you are unsure which template to use, use this one and a maintainer will redirect you if needed.
