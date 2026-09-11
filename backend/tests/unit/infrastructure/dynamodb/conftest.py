"""A real DynamoDB table, in process.

moto patches botocore, so these tests drive the same boto3 code the Lambda runs —
real key validation, real `Decimal` coercion, real overwrite semantics — with no
Docker and no network. A hand-written fake would only prove the fake agrees with
itself; this catches a malformed key the way DynamoDB would.

The schema mirrors `infra/local/init/ready.d/10-dynamodb.sh`, so a table shape that
passes here is the shape `docker compose up` creates.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "trip-tab"
REGION = "us-east-1"


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
  """Never let a test reach a real account, even if the developer has one configured."""
  for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    monkeypatch.setenv(name, "testing")
  monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def table():
  with mock_aws():
    resource = boto3.resource("dynamodb", region_name=REGION)
    resource.create_table(
      TableName=TABLE_NAME,
      BillingMode="PAY_PER_REQUEST",
      AttributeDefinitions=[
        {"AttributeName": name, "AttributeType": "S"}
        for name in ("PK", "SK", "GSI1PK", "GSI1SK")
      ],
      KeySchema=[
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
      ],
      GlobalSecondaryIndexes=[
        {
          "IndexName": "GSI1",
          "KeySchema": [
            {"AttributeName": "GSI1PK", "KeyType": "HASH"},
            {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
          ],
          "Projection": {"ProjectionType": "ALL"},
        }
      ],
    )
    yield resource.Table(TABLE_NAME)
