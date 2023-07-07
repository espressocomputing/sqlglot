import time
import unittest
from unittest.mock import patch

from sqlglot import Parser, exp, parse, parse_one
from sqlglot.errors import ErrorLevel, ParseError
from tests.helpers import assert_logger_contains


class TestParser(unittest.TestCase):
    def test_parse_empty(self):
        with self.assertRaises(ParseError) as ctx:
            parse_one("")

    def test_parse_into(self):
        self.assertIsInstance(parse_one("left join foo", into=exp.Join), exp.Join)
        self.assertIsInstance(parse_one("int", into=exp.DataType), exp.DataType)
        self.assertIsInstance(parse_one("array<int>", into=exp.DataType), exp.DataType)
        self.assertIsInstance(parse_one("foo", into=exp.Table), exp.Table)

        with self.assertRaises(ParseError) as ctx:
            parse_one("SELECT * FROM tbl", into=exp.Table)

        self.assertEqual(
            str(ctx.exception),
            "Failed to parse 'SELECT * FROM tbl' into <class 'sqlglot.expressions.Table'>",
        )

    def test_parse_into_error(self):
        expected_message = "Failed to parse 'SELECT 1;' into [<class 'sqlglot.expressions.From'>]"
        expected_errors = [
            {
                "description": "Invalid expression / Unexpected token",
                "line": 1,
                "col": 6,
                "start_context": "",
                "highlight": "SELECT",
                "end_context": " 1;",
                "into_expression": exp.From,
            }
        ]
        with self.assertRaises(ParseError) as ctx:
            parse_one("SELECT 1;", read="sqlite", into=[exp.From])

        self.assertEqual(str(ctx.exception), expected_message)
        self.assertEqual(ctx.exception.errors, expected_errors)

    def test_parse_into_errors(self):
        expected_message = "Failed to parse 'SELECT 1;' into [<class 'sqlglot.expressions.From'>, <class 'sqlglot.expressions.Join'>]"
        expected_errors = [
            {
                "description": "Invalid expression / Unexpected token",
                "line": 1,
                "col": 6,
                "start_context": "",
                "highlight": "SELECT",
                "end_context": " 1;",
                "into_expression": exp.From,
            },
            {
                "description": "Invalid expression / Unexpected token",
                "line": 1,
                "col": 6,
                "start_context": "",
                "highlight": "SELECT",
                "end_context": " 1;",
                "into_expression": exp.Join,
            },
        ]
        with self.assertRaises(ParseError) as ctx:
            parse_one("SELECT 1;", "sqlite", into=[exp.From, exp.Join])

        self.assertEqual(str(ctx.exception), expected_message)
        self.assertEqual(ctx.exception.errors, expected_errors)

    def test_column(self):
        columns = parse_one("select a, ARRAY[1] b, case when 1 then 1 end").find_all(exp.Column)
        assert len(list(columns)) == 1

        self.assertIsNotNone(parse_one("date").find(exp.Column))

    def test_float(self):
        self.assertEqual(parse_one(".2"), parse_one("0.2"))

    def test_unnest_projection(self):
        expr = parse_one("SELECT foo IN UNNEST(bla) AS bar")
        self.assertIsInstance(expr.selects[0], exp.Alias)
        self.assertEqual(expr.selects[0].output_name, "bar")

    def test_unary_plus(self):
        self.assertEqual(parse_one("+15"), exp.Literal.number(15))

    def test_table(self):
        tables = [t.sql() for t in parse_one("select * from a, b.c, .d").find_all(exp.Table)]
        self.assertEqual(set(tables), {"a", "b.c", "d"})

    def test_union_order(self):
        self.assertIsInstance(parse_one("SELECT * FROM (SELECT 1) UNION SELECT 2"), exp.Union)
        self.assertIsInstance(
            parse_one("SELECT x FROM y HAVING x > (SELECT 1) UNION SELECT 2"), exp.Union
        )

    def test_select(self):
        self.assertIsNotNone(parse_one("select 1 natural"))
        self.assertIsNotNone(parse_one("select * from (select 1) x order by x.y").args["order"])
        self.assertIsNotNone(
            parse_one("select * from x where a = (select 1) order by x.y").args["order"]
        )
        self.assertEqual(len(parse_one("select * from (select 1) x cross join y").args["joins"]), 1)
        self.assertEqual(
            parse_one("""SELECT * FROM x CROSS JOIN y, z LATERAL VIEW EXPLODE(y)""").sql(),
            """SELECT * FROM x CROSS JOIN y, z LATERAL VIEW EXPLODE(y)""",
        )
        self.assertIsNone(
            parse_one("create table a as (select b from c) index").find(exp.TableAlias)
        )

    def test_command(self):
        expressions = parse("SET x = 1; ADD JAR s3://a; SELECT 1", read="hive")
        self.assertEqual(len(expressions), 3)
        self.assertEqual(expressions[0].sql(), "SET x = 1")
        self.assertEqual(expressions[1].sql(), "ADD JAR s3://a")
        self.assertEqual(expressions[2].sql(), "SELECT 1")

    def test_lambda_struct(self):
        expression = parse_one("FILTER(a.b, x -> x.id = id)")
        lambda_expr = expression.expression

        self.assertIsInstance(lambda_expr.this.this, exp.Dot)
        self.assertEqual(lambda_expr.sql(), "x -> x.id = id")

        self.assertIsNone(parse_one("FILTER([], x -> x)").find(exp.Column))

    def test_transactions(self):
        expression = parse_one("BEGIN TRANSACTION")
        self.assertIsNone(expression.this)
        self.assertEqual(expression.args["modes"], [])
        self.assertEqual(expression.sql(), "BEGIN")

        expression = parse_one("START TRANSACTION", read="mysql")
        self.assertIsNone(expression.this)
        self.assertEqual(expression.args["modes"], [])
        self.assertEqual(expression.sql(), "BEGIN")

        expression = parse_one("BEGIN DEFERRED TRANSACTION")
        self.assertEqual(expression.this, "DEFERRED")
        self.assertEqual(expression.args["modes"], [])
        self.assertEqual(expression.sql(), "BEGIN")

        expression = parse_one(
            "START TRANSACTION READ WRITE, ISOLATION LEVEL SERIALIZABLE", read="presto"
        )
        self.assertIsNone(expression.this)
        self.assertEqual(expression.args["modes"][0], "READ WRITE")
        self.assertEqual(expression.args["modes"][1], "ISOLATION LEVEL SERIALIZABLE")
        self.assertEqual(expression.sql(), "BEGIN")

        expression = parse_one("BEGIN", read="bigquery")
        self.assertNotIsInstance(expression, exp.Transaction)
        self.assertIsNone(expression.expression)
        self.assertEqual(expression.sql(), "BEGIN")

    def test_identify(self):
        expression = parse_one(
            """
            SELECT a, "b", c AS c, d AS "D", e AS "y|z'"
            FROM y."z"
        """
        )

        assert expression.expressions[0].name == "a"
        assert expression.expressions[1].name == "b"
        assert expression.expressions[2].alias == "c"
        assert expression.expressions[3].alias == "D"
        assert expression.expressions[4].alias == "y|z'"
        table = expression.args["from"].this
        assert table.name == "z"
        assert table.args["db"].name == "y"

    def test_multi(self):
        expressions = parse(
            """
            SELECT * FROM a; SELECT * FROM b;
        """
        )

        assert len(expressions) == 2
        assert expressions[0].args["from"].name == "a"
        assert expressions[1].args["from"].name == "b"

        expressions = parse("SELECT 1; ; SELECT 2")

        assert len(expressions) == 3
        assert expressions[1] is None

    def test_expression(self):
        ignore = Parser(error_level=ErrorLevel.IGNORE)
        self.assertIsInstance(ignore.expression(exp.Hint, expressions=[""]), exp.Hint)
        self.assertIsInstance(ignore.expression(exp.Hint, y=""), exp.Hint)
        self.assertIsInstance(ignore.expression(exp.Hint), exp.Hint)

        default = Parser(error_level=ErrorLevel.RAISE)
        self.assertIsInstance(default.expression(exp.Hint, expressions=[""]), exp.Hint)
        default.expression(exp.Hint, y="")
        default.expression(exp.Hint)
        self.assertEqual(len(default.errors), 3)

        warn = Parser(error_level=ErrorLevel.WARN)
        warn.expression(exp.Hint, y="")
        self.assertEqual(len(warn.errors), 2)

    def test_parse_errors(self):
        with self.assertRaises(ParseError):
            parse_one("IF(a > 0, a, b, c)")

        with self.assertRaises(ParseError):
            parse_one("IF(a > 0)")

        with self.assertRaises(ParseError):
            parse_one("WITH cte AS (SELECT * FROM x)")

        self.assertEqual(
            parse_one(
                "CREATE TABLE t (i UInt8) ENGINE = AggregatingMergeTree() ORDER BY tuple()",
                read="clickhouse",
                error_level=ErrorLevel.RAISE,
            ).sql(dialect="clickhouse"),
            "CREATE TABLE t (i UInt8) ENGINE=AggregatingMergeTree() ORDER BY tuple()",
        )

    def test_space(self):
        self.assertEqual(
            parse_one("SELECT ROW() OVER(PARTITION  BY x) FROM x GROUP  BY y").sql(),
            "SELECT ROW() OVER (PARTITION BY x) FROM x GROUP BY y",
        )

        self.assertEqual(
            parse_one(
                """SELECT   * FROM x GROUP
                BY y"""
            ).sql(),
            "SELECT * FROM x GROUP BY y",
        )

    def test_missing_by(self):
        with self.assertRaises(ParseError):
            parse_one("SELECT FROM x ORDER BY")

    def test_parameter(self):
        self.assertEqual(parse_one("SELECT @x, @@x, @1").sql(), "SELECT @x, @@x, @1")

    def test_var(self):
        self.assertIsInstance(parse_one("INTERVAL '1' DAY").args["unit"], exp.Var)
        self.assertEqual(parse_one("SELECT @JOIN, @'foo'").sql(), "SELECT @JOIN, @'foo'")

    def test_comments(self):
        expression = parse_one(
            """
            --comment1.1
            --comment1.2
            SELECT /*comment1.3*/
                a, --comment2
                b as B, --comment3:testing
                "test--annotation",
                c, --comment4 --foo
                e, --
                f -- space
            FROM foo
        """
        )

        self.assertEqual(expression.comments, ["comment1.1", "comment1.2", "comment1.3"])
        self.assertEqual(expression.expressions[0].comments, ["comment2"])
        self.assertEqual(expression.expressions[1].comments, ["comment3:testing"])
        self.assertEqual(expression.expressions[2].comments, None)
        self.assertEqual(expression.expressions[3].comments, ["comment4 --foo"])
        self.assertEqual(expression.expressions[4].comments, [""])
        self.assertEqual(expression.expressions[5].comments, [" space"])

    def test_type_literals(self):
        self.assertEqual(parse_one("int 1"), parse_one("CAST(1 AS INT)"))
        self.assertEqual(parse_one("int.5"), parse_one("CAST(0.5 AS INT)"))
        self.assertEqual(
            parse_one("TIMESTAMP '2022-01-01'").sql(), "CAST('2022-01-01' AS TIMESTAMP)"
        )
        self.assertEqual(
            parse_one("TIMESTAMP(1) '2022-01-01'").sql(), "CAST('2022-01-01' AS TIMESTAMP(1))"
        )
        self.assertEqual(
            parse_one("TIMESTAMP WITH TIME ZONE '2022-01-01'").sql(),
            "CAST('2022-01-01' AS TIMESTAMPTZ)",
        )
        self.assertEqual(
            parse_one("TIMESTAMP WITH LOCAL TIME ZONE '2022-01-01'").sql(),
            "CAST('2022-01-01' AS TIMESTAMPLTZ)",
        )
        self.assertEqual(
            parse_one("TIMESTAMP WITHOUT TIME ZONE '2022-01-01'").sql(),
            "CAST('2022-01-01' AS TIMESTAMP)",
        )
        self.assertEqual(
            parse_one("TIMESTAMP(1) WITH TIME ZONE '2022-01-01'").sql(),
            "CAST('2022-01-01' AS TIMESTAMPTZ(1))",
        )
        self.assertEqual(
            parse_one("TIMESTAMP(1) WITH LOCAL TIME ZONE '2022-01-01'").sql(),
            "CAST('2022-01-01' AS TIMESTAMPLTZ(1))",
        )
        self.assertEqual(
            parse_one("TIMESTAMP(1) WITHOUT TIME ZONE '2022-01-01'").sql(),
            "CAST('2022-01-01' AS TIMESTAMP(1))",
        )
        self.assertEqual(parse_one("TIMESTAMP(1) WITH TIME ZONE").sql(), "TIMESTAMPTZ(1)")
        self.assertEqual(parse_one("TIMESTAMP(1) WITH LOCAL TIME ZONE").sql(), "TIMESTAMPLTZ(1)")
        self.assertEqual(parse_one("TIMESTAMP(1) WITHOUT TIME ZONE").sql(), "TIMESTAMP(1)")
        self.assertEqual(parse_one("""JSON '{"x":"y"}'""").sql(), """CAST('{"x":"y"}' AS JSON)""")
        self.assertIsInstance(parse_one("TIMESTAMP(1)"), exp.Func)
        self.assertIsInstance(parse_one("TIMESTAMP('2022-01-01')"), exp.Func)
        self.assertIsInstance(parse_one("TIMESTAMP()"), exp.Func)
        self.assertIsInstance(parse_one("map.x"), exp.Column)
        self.assertIsInstance(parse_one("CAST(x AS CHAR(5))").to.expressions[0], exp.DataTypeSize)
        self.assertEqual(parse_one("1::int64", dialect="bigquery"), parse_one("CAST(1 AS BIGINT)"))

    def test_set_expression(self):
        set_ = parse_one("SET")

        self.assertEqual(set_.sql(), "SET")
        self.assertIsInstance(set_, exp.Set)

        set_session = parse_one("SET SESSION x = 1")

        self.assertEqual(set_session.sql(), "SET SESSION x = 1")
        self.assertIsInstance(set_session, exp.Set)

        set_item = set_session.expressions[0]

        self.assertIsInstance(set_item, exp.SetItem)
        self.assertIsInstance(set_item.this, exp.EQ)
        self.assertIsInstance(set_item.this.this, exp.Identifier)
        self.assertIsInstance(set_item.this.expression, exp.Literal)

        self.assertEqual(set_item.args.get("kind"), "SESSION")

        set_to = parse_one("SET x TO 1")

        self.assertEqual(set_to.sql(), "SET x = 1")
        self.assertIsInstance(set_to, exp.Set)

        set_as_command = parse_one("SET DEFAULT ROLE ALL TO USER")

        self.assertEqual(set_as_command.sql(), "SET DEFAULT ROLE ALL TO USER")

        self.assertIsInstance(set_as_command, exp.Command)
        self.assertEqual(set_as_command.this, "SET")
        self.assertEqual(set_as_command.expression, " DEFAULT ROLE ALL TO USER")

    def test_pretty_config_override(self):
        self.assertEqual(parse_one("SELECT col FROM x").sql(), "SELECT col FROM x")
        with patch("sqlglot.pretty", True):
            self.assertEqual(parse_one("SELECT col FROM x").sql(), "SELECT\n  col\nFROM x")

        self.assertEqual(parse_one("SELECT col FROM x").sql(pretty=True), "SELECT\n  col\nFROM x")

    @patch("sqlglot.parser.logger")
    def test_comment_error_n(self, logger):
        parse_one(
            """SUM
(
-- test
)""",
            error_level=ErrorLevel.WARN,
        )

        assert_logger_contains(
            "Required keyword: 'this' missing for <class 'sqlglot.expressions.Sum'>. Line 4, Col: 1.",
            logger,
        )

    @patch("sqlglot.parser.logger")
    def test_comment_error_r(self, logger):
        parse_one(
            """SUM(-- test\r)""",
            error_level=ErrorLevel.WARN,
        )

        assert_logger_contains(
            "Required keyword: 'this' missing for <class 'sqlglot.expressions.Sum'>. Line 2, Col: 1.",
            logger,
        )

    @patch("sqlglot.parser.logger")
    def test_create_table_error(self, logger):
        parse_one(
            """CREATE TABLE SELECT""",
            error_level=ErrorLevel.WARN,
        )

        assert_logger_contains(
            "Expected table name",
            logger,
        )

    def test_rename_table(self):
        self.assertEqual(
            parse_one("ALTER TABLE foo RENAME TO bar").sql(),
            "ALTER TABLE foo RENAME TO bar",
        )

    def test_pivot_columns(self):
        nothing_aliased = """
            SELECT * FROM (
                SELECT partname, price FROM part
            ) PIVOT (AVG(price) FOR partname IN ('prop', 'rudder'))
        """

        everything_aliased = """
            SELECT * FROM (
                SELECT partname, price FROM part
            ) PIVOT (AVG(price) AS avg_price FOR partname IN ('prop' AS prop1, 'rudder' AS rudder1))
        """

        only_pivot_columns_aliased = """
            SELECT * FROM (
                SELECT partname, price FROM part
            ) PIVOT (AVG(price) FOR partname IN ('prop' AS prop1, 'rudder' AS rudder1))
        """

        columns_partially_aliased = """
            SELECT * FROM (
                SELECT partname, price FROM part
            ) PIVOT (AVG(price) FOR partname IN ('prop' AS prop1, 'rudder'))
        """

        multiple_aggregates_aliased = """
            SELECT * FROM (
                SELECT partname, price, quality FROM part
            ) PIVOT (AVG(price) AS p, MAX(quality) AS q FOR partname IN ('prop' AS prop1, 'rudder'))
        """

        multiple_aggregates_not_aliased = """
            SELECT * FROM (
                SELECT partname, price, quality FROM part
            ) PIVOT (AVG(price), MAX(quality) FOR partname IN ('prop' AS prop1, 'rudder'))
        """

        multiple_aggregates_not_aliased_with_quoted_identifier_spark = """
            SELECT * FROM (
                SELECT partname, price, quality FROM part
            ) PIVOT (AVG(`PrIcE`), MAX(quality) FOR partname IN ('prop' AS prop1, 'rudder'))
        """

        multiple_aggregates_not_aliased_with_quoted_identifier_duckdb = """
            SELECT * FROM (
                SELECT partname, price, quality FROM part
            ) PIVOT (AVG("PrIcE"), MAX(quality) FOR partname IN ('prop' AS prop1, 'rudder'))
        """

        query_to_column_names = {
            nothing_aliased: {
                "bigquery": ["prop", "rudder"],
                "duckdb": ["prop", "rudder"],
                "redshift": ["prop", "rudder"],
                "snowflake": ['''"'prop'"''', '''"'rudder'"'''],
                "spark": ["prop", "rudder"],
            },
            everything_aliased: {
                "bigquery": ["avg_price_prop1", "avg_price_rudder1"],
                "duckdb": ["prop1_avg_price", "rudder1_avg_price"],
                "redshift": ["prop1_avg_price", "rudder1_avg_price"],
                "spark": ["prop1", "rudder1"],
            },
            only_pivot_columns_aliased: {
                "bigquery": ["prop1", "rudder1"],
                "duckdb": ["prop1", "rudder1"],
                "redshift": ["prop1", "rudder1"],
                "spark": ["prop1", "rudder1"],
            },
            columns_partially_aliased: {
                "bigquery": ["prop1", "rudder"],
                "duckdb": ["prop1", "rudder"],
                "redshift": ["prop1", "rudder"],
                "spark": ["prop1", "rudder"],
            },
            multiple_aggregates_aliased: {
                "bigquery": ["p_prop1", "q_prop1", "p_rudder", "q_rudder"],
                "duckdb": ["prop1_p", "prop1_q", "rudder_p", "rudder_q"],
                "spark": ["prop1_p", "prop1_q", "rudder_p", "rudder_q"],
            },
            multiple_aggregates_not_aliased: {
                "duckdb": [
                    '"prop1_avg(price)"',
                    '"prop1_max(quality)"',
                    '"rudder_avg(price)"',
                    '"rudder_max(quality)"',
                ],
                "spark": [
                    "`prop1_avg(price)`",
                    "`prop1_max(quality)`",
                    "`rudder_avg(price)`",
                    "`rudder_max(quality)`",
                ],
            },
            multiple_aggregates_not_aliased_with_quoted_identifier_spark: {
                "spark": [
                    "`prop1_avg(PrIcE)`",
                    "`prop1_max(quality)`",
                    "`rudder_avg(PrIcE)`",
                    "`rudder_max(quality)`",
                ],
            },
            multiple_aggregates_not_aliased_with_quoted_identifier_duckdb: {
                "duckdb": [
                    '"prop1_avg(PrIcE)"',
                    '"prop1_max(quality)"',
                    '"rudder_avg(PrIcE)"',
                    '"rudder_max(quality)"',
                ],
            },
        }

        for query, dialect_columns in query_to_column_names.items():
            for dialect, expected_columns in dialect_columns.items():
                expr = parse_one(query, read=dialect)
                columns = expr.args["from"].this.args["pivots"][0].args["columns"]
                self.assertEqual(expected_columns, [col.sql(dialect=dialect) for col in columns])

    def test_parse_nested(self):
        now = time.time()
        query = parse_one(
            """
            select *
            FROM a
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            LEFT JOIN b ON a.id = b.id
            """
        )
        self.assertIsNotNone(query)
        self.assertLessEqual(time.time() - now, 0.1)

    def test_parse_properties(self):
        self.assertEqual(
            parse_one("create materialized table x").sql(), "CREATE MATERIALIZED TABLE x"
        )

    def test_parse_floats(self):
        self.assertTrue(parse_one("1. ").is_number)

    def test_parse_wrapped_tables(self):
        expr = parse_one("select * from (table)")
        self.assertIsInstance(expr.args["from"].this, exp.Table)
        self.assertTrue(expr.args["from"].this.args["wrapped"])

        expr = parse_one("select * from (((table)))")
        self.assertIsInstance(expr.args["from"].this, exp.Table)
        self.assertTrue(expr.args["from"].this.args["wrapped"])

        self.assertEqual(expr.sql(), "SELECT * FROM (table)")

        expr = parse_one("select * from (tbl1 join tbl2)")
        self.assertIsInstance(expr.args["from"].this, exp.Table)
        self.assertTrue(expr.args["from"].this.args["wrapped"])
        self.assertEqual(len(expr.args["from"].this.args["joins"]), 1)

        expr = parse_one("select * from (tbl1 join tbl2) t")
        self.assertIsInstance(expr.args["from"].this, exp.Subquery)
        self.assertIsInstance(expr.args["from"].this.this, exp.Select)
        self.assertEqual(expr.sql(), "SELECT * FROM (SELECT * FROM tbl1, tbl2) AS t")

        expr = parse_one("select * from (tbl as tbl) t")
        self.assertEqual(expr.sql(), "SELECT * FROM (SELECT * FROM tbl AS tbl) AS t")

        expr = parse_one("select * from ((a cross join b) cross join c)")
        self.assertIsInstance(expr.args["from"].this, exp.Table)
        self.assertTrue(expr.args["from"].this.args["wrapped"])
        self.assertEqual(len(expr.args["from"].this.args["joins"]), 2)
        self.assertEqual(expr.sql(), "SELECT * FROM (a CROSS JOIN b CROSS JOIN c)")

        expr = parse_one("select * from ((a cross join b) cross join c) t")
        self.assertIsInstance(expr.args["from"].this, exp.Subquery)
        self.assertEqual(len(expr.args["from"].this.this.args["joins"]), 2)
        self.assertEqual(
            expr.sql(), "SELECT * FROM (SELECT * FROM a CROSS JOIN b CROSS JOIN c) AS t"
        )

        expr = parse_one("select * from (a cross join (b cross join c))")
        self.assertIsInstance(expr.args["from"].this, exp.Table)
        self.assertTrue(expr.args["from"].this.args["wrapped"])
        self.assertEqual(len(expr.args["from"].this.args["joins"]), 1)
        self.assertIsInstance(expr.args["from"].this.args["joins"][0].this, exp.Table)
        self.assertTrue(expr.args["from"].this.args["joins"][0].this.args["wrapped"])
        self.assertEqual(expr.sql(), "SELECT * FROM (a CROSS JOIN (b CROSS JOIN c))")

        expr = parse_one("select * from ((a cross join ((b cross join c) cross join d)))")
        self.assertEqual(expr.sql(), "SELECT * FROM (a CROSS JOIN (b CROSS JOIN c CROSS JOIN d))")

        expr = parse_one(
            "select * from ((a cross join ((b cross join c) cross join (d cross join e))))"
        )
        self.assertEqual(
            expr.sql(), "SELECT * FROM (a CROSS JOIN (b CROSS JOIN c CROSS JOIN (d CROSS JOIN e)))"
        )
