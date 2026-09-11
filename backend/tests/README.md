# Tests

Unit tests. No fixtures on disk, no network, no Docker — domain and application tests
build entities in memory, and infrastructure tests run against a DynamoDB that moto
patches into botocore in-process.

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
  conftest.py         shared fixtures: stable UserIds (alice, bob, carol, dave), a GroupId
  builders.py         object mothers: make_user/make_group/make_expense/make_settlement
  fakes.py            in-memory repository ports, e.g. InMemoryGroupRepository
  unit/domain/        mirrors src/domain/
  unit/application/   mirrors src/application/
  unit/infrastructure/  mirrors src/infrastructure/; dynamodb/conftest.py builds the table
```

Ids validate as UUIDs, so tests cannot write `UserId("alice")`. `id_for(UserId, "alice")`
derives a stable uuid5 from a label instead — the same label always yields the same id, in
every test and every run, so a failing assertion can be traced back to a name. The
`alice`/`bob`/`carol`/`dave` and `group_id` fixtures are built that way.

Builders return a valid entity by default and take keyword overrides, so a test spells
out only the field it cares about:

```python
expense = make_expense(paid_by=alice, participants=[alice, bob], total=money(10_000))
```

`make_expense` derives balanced splits from `participants`; pass `splits=` explicitly to
build a deliberately invalid expense.

Use-case tests drive a real use case against a fake repository from `fakes.py`. The fakes
deep-copy on read and on write, so a use case that mutates an entity without calling
`save` leaves the store unchanged and the test fails. `repository.saved` records every
write, which is how a test asserts that a rejected operation wrote nothing.

## Infrastructure tests

`unit/infrastructure/dynamodb/conftest.py` provides a `table` fixture: a real
`boto3` Table backed by moto, created with the same schema as
`infra/local/init/ready.d/10-dynamodb.sh`. Repository tests inject it, so they exercise
the production boto3 calls — key validation, `Decimal` coercion, upsert semantics —
without Docker.

Those tests assert the physical key strings (`PK=USER#<id>`, `SK=METADATA`) as literals
rather than building them from `infrastructure.dynamodb.keys`. A round trip alone cannot
catch a changed key format, because the write and the read would move together and leave
already-stored rows orphaned.
