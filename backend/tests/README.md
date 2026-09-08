# Tests

Pure unit tests for the domain layer. No I/O, no fixtures on disk, no network — every
test builds entities in memory and asserts on domain behavior.

## Running

```sh
.venv/bin/pip install -r requirements-dev.txt   # first time
.venv/bin/pytest                                # whole suite
.venv/bin/pytest tests/unit/domain/entities     # one area
```

`pyproject.toml` puts `src` on the import path, so tests import production code the same
way the app does (`from domain.entities.expense import Expense`) with no editable install.

## Layout

```
tests/
  conftest.py    shared fixtures: readable UserIds (alice, bob, carol, dave), a GroupId
  builders.py    object mothers: make_user/make_group/make_expense/make_settlement
  unit/domain/   mirrors src/domain/
```

Builders return a valid entity by default and take keyword overrides, so a test spells
out only the field it cares about:

```python
expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))
```

`make_expense` derives balanced splits from `participants`; pass `splits=` explicitly to
build a deliberately invalid expense.
