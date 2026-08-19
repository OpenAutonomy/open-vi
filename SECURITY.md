# Security policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: Security → Report a
vulnerability. **Do not open a public issue** for a vulnerability.

Expect a best-effort response from a single maintainer, not a staffed
queue. Fixes land on `main`; there is no backport branch.

## What this software assumes

open-vi is a prototype. **The Abstract Service Bus has no authentication,
no authorization, and no in-process TLS.** `compose/asb.yml` starts
ActiveMQ with no credentials so it matches a typical local ASB. Any peer
that can open STOMP `:61613` can publish and subscribe as any identity.

`compose/asb.yml` publishes STOMP, OpenWire, and the console on
loopback only. Bind any other broker the same way, or put it on a
network you already trust. `compose/vi.yml` runs the VI image as a
STOMP client on that broker; it does not add authentication.
A finding is interesting here if it lets a peer do something that
posture does not already permit.

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
- `COMPLIANCE_MODE` only selects status-ladder length. It is not an
  access-control switch.

## Supported versions

`0.1.0` on `main` is the supported line. The API may still change.
