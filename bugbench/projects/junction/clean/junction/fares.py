"""Zone fares, in grosz (1/100 PLN).

The fare of a journey depends on the zones it touches: the zone of every
station where it boards, alights, passes through or walks.  Zones travelled =
highest zone - lowest zone + 1.  Prices: 1 zone 4.00, 2 zones 5.60, 3 zones
7.20, every further zone 1.50 more.  A journey that departs between 23:00 and
03:59 on the clock pays a night surcharge of 2.00.

A concession takes a percentage off the full fare (surcharge included):
``senior`` 37 %, ``student`` 51 %.  Reduced amounts are rounded half up to
10 grosz.  A day ticket caps one passenger's fares on one day at 16.00, or at
the reduced cap for a concession.
"""
from decimal import ROUND_HALF_UP, Decimal

from .clock import MINUTES_PER_DAY
from .errors import JunctionError
from .network import whole

ZONE_PRICES = (400, 560, 720)
EXTRA_ZONE = 150
NIGHT_SURCHARGE = 200
NIGHT_FROM, NIGHT_UNTIL = 23 * 60, 4 * 60
CONCESSIONS = {"full": 0, "senior": 37, "student": 51}
DAY_CAP = 1600


def zone_price(zones):
    """Full price for travelling through ``zones`` zones (1-99)."""
    whole(zones, 1, 99, "zones")
    if zones <= len(ZONE_PRICES):
        return ZONE_PRICES[zones - 1]
    return ZONE_PRICES[-1] + EXTRA_ZONE * (zones - len(ZONE_PRICES))


def is_night(minutes):
    """True for listing times whose clock time is 23:00-03:59 (``minutes`` may be 24:00 or later)."""
    clock = minutes % MINUTES_PER_DAY
    return clock >= NIGHT_FROM or clock < NIGHT_UNTIL


def reduce(cents, concession):
    """``cents`` minus the concession's percentage, rounded half up to 10 grosz (``full``: unchanged)."""
    if concession not in CONCESSIONS:
        raise JunctionError(f"unknown concession {concession!r}")
    if not CONCESSIONS[concession]:
        return cents
    tens = Decimal(cents) * (100 - CONCESSIONS[concession]) / 1000
    return int(tens.quantize(Decimal(1), rounding=ROUND_HALF_UP)) * 10


def zones_travelled(network, journey):
    zones = network.zones(journey.stations())
    return zones[-1] - zones[0] + 1


def fare(network, journey, concession="full"):
    """Fare of ``journey`` in grosz."""
    full = zone_price(zones_travelled(network, journey))
    if is_night(journey.departure):
        full += NIGHT_SURCHARGE
    return reduce(full, concession)


def day_total(network, journeys, concession="full"):
    """Total for one passenger's journeys on one day, capped by the day ticket."""
    total = sum(fare(network, journey, concession) for journey in journeys)
    return min(total, reduce(DAY_CAP, concession))


def format_money(cents):
    """``560`` -> ``"5.60"``."""
    whole(cents, 0, 10 ** 9, "amount")
    return f"{cents // 100}.{cents % 100:02d}"
