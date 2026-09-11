from __future__ import annotations

import os 

import boto3

_table = None

def get_table():
  """Returns a singleton instance of the DynamoDB table."""
  global _table
  if _table is None:
    table_name = os.environ.get("DYNAMODB_TABLE_NAME")
    if not table_name:
      raise ValueError("DYNAMODB_TABLE_NAME environment variable is not set.")
    _table = boto3.resource("dynamodb").Table(table_name)
  return _table