# Changelog

## [Unreleased]

### Removed

- `compose/asb.yml`.
- `COMPLIANCE_MODE`. Route, query, and control always publish
  `QUEUED`, `PROCESSING`, then `COMPLETED`.

### Added

- PX4 Flight Autonomy for waypoint following: envelope
  validation with Volume `ValidationResult` reasons,
  `WaypointFollowingPerformanceProfile` min/max altitude on
  `MA_FlightCapability`, and `SENS_BARO_QNH` on
  `MA_SystemManagementRequest`.
- [docs/FEATURES.md](docs/FEATURES.md): ASK 5.0a Vehicle Interface
  Volume coverage, structured as the volume's compliance IDs,
  §1.2 interactions, and §1.3.1 MMS.
- Activity UPDATE on `MA_FlightCommand`: Isolator matches the live
  `ActivityID`, Stub and PX4 replace the path without minting a new
  activity, and `MA_FlightActivity` is published as `UPDATED`.
  Capability NEW while an activity is live is rejected; replan is
  Activity UPDATE only.
- MkDocs on GitHub Pages:
  [openautonomy.github.io/open-vi](https://openautonomy.github.io/open-vi/).
- Container image on GHCR (`ghcr.io/openautonomy/open-vi`), built from
  `Containerfile` on a public push to `main`.

## [0.1.0] - 2026-08-17

First tagged source release. Canonical home is
[OpenAutonomy/open-vi](https://github.com/OpenAutonomy/open-vi).

Isolator owns A-GRA sequences, including the route ladder and File*.
`PlatformPort` is vehicle I/O: snapshot, flight command, TSPI, status /
faults, and QNH. Shared values live in `open_vi.domain`. Stub is the
default backend; PX4 SITL does telemetry and `WAYPOINT_FOLLOWING`.

[0.1.0]: https://github.com/OpenAutonomy/open-vi/releases/tag/v0.1.0
