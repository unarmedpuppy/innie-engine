# ADR-0039 — Internal Docker Network Hostnames for Gitea Communication

**Status:** Accepted
**Date:** 2026-03

---

## Context

The Gitea instance runs as a Docker container on `my-network`. External access is via
`gitea.server.unarmedpuppy.com` — Traefik on port 443 (HTTPS) and port 2223 (SSH, mapped from
host port 2223 to container port 22).

From inside a container on `my-network`, the external hostname resolves to the host's external IP.
Two failure modes were observed:

1. **SSH timeout**: `ssh git@gitea.server.unarmedpuppy.com -p 2223` from inside the container
   times out. The connection routes out through the host NAT and back — hairpin NAT — which does
   not work reliably on this host configuration.
2. **HTTPS unreliable**: API calls to the external hostname were intermittently failing from
   inside containers on `my-network`.

Direct internal container-to-container communication on `my-network` is reliable and avoids the
NAT path entirely.

---

## Decision

All Gitea communication from within containers uses internal Docker network hostnames:

| Protocol | Internal address | Purpose |
|----------|-----------------|---------|
| HTTPS API | `http://gitea:3000/api/v1/...` | Gitea REST API calls (repo listing, etc.) |
| HTTPS clone | `http://gitea:3000/homelab/<repo>.git` | Git clone and pull over HTTP |
| SSH | `ssh://git@gitea:2222/homelab/agent-memory.git` | Agent memory remote push/pull |

SSH config in `/home/appuser/.ssh/config` maps `Host gitea` to port 2222 (the container's
internal SSH port, not the host-mapped port 2223).

The git credential store includes an entry for `http://gitea:3000` alongside the external hostname,
so HTTPS clone/pull operations authenticate correctly without prompting.

---

## Alternatives Considered

### Use external hostname (`gitea.server.unarmedpuppy.com`)

Rejected. SSH connections time out due to hairpin NAT. HTTPS API calls were unreliable. External
hostnames are the wrong tool for same-host container-to-container communication.

### Use `host.docker.internal`

Would bypass the NAT problem for some cases. Rejected: requires adding `extra_hosts` to every
compose file that needs Gitea access. The internal Docker network hostname is cleaner and works
without any additional configuration on the consuming container.

### Expose Gitea on standard ports (80/443) internally

Would allow using the external hostname on standard ports from inside the network. Rejected:
reconfiguring Gitea's internal listening ports would affect the external Traefik routing and
is unnecessary when the internal hostname works as-is.

---

## Consequences

**Positive:**
- Reliable Gitea connectivity from all containers on `my-network` — no NAT, no timeout risk.
- SSH push/pull to the agent-memory remote works correctly on first try.
- No `extra_hosts` configuration required on consuming containers.

**Negative:**
- Clone URLs inside the container use `http://gitea:3000` — these are not usable from outside
  Docker. Operators cloning from a workstation must use the external hostname. This can cause
  confusion when reading remote URLs from inside the container (`git remote -v` shows the internal
  URL).
- SSH deploy keys must still be added to the Gitea repo via the external UI (`gitea.server.
  unarmedpuppy.com`) using the public key generated inside the container. The setup process
  requires one manual step that crosses the internal/external boundary.
