"""Exact-decimal money math for the MCP server.

This mirrors the semantics of the sibling ``money-rs`` crate so an agent gets
the same answers whether it calls the Rust library directly or this MCP tool:

* amounts are a signed integer count of *minor units* (cents, pennies, fils),
  so addition, subtraction and scaling never drift the way binary floats do;
* splitting a sum uses the largest-remainder method, so the parts always add
  back up to the original to the last minor unit;
* rounding is explicit and defaults to banker's rounding (half to even).

``money-rs`` is the canonical implementation and the reference for the rules;
this module is the pure-Python equivalent the server uses so the tool works
without a Rust toolchain. It has no third-party dependencies.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Dict, List, Optional

# code -> exponent (number of decimal places). Mirrors money-rs's built-ins.
_CURRENCIES: Dict[str, Dict[str, object]] = {
    "USD": {"symbol": "$", "exponent": 2},
    "EUR": {"symbol": "€", "exponent": 2},
    "GBP": {"symbol": "£", "exponent": 2},
    "JPY": {"symbol": "¥", "exponent": 0},
    "BHD": {"symbol": "BD", "exponent": 3},
}

_ROUNDING = {
    "half_even": ROUND_HALF_EVEN,
    "half_up": ROUND_HALF_UP,
    "floor": ROUND_FLOOR,
    "ceil": ROUND_CEILING,
    "truncate": ROUND_DOWN,
}


class MoneyError(ValueError):
    """Raised on an invalid money operation (unknown currency, bad ratios)."""


def _resolve_currency(code: str, exponent: Optional[int]) -> Dict[str, object]:
    """Return the currency descriptor for ``code``.

    Known codes use their standard exponent and symbol. An unknown code is
    allowed only when the caller supplies an explicit ``exponent`` (so custom
    or crypto currencies work), and then the code doubles as its own symbol.
    """
    code = (code or "").upper()
    if code in _CURRENCIES:
        desc = dict(_CURRENCIES[code])
        if exponent is not None and int(exponent) != desc["exponent"]:
            raise MoneyError(
                f"currency {code} uses exponent {desc['exponent']}, not {exponent}"
            )
        desc["code"] = code
        return desc
    if exponent is None:
        raise MoneyError(
            f"unknown currency {code!r}; pass an explicit exponent for a custom currency"
        )
    if int(exponent) < 0:
        raise MoneyError("exponent must be >= 0")
    return {"code": code, "symbol": code, "exponent": int(exponent)}


def _subunit(exponent: int) -> int:
    return 10 ** exponent


def format_amount(minor_units: int, desc: Dict[str, object]) -> str:
    """Render minor units like money-rs's Display (for example ``$19.99``)."""
    exponent = int(desc["exponent"])
    subunit = _subunit(exponent)
    negative = minor_units < 0
    magnitude = abs(minor_units)
    sign = "-" if negative else ""
    symbol = str(desc["symbol"])
    if exponent == 0:
        return f"{sign}{symbol}{magnitude}"
    major = magnitude // subunit
    minor = magnitude % subunit
    return f"{sign}{symbol}{major}.{minor:0{exponent}d}"


def _money_dict(minor_units: int, desc: Dict[str, object]) -> Dict[str, object]:
    return {
        "minor_units": int(minor_units),
        "currency": desc["code"],
        "exponent": int(desc["exponent"]),
        "formatted": format_amount(minor_units, desc),
    }


def allocate(
    minor_units: int,
    currency: str,
    *,
    ratios: Optional[List[int]] = None,
    parts: Optional[int] = None,
    exponent: Optional[int] = None,
) -> Dict[str, object]:
    """Split ``minor_units`` across ``ratios`` (or evenly into ``parts``).

    Uses the largest-remainder method: each recipient gets the floor of its
    proportional share, then the leftover minor units are handed out one at a
    time to the largest remainders (ties broken by lower index). The parts
    always sum back exactly to the original amount, with no lost or invented
    minor units. Exactly one of ``ratios`` or ``parts`` must be given.
    """
    desc = _resolve_currency(currency, exponent)
    if (ratios is None) == (parts is None):
        raise MoneyError("pass exactly one of 'ratios' or 'parts'")
    if parts is not None:
        if int(parts) <= 0:
            raise MoneyError("parts must be a positive integer")
        ratios = [1] * int(parts)
    ratios = [int(r) for r in ratios]
    if not ratios:
        raise MoneyError("ratios must be non-empty")
    if any(r < 0 for r in ratios):
        raise MoneyError("ratios must be non-negative")
    total_ratio = sum(ratios)
    if total_ratio == 0:
        raise MoneyError("ratios must not sum to zero")

    sign = -1 if minor_units < 0 else 1
    amount = abs(int(minor_units))

    shares: List[int] = []
    remainders: List[tuple] = []  # (index, remainder)
    allocated = 0
    for i, r in enumerate(ratios):
        numerator = amount * r
        share = numerator // total_ratio
        rem = numerator % total_ratio
        shares.append(share)
        remainders.append((i, rem))
        allocated += share

    leftover = amount - allocated
    # Largest remainder first; ties go to the lower index for determinism.
    remainders.sort(key=lambda t: (-t[1], t[0]))
    k = 0
    while leftover > 0:
        shares[remainders[k][0]] += 1
        leftover -= 1
        k += 1

    parts_out = [_money_dict(sign * s, desc) for s in shares]
    return {
        "ok": True,
        "op": "allocate",
        "input": _money_dict(minor_units, desc),
        "ratios": ratios,
        "parts": parts_out,
        "sum_check": int(sign * sum(shares)),
    }


def apply_rate(
    minor_units: int,
    currency: str,
    rate: float,
    *,
    rounding: str = "half_even",
    exponent: Optional[int] = None,
) -> Dict[str, object]:
    """Multiply an amount by a real ``rate`` (a tax rate, discount, or share).

    The exact product is computed in decimal and rounded to whole minor units
    with the requested strategy. Use this for tax, tips, or applying a
    percentage; the result is a clean integer minor-unit amount.
    """
    desc = _resolve_currency(currency, exponent)
    mode = _ROUNDING.get(str(rounding).lower())
    if mode is None:
        raise MoneyError(
            f"unknown rounding {rounding!r}; choose from {sorted(_ROUNDING)}"
        )
    exact = Decimal(int(minor_units)) * Decimal(str(rate))
    rounded = int(exact.quantize(Decimal(1), rounding=mode))
    return {
        "ok": True,
        "op": "apply_rate",
        "input": _money_dict(minor_units, desc),
        "rate": str(rate),
        "rounding": str(rounding).lower(),
        "exact_minor_units": str(exact),
        "result": _money_dict(rounded, desc),
    }


def sum_amounts(
    amounts: List[int],
    currency: str,
    *,
    exponent: Optional[int] = None,
) -> Dict[str, object]:
    """Sum exact integer minor-unit amounts without floating-point drift.

    Supports negative values for debits/refunds alongside positive credits.
    Rejects non-integer entries (including booleans and floats) so agents
    cannot silently truncate fractional amounts.
    """
    desc = _resolve_currency(currency, exponent)
    if isinstance(amounts, (str, bytes)) or not isinstance(amounts, (list, tuple)):
        raise MoneyError("amounts must be a list of integer minor-unit values")
    validated: List[int] = []
    for item in amounts:
        if isinstance(item, bool) or not isinstance(item, int):
            raise MoneyError(
                f"each amount must be an integer minor-unit value, got {type(item).__name__}"
            )
        validated.append(item)
    total = sum(validated)
    return {
        "ok": True,
        "op": "sum",
        "count": len(validated),
        "result": _money_dict(total, desc),
    }


def supported_currencies() -> List[Dict[str, object]]:
    """List the built-in currencies (custom ones need an explicit exponent)."""
    return [
        {"code": code, "symbol": desc["symbol"], "exponent": desc["exponent"]}
        for code, desc in _CURRENCIES.items()
    ]
