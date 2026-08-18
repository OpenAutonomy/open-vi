# Adding a vehicle adapter

An adapter owns the vehicle protocol: the link, framing, and mapping into
`open_vi.domain`. Isolator owns A-GRA sequences, including the route ladder
and File*. A new vehicle is a new `PlatformPort`; it is not a change to
Isolator, codec, or the bus. The port methods are in [PLATFORM.md](PLATFORM.md).
PX4 is the worked example ([PX4.md](PX4.md), `src/open_vi/platform/px4.py`).

## Contract

Implement snapshot, flight command, TSPI, status, faults, and QNH.
`poll_command_updates()` and `close()` have defaults. Use `StubPlatform` as
a reference for accept and reject, not for routes.

The design depends on four rules:

1. **Do not parse UCI in the adapter.** Isolator and codec own XML. Map
   MAVLink (or anything else) to domain types only.
2. **Do not import the bus or Isolator handlers.** The adapter is called
   through `PlatformPort` and returns domain values.
3. **Do not implement the route ladder.** Isolator `RouteStore` owns
   upload → prepare → activate → deactivate and stored `MA_RoutePlan`
   bytes. ACTIVATE does not call the vehicle.
4. **Do not put `inject_contingency` on the ABC.** That is Stub-only, for
   unit tests. Report readiness through `snapshot()`.

## Steps

1. Add a module under `src/open_vi/platform/` and implement `PlatformPort`.
2. Wire it in `make_platform()` / CLI `--platform` (`open_vi/__main__.py`).
   Import the adapter inside that branch so `import open_vi.platform` does
   not load it.
3. Test the adapter in isolation (unit or SITL). Keep Isolator sequence
   coverage on `StubPlatform`.
4. List the backend in [PLATFORM.md](PLATFORM.md).

## Checklist

- [ ] Snapshot, flight command, TSPI, status/faults, and QNH implemented
- [ ] Control modes and readiness match what Isolator should advertise
- [ ] Flight commands return a valid `processing_state`
- [ ] `get_vehicle_state()` supplies the fields TSPI outs need
- [ ] No route ladder or `MA_RoutePlan` store on the adapter
- [ ] Isolator unchanged except construction / selection of the backend
