# Lumen Ora Governance

**Version:** 1.0
**Effective Date:** 2026-05-19
**Status:** Active

This document establishes the governance structure for the Lumen Ora project. It is binding on all project participants — contributors, maintainers, and Steering Council members. Amendments require the process described in Section 9.

---

## Table of Contents

1. [Principles](#1-principles)
2. [Organizational Structure](#2-organizational-structure)
3. [The Steering Council](#3-the-steering-council)
4. [The Safety Subcommittee](#4-the-safety-subcommittee)
5. [Maintainers](#5-maintainers)
6. [How Decisions Are Made](#6-how-decisions-are-made)
7. [The Model RFC Process](#7-the-model-rfc-process)
8. [Conflict Resolution](#8-conflict-resolution)
9. [Amendments to This Document](#9-amendments-to-this-document)
10. [Security Incident Response](#10-security-incident-response)
11. [Transition to Community Governance](#11-transition-to-community-governance)
12. [Current Council Roster](#12-current-council-roster)

---

## 1. Principles

The following principles are not aspirational — they are constraints that apply to every decision made under this governance document. When a proposed decision violates a principle, the principle wins.

**1.1 Auditability.** The code that governs what an AI can do on a person's machine must be readable by the person who owns the machine. No part of the Policy Layer, the tool call schema, or the default rule set may be closed-source or obfuscated.

**1.2 User sovereignty.** The user controls the AI's capabilities. The project may define defaults, but users must be able to understand, review, and change those defaults on their own system. A governance decision that removes user control over Policy Layer configuration on their own machine is not permitted.

**1.3 Safety primacy.** Changes that expand the AI's capabilities, reduce the restrictiveness of default policy rules, or modify the audit mechanism require a higher threshold of review than other changes. The Safety Subcommittee's veto power exists because these decisions have asymmetric downside risk.

**1.4 Proportional process.** Not every decision requires a vote. The process is scaled to the significance of the change. Typo fixes in documentation do not require a Steering Council vote. Changes to the default Policy Layer rules do.

**1.5 Transparency.** Governance decisions are made in public, recorded in public, and explained in plain language. The Steering Council does not make decisions in private channels, with the exception of security vulnerability handling (Section 10).

**1.6 No corporate capture.** The Lumen Ora Foundation is modeled on the Python Software Foundation's governance model. There are no corporate seats on the Steering Council. Organizational affiliations of Council members are disclosed but do not determine their voting weight or eligibility.

---

## 2. Organizational Structure

```
Lumen Ora Foundation
        │
        ├── Steering Council (7 seats)
        │         │
        │         └── Safety Subcommittee (≥3 seats, drawn from Council + community)
        │
        └── Maintainers
                  │
                  ├── Component Maintainers (Policy Layer, Inference, OS Layer, Docs)
                  └── Contributors
```

**The Lumen Ora Foundation** is the non-profit legal entity that holds the project's trademarks, domain names, and any financial assets. It is incorporated in a jurisdiction to be determined before the first public release. Until incorporation, these assets are held by the Founder, @ericvonbibra.

**The Steering Council** is the project's primary governing body. It makes decisions about project direction, release policy, the governance document itself, and any matter not delegated to a subcommittee or resolved by a maintainer vote.

**The Safety Subcommittee** has autonomous authority over the safety and AI behavior dimensions of the project, with veto power over changes to the Policy Layer and tool call schema. Its mandate and powers are defined in Section 4.

**Maintainers** are trusted contributors with commit access to the repository. They review and merge pull requests, triage issues, and participate in technical decisions about their components.

---

## 3. The Steering Council

### 3.1 Composition

The Steering Council has seven seats, divided into two categories during the founding period (the first five years of the project, beginning on the effective date of this document):

**Three Founding Seats.** Held by individuals designated at the project's founding. These seats are not subject to election during the founding period. Current holders: see Section 12. From Year 6 onward, founding seats convert to elected seats as the current holder's term ends. No founding seat holder may stand for re-election to the same seat; they may stand for other elected seats.

**Four Elected Seats.** Filled through community elections as described in Section 3.4. The first election is held within 90 days of the project's first public beta release, or by January 1, 2027, whichever is earlier.

Elected seats have two-year terms, staggered so that two seats are up for election each year. No individual may hold more than one seat simultaneously.

### 3.2 Responsibilities

The Steering Council is responsible for:

- Project direction and roadmap (setting milestones, approving release timelines)
- This governance document and any amendments to it
- Adding and removing Maintainers (see Section 5)
- Resolving disputes that cannot be resolved at the Maintainer level (see Section 8)
- Approving the annual budget and expenditures from the Foundation's funds
- Public communication on behalf of the project for significant matters (security incidents, major policy changes, project discontinuation)
- Appointing and removing Safety Subcommittee members (see Section 4)

### 3.3 Decision Making

The Steering Council meets at minimum once per calendar quarter. Meetings are conducted asynchronously (via GitHub Discussions or a designated platform) or synchronously via video call. Meeting notes are published publicly within 7 days.

**Standard decisions** require a simple majority (4/7) of Council members. A Council member who does not vote within 14 days of a decision being called is counted as abstaining.

**Supermajority decisions** (6/7) are required for:
- Overriding a Safety Subcommittee veto (see Section 4.4)
- Amending this governance document (Section 9)
- Adding or removing a Founding Seat holder during the founding period
- Changing the license of the core project code
- Dissolving the Foundation

**Quorum:** A minimum of five Council members must vote for a decision to be valid. If quorum is not met after 14 days, the decision is deferred.

### 3.4 Elections for Elected Seats

Elections for elected Steering Council seats are conducted as follows:

**Eligibility to vote:** Any individual who has had at least one commit, issue, or pull request merged into the Lumen Ora repository in the 12 months preceding the election close date is eligible to vote.

**Eligibility to stand:** Any eligible voter who has been a project participant for at least 6 months. Candidates must not be employed by the same organization as more than one other current Council member at the time they take their seat. (Organizational affiliation changes during a term do not invalidate a seat.)

**Nomination period:** 14 days. Candidates self-nominate via a public GitHub issue, providing a brief statement (under 500 words) of their priorities for the project.

**Voting period:** 7 days, conducted via a private ballot system approved by the Council. Results are published immediately after close.

**Voting method:** Approval voting (voters select all acceptable candidates; the candidates with the most approvals win). Ties are broken by a runoff vote among tied candidates.

**Vacancies:** If an elected seat becomes vacant (resignation, removal, or death), the Council may appoint an interim holder by majority vote. An election for the remaining term is held at the next scheduled election cycle, or within 90 days if more than 12 months remain in the term.

### 3.5 Removal of a Council Member

A Council member may be removed:

- By their own resignation (written notice to the Council)
- By a 6/7 Council vote for sustained failure to participate (missing more than 50% of votes over 6 months without notice) or for conduct incompatible with the project's values (Section 1 and CONTRIBUTING.md's community standards)
- For founding seat holders only: by a 6/7 Council vote for conduct incompatible with the project's values, with no other threshold for removal during the founding period (founding seats cannot be removed for non-participation alone)

Removal decisions are not subject to appeal within the project. A removed member may petition the community through public forums, but the Council decision stands.

### 3.6 Compensation

Steering Council members are not compensated by the Foundation for their Council service. If the Foundation employs any individuals in paid roles, Council members are not eligible for those paid roles while serving on the Council.

---

## 4. The Safety Subcommittee

### 4.1 Purpose and Mandate

The Safety Subcommittee (hereafter "the Subcommittee") has autonomous authority over the safety properties of the Lumen Ora system. Its mandate is to ensure that:

- The Policy Layer correctly limits what the AI is permitted to do on a user's machine
- Changes to the Policy Layer, tool call schema, and default behavioral rules do not introduce regressions in the system's safety properties
- The Model RFC process produces good outcomes (the right changes are adopted, the wrong ones are not)
- Security vulnerabilities in the AI layer are handled appropriately (Section 10)

The Subcommittee reports to the Steering Council but acts independently on the matters within its mandate. The Steering Council cannot override the Subcommittee's decisions within its mandate without a 6/7 supermajority.

### 4.2 Composition

The Subcommittee has at least three members and at most five. At least two members of the Subcommittee must be current Steering Council members. The remaining members may be drawn from the project's contributor community.

Members are appointed by the Steering Council by majority vote. There is no fixed term; members serve until they resign or are removed.

Current Subcommittee members: see Section 12.

**Desired qualifications** (not mandatory, but weighted in appointment decisions):
- Background in formal methods, security, or AI safety research
- Experience auditing safety-critical software
- Track record of thoughtful, conservative judgment in technical review

### 4.3 Decision Making

The Subcommittee requires a quorum of three members for decisions. Decisions within the Subcommittee require a simple majority of the quorum.

**The Subcommittee Chair** is elected by Subcommittee members by majority vote. The Chair coordinates meetings, drives RFC reviews, and is the public point of contact for safety matters. The Chair serves a 12-month renewable term.

### 4.4 Veto Power

The Subcommittee has veto power over the following categories of changes:

- Any change to the Policy Layer code (the policy engine daemon and its rule implementations)
- Any change to the tool call JSON Schema (including adding new tool types)
- Any change to the default values of the 10 starter rules
- Any change to the audit log format or integrity mechanism
- Any Model RFC transitioning from beta to default (see Section 7)

A veto may be exercised by a majority vote of the Subcommittee. A veto blocks the change from merging. The veto must be accompanied by a written explanation stating what specific safety concern the change raises and what the Subcommittee would need to see to lift the veto.

**Overriding a veto:** The Steering Council may override a Subcommittee veto by a 6/7 supermajority vote. The override requires a written statement explaining why the Council finds the Subcommittee's safety concern insufficient to block the change. Override decisions are published in the project's governance log.

The veto override mechanism exists to prevent governance deadlock, not to make safety overrides routine. The Council's use of override power is a significant governance event and will be treated as such by the community.

### 4.5 Emergency Veto

If a change is about to be merged (a PR is approved and queued for merge) that any Subcommittee member believes raises an urgent safety concern, a single Subcommittee member may call an emergency veto. The emergency veto blocks the merge for 72 hours, during which the full Subcommittee must convene and decide whether to sustain or lift it.

Emergency vetoes may only be invoked once per change; if lifted after emergency review, it cannot be re-invoked.

---

## 5. Maintainers

### 5.1 Role and Responsibilities

Maintainers are trusted contributors with write access to the repository. They:

- Review and merge pull requests in their component areas
- Triage and close issues
- Participate in technical decisions about their component
- Enforce contribution guidelines (CONTRIBUTING.md)
- Escalate appropriate matters to the Steering Council

Maintainers do not have unilateral authority over project direction. They have authority over merging code and managing the contribution process.

### 5.2 Component Areas

Maintainers are associated with one or more component areas:

| Component | Scope |
|-----------|-------|
| `policy-layer` | Policy Engine daemon, audit log, capability model |
| `inference` | Inference Bridge, llama.cpp integration, model routing, session memory |
| `context-shell` | Context Shell, user interaction, session management |
| `os-layer` | Genode components, seL4 integration, drivers, compatibility environment |
| `docs` | Documentation in docs/, architecture specs, TLA+ specifications |
| `build` | Build system, CI/CD, release process |

### 5.3 Adding Maintainers

A contributor may be nominated as a Maintainer by any existing Maintainer or Steering Council member. Nomination is via a GitHub issue in a designated governance repository, open for 14 days for community comment.

After the comment period, the Steering Council votes by majority. A successful nomination requires both a Council majority and no strong objections from existing Maintainers in the relevant component area.

**Criteria for maintainership:**
- Track record of high-quality contributions (at least 10 merged PRs, not all trivial)
- Demonstrated understanding of the project's architecture and values
- History of constructive participation in code review and issue discussions
- For `policy-layer` maintainers: specific demonstrated understanding of the Policy Layer's security model

### 5.4 Removing Maintainers

Maintainers may step down by notifying the Steering Council. The Council thanks them and removes their access.

Maintainers may be removed involuntarily by a majority Council vote for:
- Sustained inactivity (no meaningful contribution in 12 months, with prior notice given at 9 months)
- Conduct violations (merging changes without required reviews, misuse of commit access, violations of the community standards)

### 5.5 Policy Layer Maintainers — Special Requirements

Given the safety significance of the Policy Layer, maintainers of the `policy-layer` component must have at least one of:
- At least 6 months of experience as a `policy-layer` maintainer before being granted merge rights (they can review but not merge during this period)
- Prior formal security review experience on safety-critical software, verified by the Subcommittee

Policy Layer merges require two maintainer approvals, one of which must come from a Safety Subcommittee member.

---

## 6. How Decisions Are Made

Not all decisions require the same process. This section defines the process for different decision types.

### 6.1 Code Changes (Non-Policy-Layer)

**Who decides:** Maintainers of the relevant component.
**Process:** Normal PR review. One maintainer approval required. No Steering Council involvement unless a dispute arises.
**Exceptions:** Changes that affect multiple components, introduce a breaking API change, or change a behavior documented in this governance document require a second maintainer review across affected areas.

### 6.2 Policy Layer Changes

**Who decides:** Policy Layer Maintainers, subject to Safety Subcommittee veto.
**Process:**
1. PR opened with description of the rule change, its rationale, and the updated TLA+ specification
2. Two maintainer reviews required (at least one from a Safety Subcommittee member)
3. Safety Subcommittee has 7 days to review and veto; if no veto is exercised, merge proceeds
4. For changes to hardcoded invariants (Rules 2, 5, 6, 8, 9): a full Model RFC is required before the PR is opened

### 6.3 Model Behavior Changes

**Who decides:** Steering Council, based on Safety Subcommittee recommendation, following the Model RFC process.
**Process:** See Section 7 (Model RFC Process) for the full specification.

### 6.4 Project Direction (Roadmap, Milestones)

**Who decides:** Steering Council by majority vote.
**Process:** Proposed roadmap items are discussed in a GitHub Discussion open for at least 14 days, then voted on by the Council.

### 6.5 Governance Changes

**Who decides:** Steering Council by 6/7 supermajority.
**Process:** See Section 9.

### 6.6 Security Incidents

**Who decides:** Safety Subcommittee, with the Steering Council informed.
**Process:** See Section 10.

### 6.7 Licensing Changes

**Who decides:** Steering Council by 6/7 supermajority.
**Process:** Licensing changes are permanent and difficult to reverse; they receive the same threshold as governance changes. Any proposed change must include legal analysis of the effect on existing contributors and users.

---

## 7. The Model RFC Process

This section defines the full process for proposing, reviewing, testing, and adopting changes to model behavior, tool call schema, default Policy Layer rules, and the prompt format.

### 7.1 What Requires an RFC

A Model RFC is required for any of the following:

- Adding a new tool type to the tool call schema
- Modifying an existing tool type's arguments, return values, or error types in a non-backward-compatible way
- Changing the default value of any of the 10 starter rules
- Adding a new default rule
- Removing an existing rule from the default set (even if it remains available as an option)
- Changing the system prompt structure in a way that affects what the AI is instructed to do
- Changing the high-stakes classification criteria
- Changing the audit log schema

A Model RFC is NOT required for:
- Bug fixes to existing tool implementations (e.g., fixing a path validation regex that incorrectly denies valid paths)
- Performance improvements that don't change observable behavior
- Documentation changes
- Adding new backward-compatible fields to existing tool schemas (these require a Safety Subcommittee review, not a full RFC)

### 7.2 RFC Lifecycle Stages

```
DRAFT → SAFETY REVIEW → BETA → TELEMETRY ANALYSIS → COUNCIL VOTE → DEFAULT (or REJECTED)
```

Each stage is described below.

### Stage 1: Draft

The RFC author opens a GitHub issue using the Model RFC template (`.github/ISSUE_TEMPLATE/model_rfc.md`). The RFC must include:

- A clear description of the proposed change
- The motivation: what problem does this solve or what user need does it serve?
- A detailed specification: what specifically changes
- An example interaction showing the before and after behavior
- A security analysis: what is the worst-case outcome if this change is exploited?
- A telemetry proposal: what signals will be collected during beta to evaluate the change?
- A proposed success criterion for graduation to default

The RFC is labeled `rfc-draft` and is open for community comment for **21 days**. Anyone may comment. Substantive objections should explain the specific concern and what would be needed to address it.

The RFC author is responsible for incorporating feedback and updating the RFC document. Substantive changes to the RFC restart the 21-day comment period.

### Stage 2: Safety Review

After 21 days with no further substantive objections, or when the RFC author indicates the RFC is ready, the Safety Subcommittee formally reviews the RFC.

The Subcommittee has **21 days** to complete its review. Possible outcomes:
- **Approved for beta:** The RFC proceeds to Stage 3.
- **Approved for beta with modifications:** The RFC proceeds to Stage 3 with mandatory changes specified by the Subcommittee.
- **Returned for revision:** The Subcommittee has specific concerns that must be addressed before it can be approved for beta. The RFC returns to Stage 1 with the concerns documented.
- **Rejected:** The Subcommittee believes the proposed change should not be adopted. The rejection must be accompanied by a written explanation. A rejected RFC may be re-submitted after 6 months if the concerns have been substantially addressed.

The Subcommittee's review is published as a comment on the RFC issue. If the Subcommittee does not complete its review within 21 days, the RFC is automatically approved for beta — this exists to prevent the Subcommittee from blocking changes through inaction.

### Stage 3: Beta Deployment

The change is implemented and deployed to users who have opted in to the beta program. Beta is **60 days** in duration.

**Opt-in mechanism:** Users opt into beta behavior by setting a configuration flag. Beta behavior is never on by default. Users who have opted in are informed that they are using beta behavior when they start a session.

**Telemetry:** The telemetry signals specified in the RFC are collected from users who have both opted into beta AND opted into anonymous telemetry collection. Telemetry collection requires explicit consent and is documented in the user-facing privacy policy. No telemetry is collected by default.

**Beta rollback:** The Safety Subcommittee may roll back beta behavior at any time if it identifies a safety regression. A beta rollback requires a Subcommittee majority vote and blocks the RFC from proceeding to graduation until the issue is resolved.

### Stage 4: Telemetry Analysis

After the 60-day beta, the Subcommittee analyzes the telemetry data and produces a written analysis assessing:
- Whether the RFC's stated goals were achieved (per the success criteria)
- Whether the change introduced any observed safety regressions
- Whether there were unexpected behaviors observed in the beta population
- A recommendation to the Steering Council: adopt as default, adopt with modifications, extend beta, or reject

The analysis is published publicly within 14 days of the beta period ending.

### Stage 5: Council Vote

The Steering Council votes on whether to adopt the RFC as the new default behavior. The vote is by majority (4/7). The Council takes the Subcommittee's recommendation as advisory.

**If the Subcommittee recommends rejection** and the Council wishes to adopt over the recommendation, the threshold increases to a 6/7 supermajority and the Council must publish a written explanation of why it overrides the recommendation.

**If the Council rejects the RFC:** The behavior returns to the previous default. Users who adopted the beta behavior are notified that it will be removed in 30 days.

**If the Council adopts the RFC:** The behavior is deployed as the new default in the next release. The RFC is closed as accepted. The tool schema documentation, policy rule documentation, and release notes are updated.

### 7.3 Expedited RFC Process

For urgent safety-motivated changes (e.g., a new default rule that closes an observed attack pattern), the Steering Council may, by majority vote, expedite the process:
- Stage 1 comment period: 7 days (instead of 21)
- Safety Subcommittee review: 7 days (instead of 21)
- Beta period: 14 days (instead of 60)

Expedited RFCs are labeled `rfc-expedited`. The relaxed process is acceptable for closing security gaps; it is not acceptable for expanding capabilities.

---

## 8. Conflict Resolution

### 8.1 Technical Disputes Between Contributors

Technical disputes about implementation approach, API design, or similar matters are resolved by the Maintainer(s) responsible for the relevant component. If contributors disagree with a Maintainer's decision, they may escalate to the Steering Council by opening a GitHub Discussion tagged `governance-escalation`. The Council will respond within 14 days.

The Council's decision on a technical dispute is final. Contributors who repeatedly escalate frivolous disputes (as determined by the Council) may have their escalation privileges restricted.

### 8.2 Disputes Between Maintainers

Disputes between Maintainers (about design decisions, review standards, contribution scope) are escalated to the Steering Council. The Council may:
- Designate one Maintainer's position as authoritative for the disputed matter
- Call a broader maintainer vote on the question
- Make a Council decision directly

### 8.3 Disputes Involving the Steering Council

If a contributor believes the Steering Council has acted contrary to this governance document, they may:
1. Open a public GitHub Discussion documenting the concern, the governance document clause they believe was violated, and the specific action taken
2. The Council must respond in writing within 14 days
3. If the contributor is not satisfied with the Council's response, they may request a community vote on the matter (see Section 8.4)

### 8.4 Community No-Confidence Vote

In the event that the community believes the Steering Council is acting contrary to the project's interests or this governance document, a no-confidence vote may be called. To trigger a community no-confidence vote:

- A petition with signatures from at least 20 eligible voters (as defined in Section 3.4) must be submitted to the Council in writing
- The Council must publish the petition publicly and call a vote within 30 days
- The vote is conducted among all eligible voters
- If 60% of voters vote no-confidence, the specific Council member(s) named in the petition are removed and a snap election for their seats is held within 60 days

A no-confidence vote may target individual Council members, not the Council as a body.

### 8.5 Code of Conduct Violations

Reports of conduct violations (harassment, threats, discrimination) are handled by the Council, not through the technical dispute process. Reports go to `conduct@lumenos.org`. The Council has sole authority to determine violations and impose consequences (warnings, temporary bans, permanent bans).

If a conduct violation involves a Council member, that member recuses from the handling of their own case. If the majority of Council members are involved, the Subcommittee Chair mediates.

---

## 9. Amendments to This Document

Amendments to this governance document require:

1. A proposed amendment opened as a GitHub issue, labeled `governance-amendment`, with a clear description of the change and its rationale
2. A 30-day public comment period
3. A 6/7 Steering Council supermajority vote to adopt

Amendments take effect immediately upon adoption unless the amendment specifies a delayed effective date.

This document's version history is maintained in the git history of the repository. Each amendment increments the version number (1.0 → 1.1 → etc.). Major restructurings increment the major version (1.x → 2.0).

**Provisions that cannot be amended without unanimous Council consent (7/7):**
- Section 1 (Principles)
- Section 4.4 (the 6/7 threshold for overriding the Safety Subcommittee's veto)
- Section 11 (the timeline for converting founding seats to elected seats)

These provisions exist to protect the project's core commitments against capture by a supermajority of the Council.

---

## 10. Security Incident Response

### 10.1 What Counts as a Security Incident

For governance purposes, a security incident is one of:

- A reported vulnerability in the Policy Layer that allows the AI to take actions outside its granted capabilities
- A reported vulnerability in the seL4 or Genode layer that allows privilege escalation
- Observed exploitation of a vulnerability in the wild (regardless of whether a report was received)
- A significant prompt injection attack pattern that bypasses Policy Layer enforcement
- A data breach affecting user session data or audit logs

### 10.2 Incident Command Structure

When a security incident is reported, the Safety Subcommittee Chair assumes incident command. The incident team consists of:
- All Safety Subcommittee members
- The maintainer(s) of the affected component
- Any external security researchers involved in the report (with mutual NDA if warranted)
- One Steering Council member designated as the communications lead

### 10.3 Response Timeline

The response timeline from the SECURITY.md document is binding:

| Action | Target |
|--------|--------|
| Acknowledge receipt of report | 48 hours |
| Initial triage and severity classification | 7 days |
| Status update | 14 days |
| Fix developed and reviewed | 30 days (P0/P1) / 90 days (P2/P3) |
| Public disclosure | After fix release, or 90 days from report |

The Safety Subcommittee may adjust these timelines if they cannot be met due to technical complexity, with written notice to the reporter.

### 10.4 P0 Incident Procedure

A P0 incident (Policy Layer bypass — the AI takes actions outside its granted capabilities) triggers the following mandatory steps:

1. **Immediate:** Safety Subcommittee Chair notifies all Council members that a P0 is in progress. No public statement is made.
2. **Within 48 hours:** The Subcommittee assesses the blast radius. Who could be affected? Is there evidence of active exploitation?
3. **Within 72 hours:** A decision on whether to push an emergency patch (for active exploitation) or proceed with the normal fix timeline.
4. **Emergency patch procedure:** An emergency patch may be merged with:
   - Two Policy Layer maintainer reviews (both Safety Subcommittee members)
   - Steering Council Chair informed and not objecting (4-hour window to object)
   - No community comment period (post-hoc review happens after the patch is deployed)
5. **After patch deployment:** A full post-mortem is published within 30 days, covering what happened, how the vulnerability was introduced, and what process changes are being made to prevent recurrence.

### 10.5 Coordinated Disclosure

The project follows the coordinated disclosure policy described in SECURITY.md. The Safety Subcommittee has authority to negotiate disclosure timelines with reporters within the bounds of that policy. If a reporter insists on disclosing before the project is ready to patch, the Subcommittee may:

- Issue a public advisory acknowledging the vulnerability and describing mitigations available to users (if any)
- Accelerate the patch timeline to the extent possible
- Not retaliate against the reporter in any way

### 10.6 Post-Incident Governance Review

After any P0 or P1 incident, the Steering Council conducts a governance review within 60 days: did the governance process make this incident more likely, less likely, or neutral? Were the right people involved in the response? What process changes, if any, are indicated?

The governance review output is a public document.

---

## 11. Transition to Community Governance

### 11.1 The Founding Period

The founding period is five years from this document's effective date (2026-05-19 through 2031-05-18). During the founding period, the three founding seats are not subject to election. This provides stability and continuity while the project establishes its community and technical foundation.

The tradeoff is acknowledged: founding seat holders have more power than elected seat holders during this period. This is mitigated by the elected seats constituting a majority (4/7), the Safety Subcommittee's independence, and the community no-confidence mechanism.

### 11.2 Conversion of Founding Seats

Beginning Year 6 (from 2031-05-19):
- Each founding seat converts to an elected seat at the end of its current holder's term
- The "current holder's term" for founding seats is defined as a 2-year term beginning on the first January 1 after Year 5 ends (i.e., January 1, 2032), with the three founding seats staggered across two election cycles to maintain continuity
- Founding seat holders may not stand for re-election to their own seat upon conversion, but may stand for any other seat

Upon conversion of all three founding seats, the Steering Council is fully elected and this section of the governance document is superseded.

### 11.3 Foundation Incorporation

The Lumen Ora Foundation is intended to incorporate as a 501(c)(3) non-profit (or equivalent in the chosen jurisdiction) within 24 months of the project's first public beta release, or by January 1, 2028, whichever is earlier. Until incorporation:

- Project assets (trademarks, domains, funds) are held by @ericvonbibra in trust for the project
- The Steering Council's governance decisions are binding on the use of those assets
- All financial decisions require Council approval

After incorporation, assets are transferred to the Foundation. The Foundation's board of directors is constituted in a manner consistent with this governance document.

---

## 12. Current Council Roster

*This section is updated in place when the composition changes. The git history records all prior states.*

### Steering Council

| Seat | Holder | Type | Term |
|------|--------|------|------|
| Seat 1 (Founder) | @ericvonbibra | Founding | Founding period (until 2031) |
| Seat 2 | Vacant | Founding | Pending appointment |
| Seat 3 | Vacant | Founding | Pending appointment |
| Seat 4 | Vacant | Elected | First election pending |
| Seat 5 | Vacant | Elected | First election pending |
| Seat 6 | Vacant | Elected | First election pending |
| Seat 7 | Vacant | Elected | First election pending |

*The first election for elected seats will be held within 90 days of the first public beta release, or by January 1, 2027, whichever is earlier.*

*Founding seats 2 and 3 are to be appointed by @ericvonbibra after consultation with early contributors. Nominees will be announced publicly before appointment and the community will have 14 days to raise objections.*

### Safety Subcommittee

| Role | Holder | Notes |
|------|--------|-------|
| Chair | @ericvonbibra (interim) | Interim until at least one elected Council member is seated |
| Member | Vacant | |
| Member | Vacant | |

*The Subcommittee Chair reverts from interim to elected status when the first elected Council members are seated. At that point, the full Subcommittee is constituted through Council appointment.*

### Component Maintainers

| Component | Maintainer(s) |
|-----------|--------------|
| policy-layer | @ericvonbibra |
| inference | Vacant — seeking maintainer |
| context-shell | Vacant — seeking maintainer |
| os-layer | Vacant — seeking maintainer |
| docs | Vacant — seeking maintainer |
| build | Vacant — seeking maintainer |

*If you are interested in becoming a maintainer for a vacant component, open an issue in the repository expressing your interest and linking to your relevant contributions. Maintainers will be appointed by the Council as the contributor community grows.*

---

## Contact

- General governance questions: open a GitHub Discussion
- Conduct reports: `conduct@lumenos.org`
- Security reports: `security@lumenos.org`
- Legal questions: `legal@lumenos.org`

---

*Lumen Ora Governance Document v1.0 — Effective 2026-05-19*
*Maintained by the Steering Council. Amendment history in git log.*
