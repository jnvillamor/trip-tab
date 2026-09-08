from __future__ import annotations

import pytest

from domain.value_objects.money import DEFAULT_CURRENCY, CurrencyMismatchError, Money


class TestConstruction:
  def test_defaults_to_the_default_currency(self):
    assert Money(100).currency == DEFAULT_CURRENCY

  def test_rejects_non_integer_cents(self):
    with pytest.raises(ValueError, match="integer representing cents"):
      Money(10.5)  # type: ignore[arg-type]

  @pytest.mark.parametrize("code", ["P", "PHPP", ""])
  def test_rejects_currency_codes_that_are_not_three_letters(self, code: str):
    with pytest.raises(ValueError, match="3-letter ISO code"):
      Money(100, code)

  def test_is_frozen(self):
    with pytest.raises(Exception):
      Money(100).amount_cents = 200  # type: ignore[misc]

  def test_is_hashable_and_compares_by_value(self):
    assert Money(100, "PHP") == Money(100, "PHP")
    assert Money(100, "PHP") != Money(100, "USD")
    assert len({Money(100, "PHP"), Money(100, "PHP")}) == 1


class TestMajorUnits:
  @pytest.mark.parametrize(
    ("major", "expected_cents"),
    [(0, 0), (1, 100), (19.99, 1999), (-5.5, -550), (1234.56, 123456)],
  )
  def test_from_major_units(self, major: float, expected_cents: int):
    assert Money.from_major_units(major).amount_cents == expected_cents

  def test_major_units_is_the_inverse(self):
    assert Money(1999).major_units == pytest.approx(19.99)

  def test_from_major_units_keeps_the_currency(self):
    assert Money.from_major_units(1, "USD").currency == "USD"


class TestArithmetic:
  def test_addition(self):
    assert Money(100) + Money(250) == Money(350)

  def test_subtraction_can_go_negative(self):
    assert Money(100) - Money(250) == Money(-150)

  def test_negation(self):
    assert -Money(100) == Money(-100)

  @pytest.mark.parametrize(
    "operation",
    [
      lambda a, b: a + b,
      lambda a, b: a - b,
      lambda a, b: a < b,
      lambda a, b: a <= b,
    ],
    ids=["add", "sub", "lt", "le"],
  )
  def test_mixing_currencies_is_rejected(self, operation):
    with pytest.raises(CurrencyMismatchError):
      operation(Money(100, "PHP"), Money(100, "USD"))


class TestComparison:
  def test_orders_by_amount(self):
    assert Money(100) < Money(200)
    assert Money(100) <= Money(100)
    assert not Money(200) < Money(100)

  def test_sorting_uses_the_amount(self):
    unsorted = [Money(300), Money(100), Money(200)]
    assert sorted(unsorted) == [Money(100), Money(200), Money(300)]


class TestPredicates:
  @pytest.mark.parametrize(
    ("cents", "is_zero", "is_positive", "is_negative"),
    [
      (0, True, False, False),
      (1, False, True, False),
      (-1, False, False, True),
    ],
  )
  def test_sign_predicates(self, cents: int, is_zero: bool, is_positive: bool, is_negative: bool):
    amount = Money(cents)
    assert amount.is_zero() is is_zero
    assert amount.is_positive() is is_positive
    assert amount.is_negative() is is_negative


class TestSum:
  def test_empty_sum_is_zero_in_the_requested_currency(self):
    assert Money.sum([], "USD") == Money(0, "USD")

  def test_adds_every_amount(self):
    assert Money.sum([Money(100), Money(250), Money(-50)]) == Money(300)

  def test_rejects_amounts_in_another_currency(self):
    with pytest.raises(CurrencyMismatchError):
      Money.sum([Money(100, "USD")], "PHP")


class TestFormatting:
  def test_renders_major_units_with_two_decimals_and_the_code(self):
    assert str(Money(1999, "PHP")) == "19.99 PHP"
    assert str(Money(-50, "USD")) == "-0.50 USD"
