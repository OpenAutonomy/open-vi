# Platforms

A platform is one `PlatformPort` implementation. Isolator owns A-GRA
sequences. The port contract is in [PLATFORM.md](../PLATFORM.md). How
to add a backend is in [ADDING_A_VEHICLE.md](../ADDING_A_VEHICLE.md).

Isolator Volume coverage is [FEATURES.md](../FEATURES.md). Each
backend has its own README and FEATURES.

| Backend | README | Features |
| --- | --- | --- |
| `StubPlatform` | [stub](stub/README.md) | [FEATURES](stub/FEATURES.md) |
| `Px4MavlinkAdapter` | [px4](px4/README.md) | [FEATURES](px4/FEATURES.md) |

Only one backend is wired at a time (`make_platform()` / `--platform`).
`import open_vi.platform` loads the port and Stub. PX4 loads only
inside `make_platform("px4")`.
