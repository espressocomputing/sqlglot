import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlglot import parse_one
from sqlglot.dialects import Snowflake

def test_simple_snowflake_query():
    # Simple Snowflake SQL query
    simple_sql = """SELECT 
    column1,
    column2,
    SUM(column3) as total
FROM 
    my_table
WHERE 
    column1 = 'value'
GROUP BY 
    column1, column2;"""

    print("[START] Original query:\n", simple_sql, "\n")
    parsed = parse_one(simple_sql, dialect=Snowflake)
    print("[MIDDLE] AST:\n", repr(parsed), "\n")
    print("[END] Generated query:\n", parsed.sql(), "\n")
    print("-" * 80, "\n")

if __name__ == "__main__":
    test_simple_snowflake_query()