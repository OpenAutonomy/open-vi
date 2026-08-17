# Adding a vehicle adapter

A new vehicle is a new `PlatformPort` implementation. Do not fork the Isolator,
codec, or ASB layers. Do not implement the A-GRA route ladder — Isolator
`RouteStore` owns upload → prepare → activate → deactivate and File*.

Parent: [PLATFORM.md](PLATFORM.md).

---

## Steps

1. **Implement `PlatformPort`** in `src/open_vi/platform/` (see `px4.py`).
   Map vehicle protocols (MAVLink, …) to `open_vi.domain` types only.
2. **Fill the vehicle methods:** snapshot, flight command, TSPI, status /
   faults, and QNH. `poll_command_updates()` and `close()` have defaults.
   Use `StubPlatform` as a behavioral reference for accept/reject — not for
   routes.
3. **Wire construction** via `make_platform()` / CLI `--platform`
   (see `open_vi/__main__.py`). Import the adapter inside that factory
   branch so `import open_vi.platform` does not load it.
4. **Test** the adapter in isolation (unit / SITL). Keep Isolator sequence
   coverage on `StubPlatform`.

---

## Rules

| Do | Don’t |
| --- | --- |
| Keep UCI out of the adapter (Isolator + codec own XML) | Import `stomp`, ActiveMQ, or Isolator handlers |
| Put vehicle I/O only in the adapter module | Put MAVLink/PX4 under `isolator/` or `codec/` |
| Report readiness via `snapshot()` | Add harness APIs to the ABC (`inject_contingency` stays Stub-only) |
| Return the same domain DTO shapes as Stub | Invent parallel status types for the Isolator |
| Implement snapshot / command / TSPI / status / QNH | Copy a route state machine or store `MA_RoutePlan` bytes |

---

## Checklist

- [ ] `PlatformPort` vehicle methods implemented (snapshot, flight command,
      TSPI, status/faults, QNH)
- [ ] Control modes / readiness match what Isolator should advertise
- [ ] Flight commands return valid `processing_state`
- [ ] `get_vehicle_state()` supplies fields needed for TSPI outs
- [ ] No route ladder / `MA_RoutePlan` store on the adapter
- [ ] Isolator unchanged except construction / selection of the backend
- [ ] Docs: list the backend in [PLATFORM.md](PLATFORM.md) (PX4 reference: [PX4.md](PX4.md))
