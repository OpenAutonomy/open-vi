"""Airfields, runways and their takeoff/landing routes.

A-GRA calls this pre-loaded, pre-validated data: §1.2.6.3 has MA query
Flight Autonomy for "pre-loaded and pre-validated Airfield and Take
off and Landing (TO/L) route information stored within FA", and
§1.2.5.2 forbids MA uploading route plans for takeoff, departure,
approach or landing because those phases are safety critical.

These are the domain shapes. :mod:`open_vi.fa.airfields` reads them
from a store and the codec projects them onto ``AirfieldReport`` and
``MA_RoutePlan``, which §1.2.6.3 requires to cross-reference each
other by ``AirfieldID`` and ``RunwayID``.

Degrees here, as everywhere in the domain; radians begin at the codec.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from open_vi.domain.flight import Waypoint


@dataclass(frozen=True)
class RunwayCoordinates:
    """A-GRA ``RunwayCoordinatesType``: Start, Threshold, Limit.

    Only ``start`` is required by the schema. ``threshold`` is the
    displaced threshold where one exists, and ``limit`` is the far end
    beyond which the runway is unusable.
    """

    start: Waypoint
    limit: Waypoint | None = None
    threshold: Waypoint | None = None

    @property
    def path(self) -> tuple[Waypoint, ...]:
        """Start to limit, skipping absent points."""
        points = [self.start, self.threshold, self.limit]
        return tuple(p for p in points if p is not None)


@dataclass(frozen=True)
class Runway:
    """One runway, and the TO/L routes that use it."""

    runway_id: uuid.UUID
    direction_deg: float
    available_length_m: float
    takeoff: RunwayCoordinates
    landing: RunwayCoordinates
    takeoff_route_id: uuid.UUID
    landing_route_id: uuid.UUID
    status: str = "OPERATIONAL"
    """A-GRA ``RunwayStatusEnum``."""

    label: str = "runway"


@dataclass(frozen=True)
class Airfield:
    """One airfield and its runways.

    ``runways`` is a tuple rather than a single runway because
    §1.2.6.3 expects "optional alternate TO/L routes for a given
    airfield", and because retrofitting a collection onto a singleton
    is the expensive direction. The shipped data may hold one.
    """

    airfield_id: uuid.UUID
    report_id: uuid.UUID
    runways: tuple[Runway, ...]
    label: str = "home"

    @property
    def primary(self) -> Runway:
        """The first runway. Used where one has to be chosen."""
        return self.runways[0]


@dataclass(frozen=True)
class HomeAirfield:
    """The single-runway view the codec projects today.

    ``AirfieldReport`` and the linked TO/L plans are built from this.
    It is a narrowing of :class:`Airfield`, kept because the codec and
    ``IsolatorContext`` are written against one field and one runway;
    widening them is a separate change from replacing the data source.
    """

    airfield_id: uuid.UUID
    report_id: uuid.UUID
    runway_id: uuid.UUID
    takeoff_route_id: uuid.UUID
    landing_route_id: uuid.UUID
    direction_deg: float
    available_length_m: float
    takeoff_start: Waypoint
    takeoff_end: Waypoint
    landing_start: Waypoint
    landing_end: Waypoint

    @property
    def takeoff_path(self) -> tuple[Waypoint, ...]:
        """Runway start to far end."""
        return (self.takeoff_start, self.takeoff_end)

    @property
    def landing_path(self) -> tuple[Waypoint, ...]:
        """Far end back to runway start."""
        return (self.landing_start, self.landing_end)

    @property
    def route_ids(self) -> tuple[uuid.UUID, uuid.UUID]:
        """Takeoff then landing plan ids."""
        return (self.takeoff_route_id, self.landing_route_id)


def home_view(airfield: Airfield, runway: Runway | None = None) -> HomeAirfield:
    """Project *airfield* onto the single-runway shape the codec takes.

    *runway* defaults to the airfield's primary. The takeoff path runs
    start to limit and the landing path is its reverse, which is what
    the previous synthesised field did and what the codec expects.
    """
    chosen = runway or airfield.primary
    takeoff = chosen.takeoff
    landing = chosen.landing
    return HomeAirfield(
        airfield_id=airfield.airfield_id,
        report_id=airfield.report_id,
        runway_id=chosen.runway_id,
        takeoff_route_id=chosen.takeoff_route_id,
        landing_route_id=chosen.landing_route_id,
        direction_deg=chosen.direction_deg,
        available_length_m=chosen.available_length_m,
        takeoff_start=takeoff.start,
        takeoff_end=takeoff.limit or takeoff.start,
        landing_start=landing.start,
        landing_end=landing.limit or landing.start,
    )
