## Summary

<!-- What does this PR do? 1-3 sentences. Link the issue it closes if applicable. -->

Closes #

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (existing behavior changes in a way that requires users to update something)
- [ ] Policy Layer change (requires two maintainer reviews including one Safety Subcommittee member)
- [ ] Documentation update
- [ ] Refactor (no behavior change, no new functionality)
- [ ] Build system / dependency update

## What Changed

<!-- Be specific. "Updated the thing" is not useful. "Changed the path validation regex in the
     filesystem tool from X to Y to prevent directory traversal via Unicode normalization" is useful. -->

## Testing

<!-- How did you verify this change works? Be specific about what you tested and on what hardware.
     "I tested it" is not sufficient. "I ran `cargo test` (all tests pass), then manually tested
     the file-read tool with a path traversal attempt on NixOS 24.11 / x86-64" is sufficient. -->

- [ ] Existing tests pass (`cargo test` / `pytest` / equivalent)
- [ ] I added new tests for this change
- [ ] I cannot add tests because: <!-- explain why -->
- [ ] I tested manually on: <!-- hardware + OS -->

## Policy Layer Impact

<!-- If this PR touches the Policy Layer, the tool call schema, the audit log format, or model
     behavior: answer these. Otherwise delete this section. -->

- [ ] This change was preceded by a Model RFC (link: #)
- [ ] This change modifies a Policy Layer rule (describe the change below)
- [ ] This change modifies the audit log format
- [ ] This change modifies the tool call JSON Schema
- [ ] Two maintainer reviews obtained (required for Policy Layer changes)

**Policy change description:**
<!-- What rule changed? What behavior is now permitted or denied that wasn't before? -->

## Documentation

- [ ] I updated relevant documentation in `docs/`
- [ ] No documentation update is needed (explain why)

## Checklist

- [ ] My code follows the style guidelines in CONTRIBUTING.md
- [ ] I have run `cargo fmt` / `cargo clippy` / `ruff` / equivalent
- [ ] My commits are signed (GPG), or this is not a Policy Layer change
- [ ] I have not included model weight files, secrets, or personally identifiable information
- [ ] I have read CONTRIBUTING.md and my PR follows its requirements

---

<!-- Reviewer guidance: Policy Layer changes require two reviews, one from a Safety Subcommittee
     member. Use the "Policy Layer change" label. Performance-sensitive changes should be
     benchmarked on at least one target hardware platform before merging. -->
