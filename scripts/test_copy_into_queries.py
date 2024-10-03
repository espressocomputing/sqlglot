import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlglot import parse_one
from sqlglot.dialects import Snowflake

def test_copy_into_queries():
    # Load json file from my Desktop/copy_into_queries.json
    queries = []
    with open("/Users/espresso/Desktop/thanx_copy_into_queries.json", "r") as f:
    # with open("/Users/espresso/Desktop/thrive_copy_into_queries.json", "r") as f:
    # with open("/Users/espresso/Desktop/thrive_queries_2k.json", "r") as f:
        for line in f:
            queries.append(json.loads(line))

    for query in queries:
        try:
            print("[START] Original query:\n", query["query_text"], "\n")
            parsed = parse_one(query["query_text"], dialect=Snowflake)
            print("[MIDDLE] AST:\n", repr(parsed), "\n")
            print("[END] Generated query:\n", parsed.sql(), "\n")
            print("-" * 80, "\n")
        except Exception as e:
            raise e

if __name__ == "__main__":
    test_copy_into_queries()

