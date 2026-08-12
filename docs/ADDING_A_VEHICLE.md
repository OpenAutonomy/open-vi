# Adding a vehicle adapter

A new vehicle is a new `PlatformPort` implementation. Do not fork the Isolator,
codec, or ASB layers.

Parent: [PLATFORM.md](PLATFORM.md).

---

## Steps

1. **Implement `PlatformPort`** in `src/open_vi/platform/` (see `px4.py`).
   Map vehicle protocols (MAVLink, …) to the DTOs in `port.py` only.
2. **Fill every abstract method.** Use `StubPlatform` as a behavioral
   reference for accept/reject and route state transitions.
3. **Wire construction** via `make_platform()` / CLI `--platform`
   (see `open_vi/__main__.py`).
4. **Export** from `platform/__init__.py` if the type is public.
5. **Test** the adapter in isolation (unit / SITL). Keep Isolator sequence
   coverage on `StubPlatform`.

---

## Rules

| Do | Don’t |
| --- | --- |
| Keep UCI out of the adapter (Isolator + codec own XML) | Import `stomp`, ActiveMQ, or Isolator handlers |
| Put vehicle I/O only in the adapter module | Put MAVLink/PX4 under `isolator/` or `codec/` |
| Report readiness via `snapshot()` | Add harness APIs to the ABC (`inject_contingency` stays Stub-only) |
| Return the same DTO shapes as Stub | Invent parallel status types for the Isolator |

---

## Checklist

- [ ] All `PlatformPort` methods implemented
- [ ] Control modes / readiness match what Isolator should advertise
- [ ] Flight commands and route activation return valid `processing_state` /
      plan states
- [ ] `get_vehicle_state()` supplies fields needed for TSPI outs
- [ ] Isolator unchanged except construction / selection of the backend
- [ ] Docs: list the backend in [PLATFORM.md](PLATFORM.md) (PX4 reference: [PX4.md](PX4.md))
