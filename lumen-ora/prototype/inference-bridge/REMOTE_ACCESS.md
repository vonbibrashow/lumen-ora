# Remote access — implementation notes

Phase 4 item 1: Tailscale-friendly remote access. Status: bridge + dashboard
+ docs done. Tests at Layer 3c in `prototype/test_e2e.py` verify the bridge
binds to a non-loopback interface when `LUMEN_BIND_HOST=0.0.0.0`.

## What shipped

- `bridge.py` — `LUMEN_BIND_HOST` env var (default `127.0.0.1`). When set to
  `0.0.0.0` and `LUMEN_API_TOKEN` is unset, the bridge prints a loud warning
  on stderr and via the logger.
- `static/index.html` — mobile viewport meta, theme-color, safe-area insets,
  responsive layout below 768 px, 16 px input font size (prevents iOS auto-zoom),
  44 px minimum touch targets, sidebar hidden on phones.
- `README.md` + `INSTALL.md` — "Remote access via Tailscale" 5-step recipe.
- `test_e2e.py` — Layer 3c (3 functional tests + 2 setup checks).

## Open items / parallel-agent coordination

The context shell (`prototype/context-shell/shell.py`) currently assumes the
bridge is reachable at `http://127.0.0.1:8765`. For a phone-side or
remote-laptop shell to work over Tailscale, the shell needs to honour
`LUMEN_BRIDGE_URL` (or similar) at startup so users can point it at
`http://<host-magic-dns>:8765`.

# TODO(phase4-tailscale): shell.py should read LUMEN_BRIDGE_URL env var and
# pass the LUMEN_API_TOKEN as a Bearer header on every /infer call. Today
# the shell hard-codes 127.0.0.1:8765 and has no token-injection path. This
# is out of scope for this PR (parallel agent owns shell.py) but is the
# blocking item for shell-from-phone usage. Web dashboard already works
# remotely — this only affects the terminal shell.

The dashboard at `/` is fully usable from a phone today; the terminal shell
remains local-only until the parallel agent wires through `LUMEN_BRIDGE_URL`
and `LUMEN_API_TOKEN`.

## Threat model recap

- `LUMEN_BIND_HOST=0.0.0.0` without `LUMEN_API_TOKEN` is a footgun. The
  startup warning is loud but not blocking — by design, since users on
  trusted single-host LANs may want this for local-only testing.
- The bearer token is the only auth layer. Tailscale provides transport
  encryption + ACLs, not application-layer auth.
- The policy engine still gates every tool call. A leaked token cannot
  bypass policy denies (e.g. `/etc/passwd` read attempts are still blocked).
