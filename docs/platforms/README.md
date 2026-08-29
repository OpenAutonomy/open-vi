# Platforms

A platform is one `PlatformPort` implementation. Isolator owns A-GRA
sequences. The port contract is in [PLATFORM.md](../PLATFORM.md). How
to add a backend is in [ADDING_A_VEHICLE.md](../ADDING_A_VEHICLE.md).

Volume coverage is [FEATURES.md](../FEATURES.md) (Sequence,
Execution, Backend). Each adapter page is the Backend column
for that vehicle.

| Backend | README | Features |
| --- | --- | --- |
| `StubPlatform` | [stub](stub/README.md) | [FEATURES](stub/FEATURES.md) |
| `Px4MavlinkAdapter` | [px4](px4/README.md) | [FEATURES](px4/FEATURES.md) |

Only one backend is wired at a time (`make_platform()` / `--platform`).
`import open_vi.platform` loads the port and Stub. PX4 loads only
inside `make_platform("px4")`.
