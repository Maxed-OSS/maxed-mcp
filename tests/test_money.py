"""Money math mirrors money-rs: exact minor units, no lost cents, banker's rounding."""

import pytest

from maxed_mcp import money


def test_allocate_evenly_loses_no_cents():
    r = money.allocate(100, "USD", parts=3)
    amounts = [p["minor_units"] for p in r["parts"]]
    assert amounts == [34, 33, 33]
    assert sum(amounts) == 100
    assert [p["formatted"] for p in r["parts"]] == ["$0.34", "$0.33", "$0.33"]


def test_allocate_by_ratio():
    r = money.allocate(1000, "USD", ratios=[3, 7])
    assert [p["minor_units"] for p in r["parts"]] == [300, 700]


def test_allocate_indivisible_remainder_to_lowest_index():
    r = money.allocate(5, "USD", parts=3)
    assert [p["minor_units"] for p in r["parts"]] == [2, 2, 1]
    assert sum(p["minor_units"] for p in r["parts"]) == 5


def test_allocate_negative_preserves_total():
    r = money.allocate(-100, "USD", parts=3)
    assert sum(p["minor_units"] for p in r["parts"]) == -100


def test_allocate_requires_exactly_one_of_ratios_or_parts():
    with pytest.raises(money.MoneyError):
        money.allocate(100, "USD")
    with pytest.raises(money.MoneyError):
        money.allocate(100, "USD", ratios=[1], parts=2)


def test_apply_rate_bankers_rounding():
    r = money.apply_rate(1999, "USD", 0.0825)  # 164.9175 -> 165
    assert r["result"]["minor_units"] == 165
    assert r["result"]["formatted"] == "$1.65"


def test_apply_rate_half_up_vs_half_even():
    # 250 * 0.01 = 2.5 -> half_even 2, half_up 3
    assert money.apply_rate(250, "USD", 0.01, rounding="half_even")["result"]["minor_units"] == 2
    assert money.apply_rate(250, "USD", 0.01, rounding="half_up")["result"]["minor_units"] == 3


def test_zero_decimal_currency_formats_without_point():
    r = money.allocate(1500, "JPY", parts=1)
    assert r["parts"][0]["formatted"] == "¥1500"


def test_custom_currency_needs_exponent():
    with pytest.raises(money.MoneyError):
        money.allocate(100, "XBT", parts=2)
    r = money.allocate(150_000_000, "XBT", parts=1, exponent=8)
    assert r["parts"][0]["formatted"] == "XBT1.50000000"


def test_unknown_rounding_rejected():
    with pytest.raises(money.MoneyError):
        money.apply_rate(100, "USD", 0.1, rounding="nearest")


def test_sum_amounts_exact_and_mixed_signs():
    r = money.sum_amounts([1999, 250, -500], "USD")
    assert r["ok"] is True
    assert r["op"] == "sum"
    assert r["count"] == 3
    assert r["result"] == {
        "minor_units": 1749,
        "currency": "USD",
        "exponent": 2,
        "formatted": "$17.49",
    }


def test_sum_amounts_empty_list():
    r = money.sum_amounts([], "JPY")
    assert r["count"] == 0
    assert r["result"]["minor_units"] == 0
    assert r["result"]["formatted"] == "¥0"


def test_sum_amounts_custom_currency_and_validation():
    r = money.sum_amounts([100_000_000, 50_000_000], "XBT", exponent=8)
    assert r["result"]["formatted"] == "XBT1.50000000"
    with pytest.raises(money.MoneyError):
        money.sum_amounts([100], "XBT")
    with pytest.raises(money.MoneyError):
        money.sum_amounts([10.5], "USD")  # type: ignore[list-item]
    with pytest.raises(money.MoneyError):
        money.sum_amounts([True], "USD")  # type: ignore[list-item]
    with pytest.raises(money.MoneyError):
        money.sum_amounts("100", "USD")  # type: ignore[arg-type]
