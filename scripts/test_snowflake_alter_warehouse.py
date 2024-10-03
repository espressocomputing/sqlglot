import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlglot import parse_one
from sqlglot.dialects import Snowflake

def test_snowflake_alter_warehouse():
    alter_warehouse_sql = """ALTER WAREHOUSE my_warehouse
RENAME TO my_new_warehouse
ABORT ALL QUERIES
SET WAREHOUSE_SIZE = 'LARGE'
MAX_CLUSTER_COUNT = 5
MIN_CLUSTER_COUNT = 2
SCALING_POLICY = 'ECONOMY'
AUTO_SUSPEND = 300
AUTO_RESUME = TRUE
COMMENT = 'Updated warehouse configuration';"""

    print("[START] Original query:\n", alter_warehouse_sql, "\n")
    parsed = parse_one(alter_warehouse_sql, dialect=Snowflake)
    print("[MIDDLE] AST:\n", repr(parsed), "\n")
    print("[END] Generated query:\n", parsed.sql(), "\n")
    print("-" * 80, "\n")

if __name__ == "__main__":
    test_snowflake_alter_warehouse()
