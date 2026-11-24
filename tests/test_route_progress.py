"""Route progress: the port contract, and the segment it names.

``RoutePlanExecutionStatus`` requires ``CurrentSegment`` — the path and
segment the vehicle is navigating. That is vehicle state, so it enters
through ``PlatformPort``; the codec turns an index into the
``PathSegmentID`` that ``build_path_element`` assigned.

The index is into the waypoint list *as submitted*. PX4 trims a
leading prefix before upload, so its mission sequence is not that
index, and the offset is the part most likely to be got wrong.
"""

from __future__ import annotations

from uuid import UUID
from xml.etree import ElementTree as ET

import pytest

from open_vi.codec.control_status import build_route_plan_execution_status
from open_vi.codec.ns import NS
from open_vi.codec.path import build_path_element, segment_id_for_index
from open_vi.domain import (
    FlightCommandRequest,
    PlanExecutionSnapshot,
    RouteProgress,
    Waypoint,
)
from open_vi.identity import SystemIdentity
from open_vi.platform import StubPlatform

IDENTITY = SystemIdentity.named("open-vi", "open-vi")
ROUTE = UUID(int=0xB0)


def _waypoints(count: int) -> tuple[Waypoint, ...]:
    return tuple(
        Waypoint(
            latitude_deg=38.0 + index * 0.01,
            longitude_deg=-77.0 - index * 0.01,
            altitude_m=120.0,
        )
        for index in range(count)
    )


def _segments(xml: bytes) -> dict[str, str]:
    """``{element name: SegmentID hex}`` for the segment elements."""
    data = ET.fromstring(xml).find(f"{{{NS}}}MessageData")
    assert data is not None
    out = {}
    for name in ("PreviousSegment", "CurrentSegment", "NextSegment"):
        node = data.find(f"{{{NS}}}{name}")
        if node is not None:
            segment = node.find(f"{{{NS}}}SegmentID/{{{NS}}}UUID")
            assert segment is not None and segment.text
            out[name] = segment.text
    return out


# --- the index -> id rule has one home -------------------------------


@pytest.mark.parametrize("count", [1, 2, 5])
def test_segment_ids_match_the_path_that_defined_them(count: int) -> None:
    """A named segment must be one the Path actually contains.

    If these two drifted, a status message would name a segment id
    that appears nowhere in the route it refers to.
    """
    path = build_path_element(_waypoints(count))
    # Each segment's own id is a direct child of PathSegment. The one
    # inside NextPathSegment is a forward reference, not an identity,
    # so it must not be collected here.
    in_path = []
    for segment in path.findall(f"{{{NS}}}PathSegment"):
        own = segment.find(f"{{{NS}}}PathSegmentID/{{{NS}}}UUID")
        assert own is not None and own.text
        in_path.append(own.text)
    expected = [segment_id_for_index(i).hex for i in range(count)]
    assert in_path == expected

    # And the forward references chain to the next segment's id.
    links = [
        node.text
        for node in path.findall(
            f"{{{NS}}}PathSegment/{{{NS}}}NextPathSegment/"
            f"{{{NS}}}PathSegmentID/{{{NS}}}UUID"
        )
    ]
    assert links == expected[1:]


# --- Stub ------------------------------------------------------------


def test_stub_reports_nothing_before_a_route() -> None:
    assert StubPlatform().active_route_progress() is None


def test_stub_reports_the_first_segment_uncaptured() -> None:
    """A stationary vehicle holding a route is at its first segment."""
    stub = StubPlatform()
    stub.submit_flight_command(
        FlightCommandRequest(
            command_id=UUID(int=1),
            capability_id=UUID(int=2),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=_waypoints(3),
        )
    )
    progress = stub.active_route_progress()
    assert progress == RouteProgress(
        waypoint_index=0, total_waypoints=3, captured=False
    )


def test_stub_advance_hook_walks_and_stops_at_the_last() -> None:
    stub = StubPlatform()
    stub.submit_flight_command(
        FlightCommandRequest(
            command_id=UUID(int=1),
            capability_id=UUID(int=2),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=_waypoints(2),
        )
    )
    stub.advance_route_progress()
    first = stub.active_route_progress()
    assert first is not None and first.waypoint_index == 1
    stub.advance_route_progress()
    second = stub.active_route_progress()
    assert second is not None and second.waypoint_index == 1


def test_stub_progress_outlives_the_activity() -> None:
    """An aborted route still has to say where it stopped.

    §1.2.5.6 requires a RoutePlanExecutionStatus carrying CANCELED on
    VI abort, and CurrentSegment is mandatory on it. Clearing progress
    with the activity would make that message impossible to form.
    """
    stub = StubPlatform()
    command_id = UUID(int=1)
    stub.submit_flight_command(
        FlightCommandRequest(
            command_id=command_id,
            capability_id=UUID(int=2),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=_waypoints(3),
        )
    )
    stub.fail_flight_command(command_id)
    assert stub.active_flight_activity() is None
    assert stub.active_route_progress() is not None


# --- the emitted segments --------------------------------------------


def _status(progress: RouteProgress | None) -> bytes:
    return build_route_plan_execution_status(
        IDENTITY,
        PlanExecutionSnapshot(
            execution_state="EXECUTING",
            route_plan_id=ROUTE,
            progress=progress,
        ),
    )


def test_no_progress_emits_no_segments() -> None:
    """There is no partial form: CurrentSegment is mandatory."""
    assert _segments(_status(None)) == {}


def test_middle_of_route_names_current_and_next() -> None:
    found = _segments(
        _status(RouteProgress(waypoint_index=1, total_waypoints=3))
    )
    assert found == {
        "CurrentSegment": segment_id_for_index(1).hex,
        "NextSegment": segment_id_for_index(2).hex,
    }


def test_last_waypoint_has_no_next_segment() -> None:
    found = _segments(
        _status(RouteProgress(waypoint_index=2, total_waypoints=3))
    )
    assert set(found) == {"CurrentSegment"}
    assert found["CurrentSegment"] == segment_id_for_index(2).hex


def test_previous_segment_is_never_emitted() -> None:
    """ActualCaptureTime is mandatory inside it and is not recorded.

    Pinned so adding PreviousSegment later is a deliberate act that
    also supplies the capture time, rather than a plausible-looking
    element with an invented timestamp.
    """
    for index in range(3):
        progress = RouteProgress(
            waypoint_index=index, total_waypoints=3, captured=True
        )
        assert "PreviousSegment" not in _segments(_status(progress))
