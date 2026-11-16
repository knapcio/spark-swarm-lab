"""VAT codes and the per-rate VAT summary of a document.

=====  =======  ==================
Code   Rate     Meaning
=====  =======  ==================
``S``  23 %     standard
``R``  8 %      reduced
``P``  5 %      super-reduced
``Z``  0 %      zero-rated
``E``  --       exempt (no VAT)
=====  =======  ==================

VAT is not rounded per line.  The net amounts of all lines with the same
code are added up first, and the VAT of each code is that sum times the
rate, rounded half-up to whole cents once.  The summary lists codes from
the highest rate to the lowest, exempt last.
"""
from dataclasses import dataclass
from decimal import Decimal

from .errors import InvalidAmount
from .money import HUNDRED, round_cents

RATES = {"S": Decimal(23), "R": Decimal(8), "P": Decimal(5), "Z": Decimal(0), "E": None}
ORDER = ("S", "R", "P", "Z", "E")


@dataclass(frozen=True)
class TaxLine:
    code: str
    net: int
    tax: int

    @property
    def rate(self):
        return RATES[self.code]

    def label(self):
        return "exempt" if self.rate is None else f"{self.rate}%"


def check_code(code):
    if code not in RATES:
        raise InvalidAmount(f"unknown VAT code {code!r}")
    return code


def rate_of(code):
    """The rate of ``code`` as a Decimal percentage; exempt counts as 0."""
    return RATES[check_code(code)] or Decimal(0)


def tax_summary(lines):
    """[TaxLine] for ``lines`` (objects with ``net`` cents and ``tax_code``), one per code used."""
    groups = {}
    for line in lines:
        rate = rate_of(line.tax_code)
        group = groups.setdefault(line.tax_code, [0, Decimal(0)])
        group[0] += line.net
        group[1] += Decimal(line.net) * rate / HUNDRED
    return [TaxLine(code, groups[code][0], round_cents(groups[code][1])) for code in ORDER if code in groups]


def tax_total(summary):
    return sum(line.tax for line in summary)

