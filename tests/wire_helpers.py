"""Deterministic capture of every message open-vi puts on the bus.

The conformance tests all work from one corpus: drive Isolator across
its outbound surface with the in-process bus and Stub backend, then
assert on what was actually published rather than on hand-built
fixtures. Fixtures drift from the publish path; this does not.

Timestamps and generated UUIDs are frozen so the same run produces the
same bytes, which is what makes the golden corpus reviewable.
"""

from __future__ import annotations

import importlib
import itertools
import pkgutil
import re
import uuid
from uuid import UUID

import pytest

import open_vi.codec as codec_pkg
from open_vi.asb import InMemoryAsb
from open_vi.codec.command import build_sample_waypoint_command
from open_vi.codec.control import build_sample_control_request
from open_vi.codec.mts import (
    MT_ACTIVATION_COMMAND,
    MT_CONTROL_REQUEST,
    MT_FLIGHT_COMMAND,
    MT_MA_RESPONSE,
    MT_MA_TASK,
    MT_QUERY_DATA_REQUEST,
    MT_ROUTE_PLAN,
    MT_ROUTE_VALIDATION_COMMAND,
    MT_SERVICE_STATUS,
    MT_SERVICE_STATUS_DATA_REQUEST,
    MT_SUBSYSTEM_STATUS_DATA_REQUEST,
    MT_SYSTEM_MGMT_REQUEST,
    MT_TASK_COMMAND,
)
from open_vi.codec.notification import build_sample_ma_response
from open_vi.codec.query import build_sample_query_data_request
from open_vi.codec.route import (
    build_sample_route_activation_command,
    build_sample_route_plan,
    build_sample_route_validation_command,
)
from open_vi.codec.status import (
    build_sample_service_status,
    build_sample_service_status_data_request,
    build_sample_subsystem_status_data_request,
)
from open_vi.codec.system_mgmt import build_sample_system_management_request
from open_vi.codec.task import build_ma_task, build_sample_task_command
from open_vi.config import IsolatorConfig
from open_vi.identity import SystemIdentity
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform

FROZEN_TIME = "2026-01-02T03:04:05.678Z"
_UUID_SEED = 0xD000

# Fixed ids so the corpus is stable and greppable.
CMD_ID = UUID(int=0xC1)
CAPABILITY_ID = UUID(int=0xC0)
ROUTE_PLAN_ID = UUID(int=0xB0)
MISSION_PLAN_ID = UUID(int=0xB1)
REQUEST_ID = UUID(int=0xA1)
TASK_ID = UUID(int=0xA2)
RESPONSE_ID = UUID(int=0xA3)
SERVICE_ID = UUID(int=0x51)
SUBSYSTEM_ID = UUID(int=0x52)
# A peer's service id. Isolator suppresses the reply when an inbound
# ServiceStatus carries its own, to avoid answering its own heartbeat.
PEER_SERVICE_ID = UUID(int=0x5F)
IDLE_ACTIVITY_ID = UUID(int=0xE0)
# A peer controller, for the leg where control is already assigned and
# a second ACQUIRE is rejected.
PEER_CONTROLLER_ID = UUID(int=0x6F)


def peer_identity() -> SystemIdentity:
    """A publisher that is not Isolator.

    ``_ingest_task`` drops an ``MA_Task`` whose MessageHeader carries
    Isolator's own SystemID, so an MA_Task built from ``iso.identity``
    is suppressed as loopback and drives nothing. §1.2.2.5 has MA send
    it, so the corpus must too.
    """
    return SystemIdentity.named("open-ma", "open-ma")


def task_without_task_id(identity: SystemIdentity) -> bytes:
    """A well-formed MA_Task with its TaskID removed.

    Drives the leg §1.2.2.5 requires and the VI used to drop in
    silence: the reply carries ``NotificationDetail``, which Table
    1-10 requires and which an acknowledgement cannot truthfully give
    -- every ``CannotComplyEnum`` value says why something failed.
    """
    body = build_ma_task(identity, task_id=TASK_ID)
    stripped = re.sub(rb"<TaskID>.*?</TaskID>", b"", body, count=1)
    assert stripped != body, "MA_Task layout changed; TaskID not removed"
    return stripped


def _codec_modules() -> list[object]:
    mods = [importlib.import_module("open_vi.codec.xmlutil")]
    for m in pkgutil.iter_modules(codec_pkg.__path__):
        mods.append(importlib.import_module(f"open_vi.codec.{m.name}"))
    return mods


def freeze_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze timestamps and generated UUIDs across the codec and Stub.

    ``utc_now`` and ``uuid4`` are imported into each module by name, so
    patching the definition site would not reach the callers. Every
    binding is replaced instead.
    """
    counter = itertools.count(_UUID_SEED)

    def fake_uuid4() -> UUID:
        return UUID(int=next(counter))

    # Every module that bound ``utc_now`` or ``uuid4`` by name. Missing
    # one leaves a random UUID in the corpus and the golden files churn.
    extra = (
        "open_vi.platform.stub",
        "open_vi.isolator.handlers.route",
        "open_vi.isolator.handlers.query",
        "open_vi.isolator.handlers.flight_command",
        "open_vi.isolator.publishers",
        "open_vi.isolator.state",
        "open_vi.domain.tspi",
    )
    targets = list(_codec_modules())
    targets += [importlib.import_module(name) for name in extra]
    for mod in targets:
        if hasattr(mod, "utc_now"):
            monkeypatch.setattr(mod, "utc_now", lambda: FROZEN_TIME)
        if hasattr(mod, "uuid4"):
            monkeypatch.setattr(mod, "uuid4", fake_uuid4)
    monkeypatch.setattr(uuid, "uuid4", fake_uuid4)


def _inbound(identity: object) -> list[tuple[str, bytes]]:
    """Scripted inbound traffic that exercises the reply surface.

    Order matters. The route plan must be ingested before the
    activation ladder, and ACTIVATE is rejected from any state but
    ``READY_FOR_ACTIVATION``, so every rung is walked in turn.
    """
    activation_steps = (
        "PREPARE_FOR_UPLOAD",
        "UPLOAD",
        "PREPARE_FOR_ACTIVATION",
        "ACTIVATE",
    )
    return [
        (
            MT_ROUTE_PLAN,
            build_sample_route_plan(identity, route_plan_id=ROUTE_PLAN_ID),
        ),
        *(
            (
                MT_ACTIVATION_COMMAND,
                build_sample_route_activation_command(
                    identity,
                    command_id=CMD_ID,
                    mission_plan_id=MISSION_PLAN_ID,
                    route_plan_id=ROUTE_PLAN_ID,
                    command_type=step,
                ),
            )
            for step in activation_steps
        ),
        (
            MT_ROUTE_VALIDATION_COMMAND,
            build_sample_route_validation_command(
                identity, command_id=CMD_ID, route_plan_id=ROUTE_PLAN_ID
            ),
        ),
        (
            MT_FLIGHT_COMMAND,
            build_sample_waypoint_command(
                identity, command_id=CMD_ID, capability_id=CAPABILITY_ID
            ),
        ),
        (
            # All three kinds, so the reply covers AirfieldReport,
            # MA_RoutePlan and the File* pair as well as capability.
            MT_QUERY_DATA_REQUEST,
            build_sample_query_data_request(
                identity,
                request_id=REQUEST_ID,
                message_types=(
                    "MA_FLIGHT_CAPABILITY",
                    "MA_ROUTE_PLAN",
                    "AIRFIELD_REPORT",
                ),
            ),
        ),
        (
            MT_CONTROL_REQUEST,
            build_sample_control_request(identity, request_id=REQUEST_ID),
        ),
        (
            MT_TASK_COMMAND,
            build_sample_task_command(
                identity,
                command_id=CMD_ID,
                task_id=TASK_ID,
                capability_id=CAPABILITY_ID,
            ),
        ),
        # From a peer: Isolator drops its own MA_Task as loopback.
        (MT_MA_TASK, build_ma_task(peer_identity(), task_id=TASK_ID)),
        (
            MT_MA_RESPONSE,
            build_sample_ma_response(identity, response_id=RESPONSE_ID),
        ),
        (
            MT_SYSTEM_MGMT_REQUEST,
            build_sample_system_management_request(
                identity, request_id=REQUEST_ID
            ),
        ),
        (
            # Peer heartbeat; Isolator replies with its own ServiceStatus.
            MT_SERVICE_STATUS,
            build_sample_service_status(identity, service_id=PEER_SERVICE_ID),
        ),
        (
            MT_SERVICE_STATUS_DATA_REQUEST,
            build_sample_service_status_data_request(
                identity, request_id=REQUEST_ID
            ),
        ),
        (
            MT_SUBSYSTEM_STATUS_DATA_REQUEST,
            build_sample_subsystem_status_data_request(
                identity, request_id=REQUEST_ID
            ),
        ),
    ]


def capture_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[str]]:
    """Every XML body Isolator publishes, keyed by message type."""
    freeze_wire(monkeypatch)
    bus = InMemoryAsb()
    platform = StubPlatform(service_id=SERVICE_ID, subsystem_id=SUBSYSTEM_ID)
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=False,
        ),
    )
    # IsolatorState builds these with field(default_factory=uuid.uuid4),
    # which captures the function object at class-definition time, so
    # patching the module attribute cannot reach it. Assign instead.
    iso.ctx.state.capability_id = CAPABILITY_ID
    iso.ctx.state.idle_activity_id = IDLE_ACTIVITY_ID

    iso.attach()

    # Outbound surface Isolator exposes for one-shot publication.
    iso.advertise_once()
    iso.publish_flight_capability_once()
    iso.publish_capability_status_once()
    iso.publish_status_package_once()
    iso.publish_vehicle_state_once()
    iso.publish_subsystem_status_once()
    iso.publish_faults_once()
    iso.publish_command_updates_once()

    # Replies driven by inbound traffic.
    for message_type, xml in _inbound(iso.identity):
        iso.dispatch(message_type, xml.decode("utf-8"))

    # Re-publish the status package now that a plan is live: the
    # Route/Mission execution statuses only emit with a snapshot.
    iso.publish_status_package_once()

    # DEACTIVATE last: MissionPlanActivationStatus only emits on
    # ACCEPTED -> DEACTIVATED, which needs the plan already activated.
    iso.dispatch(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=CMD_ID,
            mission_plan_id=MISSION_PLAN_ID,
            route_plan_id=ROUTE_PLAN_ID,
            command_type="DEACTIVATE",
        ).decode("utf-8"),
    )

    # Unsuccessful legs last, so they cannot perturb the frozen UUID
    # sequence of anything above. Both carry a reason element that no
    # successful reply does, and neither the XSD nor Table 1-38 can
    # tell whether it is present.
    #
    # A second ACQUIRE from another controller is rejected, because the
    # first one in _inbound already holds the capability.
    iso.dispatch(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=REQUEST_ID,
            controller_system_id=PEER_CONTROLLER_ID,
        ).decode("utf-8"),
    )
    iso.dispatch(
        MT_MA_TASK, task_without_task_id(peer_identity()).decode("utf-8")
    )

    # A real fault, last. Tables 1-4 and 1-5 require nine fields of
    # MA_Fault, and six of them describe a fault that exists: a
    # CLEARED / NO_FAULT sentinel has no detection time, no occurrence
    # count, and no subsystem it occurred within. Publishing only the
    # sentinel left the corpus unable to speak to the interaction the
    # tables are about, which is reporting a fault.
    platform.inject_contingency("MECHANICAL_DAMAGE")
    iso.publish_faults_once()

    return {mt: list(bodies) for mt, bodies in sorted(bus.published.items())}
