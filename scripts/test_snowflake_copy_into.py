import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlglot import parse_one
from sqlglot.dialects import Snowflake

def test_snowflake_copy_into():
    copy_into_sql = """COPY INTO mytable (column1, column2, column3)
FROM (
    SELECT 
        $1 as column1,
        $2 as column2,
        $3 as column3
    FROM @my_stage/path/to/data/
)"""

    print("[START] Original query:\n", copy_into_sql, "\n")
    parsed = parse_one(copy_into_sql, dialect=Snowflake)
    print("[MIDDLE] AST:\n", repr(parsed), "\n")
    print("[END] Generated query:\n", parsed.sql(dialect=Snowflake), "\n")
    print("-" * 80, "\n")

if __name__ == "__main__":
    test_snowflake_copy_into()