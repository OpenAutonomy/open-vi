# Security policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: Security → Report a
vulnerability. **Do not open a public issue** for a vulnerability.

Expect a best-effort response from a single maintainer, not a staffed
queue. Fixes land on `main`; there is no backport branch.

## What this software assumes

open-vi is a prototype. **The Abstract Service Bus has no authentication,
no authorization, and no in-process TLS.** open-vi is a STOMP client.
Any peer that can open the same STOMP port can publish and subscribe as
any identity.

`compose/vi.yml` runs the VI image against `BROKER_HOST`. Bind the
broker on a network you already trust. A finding is interesting here if
it lets a peer do something that posture does not already permit.

## In scope

- A hang, crash, or unbounded loop reachable from a peer's XML or STOMP
  frames.
- Isolator accept/reject that treats a malformed command as a valid
  vehicle action.
- A codec turning malformed XML into a plausible-but-wrong domain value
  instead of dropping the message.

## Known limitations, not vulnerabilities

- The codec does not validate against the UCI XSD. Non-conforming XML
  may be parsed into domain structs or dropped; it is not schema-rejected.

## Supported versions

`0.2.0` on `main` is the supported line. The API may still change.
