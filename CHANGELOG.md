# Changelog

## [0.1.0] - 2026-08-17

First tagged source release. Canonical home is
[OpenAutonomy/open-vi](https://github.com/OpenAutonomy/open-vi).

Isolator owns A-GRA sequences, including the route ladder and File*.
`PlatformPort` is vehicle I/O: snapshot, flight command, TSPI, status /
faults, and QNH. Shared values live in `open_vi.domain`. Stub is the
default backend; PX4 SITL does telemetry and `WAYPOINT_FOLLOWING`.

[0.1.0]: https://github.com/OpenAutonomy/open-vi/releases/tag/v0.1.0
