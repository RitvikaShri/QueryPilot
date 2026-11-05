
"""LangGraph NL-to-SQL analytics agent using local Ollama models."""
from __future__ import annotations

import os
import re
from typing import Any, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from config import DEFAULT_DOMAIN, DOMAINS
from dataset import DemoDataset
from sql_safety import validate_select_sql
from visualization import suggest_chart


load_dotenv()

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")


# ---------------------------------------------------------
# AGENT STATE
# ---------------------------------------------------------

class DataAgentState(TypedDict, total=False):
    question: str
    history: list[tuple[str, str]]
    standalone_question: str
    domain: str
    sql: str
    validated_sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    answer: str
    insights: list[str]
    chart: dict[str, str] | None
    error: str | None


# ---------------------------------------------------------
# DATA AGENT
# ---------------------------------------------------------

class DataAgent:
    """A multi-domain analytics agent: route, generate SQL,
    validate, execute, visualize, and answer.
    """

    def __init__(
        self,
        dataset: DemoDataset | None = None,
        verbose: bool = False,
    ) -> None:

        self.dataset = dataset or DemoDataset()
        self.verbose = verbose

        self.llm = ChatOllama(
            model=DEFAULT_MODEL,
            temperature=0,
        )

        self.graph = self._build_graph()

    def query(
        self,
        question: str,
        history: list[tuple[str, str]] | None = None,
    ) -> DataAgentState:

        return self.graph.invoke(
            {
                "question": question,
                "history": history or [],
            }
        )

    # -----------------------------------------------------
    # LANGGRAPH WORKFLOW
    # -----------------------------------------------------

    def _build_graph(self):

        graph = StateGraph(DataAgentState)

        graph.add_node("rewrite", self._rewrite_question)
        graph.add_node("route", self._route_question)
        graph.add_node("write_sql", self._write_sql)
        graph.add_node("validate_sql", self._validate_sql)
        graph.add_node("execute_sql", self._execute_sql)
        graph.add_node("answer", self._answer)

        graph.set_entry_point("rewrite")

        graph.add_edge("rewrite", "route")
        graph.add_edge("route", "write_sql")
        graph.add_edge("write_sql", "validate_sql")
        graph.add_edge("validate_sql", "execute_sql")
        graph.add_edge("execute_sql", "answer")
        graph.add_edge("answer", END)

        return graph.compile()

    # -----------------------------------------------------
    # 1. QUESTION REWRITING
    # -----------------------------------------------------

    def _rewrite_question(
        self,
        state: DataAgentState,
    ) -> dict[str, Any]:

        question = state["question"]
        history = state.get("history", [])

        if not history:
            return {"standalone_question": question}

        history_text = _format_history(history[-6:])

        messages = [
            SystemMessage(
                content=(
                    "Rewrite the user's latest analytics question "
                    "into a standalone question. "
                    "Preserve all metrics, dimensions, filters, "
                    "time periods, entities, and domain context. "
                    "Do not add new requirements. "
                    "Return only the rewritten question."
                )
            ),
            HumanMessage(
                content=(
                    f"Conversation:\n{history_text}\n\n"
                    f"Latest question: {question}"
                )
            ),
        ]

        try:
            rewritten = self.llm.invoke(messages).content.strip()
        except Exception:
            rewritten = question

        return {
            "standalone_question": rewritten or question
        }

    # -----------------------------------------------------
    # 2. DOMAIN ROUTING
    # -----------------------------------------------------

    def _route_question(
        self,
        state: DataAgentState,
    ) -> dict[str, Any]:

        question = (
            state.get("standalone_question")
            or state["question"]
        )

        # Strong domain keywords take precedence over LLM routing.
        keyword_domain = _keyword_domain(question)

        if keyword_domain:
            if self.verbose:
                print(f"Domain selected by keywords: {keyword_domain}")

            return {"domain": keyword_domain}

        domain_descriptions = "\n".join(
            f"- {name}: {domain.description}"
            for name, domain in DOMAINS.items()
        )

        messages = [
            SystemMessage(
                content=(
                    "You are a data analytics domain router. "
                    "Choose exactly one domain from the provided list: "
                    "sales, support, hr. "
                    "Choose HR for employee, payroll, attendance, "
                    "salary, leave, and workforce analytics. "
                    "Choose support for customer support tickets "
                    "and issue resolution. "
                    "Choose sales for revenue, orders, products, "
                    "inventory, and sales channels. "
                    "Return only the domain name."
                )
            ),
            HumanMessage(
                content=(
                    f"Domains:\n{domain_descriptions}\n\n"
                    f"Question: {question}"
                )
            ),
        ]

        try:
            raw_domain = self.llm.invoke(messages).content.strip().lower()
        except Exception:
            raw_domain = ""

        domain = (
            _pick_domain(raw_domain)
            or _keyword_domain(question)
            or DEFAULT_DOMAIN
        )

        if self.verbose:
            print(f"Selected domain: {domain}")

        return {"domain": domain}

    # -----------------------------------------------------
    # 3. SQL GENERATION
    # -----------------------------------------------------

    def _write_sql(
        self,
        state: DataAgentState,
    ) -> dict[str, Any]:

        question = (
            state.get("standalone_question")
            or state["question"]
        )

        domain = DOMAINS[state["domain"]]

        schema = self.dataset.schema_text(domain.tables)

        system_prompt = _build_sql_prompt(domain.name)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=(
                    f"Domain: {domain.name}\n"
                    f"Allowed tables: {', '.join(domain.tables)}\n\n"
                    f"Schema:\n{schema}\n\n"
                    f"Question: {question}"
                )
            ),
        ]

        sql = self.llm.invoke(messages).content

        generated_sql = _extract_sql(sql)

        if self.verbose:
            print(f"Generated SQL:\n{generated_sql}")

        return {"sql": generated_sql}

    # -----------------------------------------------------
    # 4. SQL VALIDATION
    # -----------------------------------------------------

    def _validate_sql(
        self,
        state: DataAgentState,
    ) -> dict[str, Any]:

        domain = DOMAINS[state["domain"]]

        result = validate_select_sql(
            state.get("sql", ""),
            set(domain.tables),
        )

        if not result.ok:
            return {
                "error": result.error,
                "validated_sql": "",
            }

        return {
            "validated_sql": result.sql,
            "error": None,
        }

    # -----------------------------------------------------
    # 5. SQL EXECUTION AND VISUALIZATION
    # -----------------------------------------------------

    def _execute_sql(
        self,
        state: DataAgentState,
    ) -> dict[str, Any]:

        if state.get("error"):
            return {
                "rows": [],
                "columns": [],
                "chart": None,
            }

        try:
            result = self.dataset.execute(
                state["validated_sql"]
            )

        except Exception as exc:
            return {
                "error": f"Query failed: {exc}",
                "rows": [],
                "columns": [],
                "chart": None,
            }

        chart = suggest_chart(result.rows)
        insights = _build_result_insights(result.rows)

        return {
            "rows": result.rows,
            "columns": result.columns,
            "chart": chart,
            "insights": insights,
        }

    # -----------------------------------------------------
    # 6. NATURAL LANGUAGE ANSWER
    # -----------------------------------------------------

    def _answer(
        self,
        state: DataAgentState,
    ) -> dict[str, Any]:
        """Create a factual response without asking the LLM to reproduce data.

        SQL rows remain the single source of truth. The UI renders those rows
        as a table/chart, while this message only reports execution status.
        This avoids model-generated changes to names, counts, rankings, or
        financial values.
        """

        if state.get("error"):
            return {
                "answer": (
                    "I could not run a safe query for that request. "
                    f"Reason: {state['error']}"
                )
            }

        row_count = len(state.get("rows", []))
        insights = state.get("insights", [])

        if row_count == 0:
            answer = "The query completed successfully, but no matching results were found."
        elif row_count == 1:
            answer = "The query returned 1 result."
        else:
            answer = f"The query returned {row_count} results."

        return {"answer": answer, "insights": insights}


# ---------------------------------------------------------
# DATA-GROUNDED INSIGHT GENERATION
# ---------------------------------------------------------

def _build_result_insights(rows: list[dict[str, Any]]) -> list[str]:
    """Create concise, deterministic observations from the returned SQL rows.

    This layer never asks the LLM to restate numbers. It aggregates the
    returned result rows by categorical dimensions and formats the actual
    values, so insight text cannot drift away from the displayed table.
    """
    if not rows:
        return []

    columns = list(rows[0].keys())

    numeric_columns = [
        column for column in columns
        if not column.lower().endswith(("_id", " id"))
        and all(
            row.get(column) in (None, "") or _is_numeric_value(row.get(column))
            for row in rows
        )
        and any(_is_numeric_value(row.get(column)) for row in rows)
    ]

    categorical_columns = [
        column for column in columns
        if column not in numeric_columns
        and not column.lower().endswith(("_id", " id"))
    ]

    if not numeric_columns:
        return [f"{len(rows):,} matching records were returned."]

    insights: list[str] = []

    # For a single row, present the returned metric values without inference.
    if len(rows) == 1:
        row = rows[0]
        parts = [
            f"{_humanize_column(column)}: {_format_insight_value(column, row[column])}"
            for column in numeric_columns[:3]
            if row.get(column) is not None
        ]
        if parts:
            return ["Key result — " + "; ".join(parts) + "."]

    # Generate a few top-level observations without overwhelming the user.
    for measure in numeric_columns[:3]:
        candidates = []

        for dimension in categorical_columns:
            values = {
                str(row.get(dimension))
                for row in rows
                if row.get(dimension) is not None
            }

            if 2 <= len(values) <= 12:
                totals: dict[str, float] = {}

                for row in rows:
                    category = row.get(dimension)
                    value = row.get(measure)

                    if category is None or not _is_numeric_value(value):
                        continue

                    key = str(category)
                    totals[key] = totals.get(key, 0.0) + float(value)

                if len(totals) >= 2:
                    candidates.append((dimension, totals))

        # Prefer the first categorical dimension in the SQL result order.
        for dimension, totals in candidates[:2]:
            operation = "average" if any(
                token in measure.lower()
                for token in ("avg", "average", "mean", "rate", "percentage")
            ) else "total"

            # Remove redundant prefixes from the metric label.
            metric_label = _humanize_column(measure)
            metric_label = re.sub(
                r"^(average|avg|mean|total)\s+",
                "",
                metric_label,
                flags=re.IGNORECASE,
            )

            if operation == "average":
                grouped_values: dict[str, list[float]] = {}

                for row in rows:
                    category = row.get(dimension)
                    value = row.get(measure)

                    if category is not None and _is_numeric_value(value):
                        grouped_values.setdefault(str(category), []).append(
                            float(value)
                        )

                totals = {
                    key: sum(vals) / len(vals)
                    for key, vals in grouped_values.items()
                    if vals
                }

            highest_value = max(totals.values())

            highest_categories = [
                category
                for category, value in totals.items()
                if abs(value - highest_value) < 1e-9
            ]

            measure_label = metric_label.lower()
            dimension_label = _humanize_column(dimension)
            leaders = ", ".join(highest_categories)
            tie_word = "are tied for" if len(highest_categories) > 1 else "has"

            sentence = (
                f"{leaders} {tie_word} the highest {operation} {measure_label} "
                f"across the returned {dimension_label.lower()} groups "
                f"({_format_insight_value(measure, highest_value)})."
            )

            if sentence not in insights:
                insights.append(sentence)

            if len(insights) >= 3:
                return insights

    if not insights:
        insights.append(
            f"The result contains {len(rows):,} rows and "
            f"{len(numeric_columns):,} numeric measure(s)."
        )

    return insights[:3]


def _is_numeric_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _humanize_column(column: str) -> str:
    return re.sub(r"\s+", " ", column.replace("_", " ")).strip().title()


def _format_insight_value(column: str, value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    currency_tokens = (
        "revenue", "payroll", "salary", "deduction", "overtime_pay",
        "gross_pay", "net_pay", "unit_price", "allowance", "bonus",
    )
    if any(token in column.lower() for token in currency_tokens):
        return f"₹{number:,.2f}".rstrip("0").rstrip(".")
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------
# SQL PROMPT BUILDER
# ---------------------------------------------------------

def _build_sql_prompt(domain: str) -> str:

    common_rules = """
You are an expert SQLite analytics SQL generator.

Generate exactly one SQL SELECT query that answers the user's
complete question.

STRICT SQL RULES:

1. Return only SQL. No markdown or explanations.
2. Use only tables and columns from the provided schema.
3. Every requested grouping dimension must appear in SELECT.
4. Every non-aggregated selected column must be included in GROUP BY
   when aggregation is used.
5. Never introduce additional grouping dimensions.
6. Never invent WHERE conditions, filters, or date ranges.
7. Only apply filters explicitly requested by the user.
8. Give every calculated column a meaningful alias.
9. Use SQLite-compatible SQL.
10. Do not use columns that are absent from the schema.
11. Use joins only when necessary to answer the question.
12. Use the correct aggregation for the requested metric.
13. Do not silently change the meaning of the user's question.
14. Never use SELECT * for analytical queries.
15. Keep the query limited to the requested information.

"""

    if domain == "sales":

        return common_rules + """
SALES-SPECIFIC RULES:

- Orders may contain multiple line items for the same order_id.
- When counting unique orders, use COUNT(DISTINCT order_id).
- When counting units sold, use SUM(quantity).
- When calculating revenue, use SUM(quantity * unit_price).
- Join customers using customer_id when customer information is needed.
- Join products using product_id when product information is needed.
- When asked which region generated the most revenue, calculate total revenue across all available periods.
- Do not include month in SELECT or GROUP BY unless the user explicitly requests monthly revenue.
- Use GROUP BY region, ORDER BY total_revenue DESC, and LIMIT 1 for highest-revenue region questions.

EXAMPLES:

Question: Show number of orders by status and channel.
SQL:
SELECT status, channel,
COUNT(DISTINCT order_id) AS number_of_orders
FROM orders
GROUP BY status, channel

Question: Show monthly revenue by channel.
SQL:
SELECT STRFTIME('%Y-%m', order_date) AS month,
channel,
SUM(quantity * unit_price) AS revenue
FROM orders
GROUP BY month, channel

"""

    if domain == "support":

        return common_rules + """
SUPPORT-SPECIFIC RULES:

- Use support_tickets for ticket-related questions.
- Use COUNT(DISTINCT ticket_id) when counting tickets.
- Use AVG(resolution_hours) for average resolution time.
- Join customers using customer_id for customer segment or region analysis.
- Do not assume that pending_customer tickets are open unless requested.
- Do not invent ticket status or priority filters.

EXAMPLE:

Question: How many open support tickets are there by priority?
SQL:
SELECT priority, COUNT(DISTINCT ticket_id) AS ticket_count
FROM support_tickets
WHERE status = 'open'
GROUP BY priority

"""

    if domain == "hr":

        return common_rules + """
HR-SPECIFIC RULES:

AVAILABLE TABLES:

1. employees:
Employee master records. One row per employee.

2. attendance:
Daily attendance records. One row per employee per scheduled weekday.
Weekends are omitted.

3. leaves:
Leave applications. One row per leave request.

4. payroll:
Monthly payroll. One row per employee per pay period.

TABLE RELATIONSHIPS:

- employees.employee_id = attendance.employee_id
- employees.employee_id = leaves.employee_id
- employees.employee_id = payroll.employee_id

EMPLOYEE ANALYTICS:

- Use employees for employee counts and department analysis.
- COUNT(DISTINCT employee_id) when counting employees.
- Use department and designation from employees.
- basic_monthly_salary represents the employee's basic monthly salary.

ATTENDANCE ANALYTICS:

- Present records have attendance_status = 'Present'.
- Absent records have attendance_status = 'Absent'.
- Approved leave is reflected as attendance_status = 'On Leave'.
- For attendance percentage excluding approved leave:
  Present records / (Present records + Absent records) * 100.
- For absenteeism percentage excluding approved leave:
  Absent records / (Present records + Absent records) * 100.
- Use attendance_date for date-based attendance analysis.
- Use working_hours for working-hour analysis.
- A late arrival is a check_in time later than 09:00.
- Attendance contains weekdays only.
- SQLite does not support PostgreSQL-style or generic expression casts such as SUM(...) AS Double.
- Never append AS Double, AS Float, or AS Integer to an arithmetic expression.
- For percentage calculations, multiply the numerator by 100.0 before dividing to ensure floating-point division.
- Use NULLIF(denominator, 0) to prevent division by zero.
- Use ROUND(expression, 2) for two-decimal precision.

LEAVE ANALYTICS:

- Use leaves for leave application analysis.
- Use approval_status = 'Approved' when the user explicitly asks
  for approved leave.
- Use SUM(leave_days) for total leave days.
- Use COUNT(DISTINCT leave_id) for leave application counts.
- Do not assume pending or rejected requests are approved.
- Do not invent leave balances; the dataset does not contain them.

PAYROLL ANALYTICS:

- Use payroll for monthly payroll calculations.
- Join employees using employee_id when department,
  designation, or employee details are needed.
- gross_salary represents earnings before deductions.
- total_deductions represents all deductions.
- net_salary represents take-home salary.
- Use SUM(gross_salary) for total gross payroll.
- Use SUM(total_deductions) for total deductions.
- Use SUM(net_salary) for total net payroll.
- Use pay_period for monthly payroll comparisons.
- Use SUM(overtime_pay) for total overtime compensation.
- Use SUM(overtime_hours) for total overtime hours.
- Use AVG(net_salary) for average net salary.
- When asked for the highest or lowest total deductions by department, aggregate across all pay periods unless a specific period is requested.
- Do not include pay_period in GROUP BY unless the user explicitly asks for a monthly or period-wise breakdown.
- When asked which department has the highest total deductions, GROUP BY department, ORDER BY total_deductions DESC, and LIMIT 1.
- Distinguish between monthly payroll breakdowns and overall payroll totals.
- When the user asks to compare a metric across departments, return all departments.
- Do not use LIMIT 1 for comparison questions.
- Use ORDER BY to rank the comparison results when useful.
- Only use LIMIT 1 when the user explicitly asks for the highest, lowest, maximum, or minimum entity.

SQL EXTRA RULES:
- When ranking employees or departments, preserve ties.
- Do not arbitrarily exclude entities with the same metric value at the ranking cutoff.
- If the user asks for the top N, consider using RANK() or DENSE_RANK() when ties should be included.

EXTRA RULES:

- When asked for absenteeism or absenteeism rate, calculate Absent / (Present + Absent) * 100. 
- Exclude On Leave records from the denominator. 
- Do not use COUNT(Absent) alone to identify the department with the highest absenteeism. 
- Attendance records represent employee-days, not unique employees. 
- Never label absent attendance records as absent employee counts.

EXAMPLE — Highest absenteeism department:

Question:
Which department has the highest absenteeism?

SQL:
SELECT
    e.department,
    ROUND(
        100.0 * SUM(
            CASE
                WHEN a.attendance_status = 'Absent'
                THEN 1 ELSE 0
            END
        ) /
        NULLIF(
            SUM(
                CASE
                    WHEN a.attendance_status IN ('Present', 'Absent')
                    THEN 1 ELSE 0
                END
            ),
            0
        ),
        2
    ) AS absenteeism_percentage
FROM attendance a
JOIN employees e
    ON a.employee_id = e.employee_id
GROUP BY e.department
ORDER BY absenteeism_percentage DESC
LIMIT 1;

CRITICAL:
- Never filter the WHERE clause to only Absent records.
- Both Present and Absent records are required.
- Exclude On Leave records from the denominator.
- Return the department and absenteeism percentage.

IMPORTANT JOIN RULE:

Payroll contains one row per employee per month.
Do not join payroll directly with attendance or leaves for
simple payroll totals because multiple attendance or leave rows
can multiply payroll records and inflate the totals.

When grouping payroll by department, join payroll to employees
using employee_id and group by employees.department.

EXAMPLES:

Question: How many employees are there in each department?
SQL:
SELECT department, COUNT(DISTINCT employee_id) AS employee_count
FROM employees
GROUP BY department

Question: Show monthly attendance percentage by department.
SQL:
SELECT
    e.department,
    STRFTIME('%Y-%m', a.attendance_date) AS month,
    ROUND(
        100.0 * SUM(
            CASE
                WHEN a.attendance_status = 'Present'
                THEN 1 ELSE 0
            END
        ) /
        NULLIF(
            SUM(
                CASE
                    WHEN a.attendance_status IN ('Present', 'Absent')
                    THEN 1 ELSE 0
                END
            ),
            0
        ),
        2
    ) AS attendance_percentage
FROM attendance a
JOIN employees e
    ON a.employee_id = e.employee_id
GROUP BY
    e.department,
    month
ORDER BY
    e.department,
    month
LIMIT 50;

Question: Calculate gross and net payroll by department and month.
SQL:
SELECT
    e.department,
    p.pay_period,
    SUM(p.gross_salary) AS gross_payroll,
    SUM(p.net_salary) AS net_payroll
FROM payroll p
JOIN employees e ON p.employee_id = e.employee_id
GROUP BY e.department, p.pay_period

Question: Which employees have taken the most approved leaves?
SQL:
SELECT
    e.employee_name,
    e.department,
    SUM(l.leave_days) AS approved_leave_days
FROM leaves l
JOIN employees e ON l.employee_id = e.employee_id
WHERE l.approval_status = 'Approved'
GROUP BY e.employee_id, e.employee_name, e.department
ORDER BY approved_leave_days DESC

"""

    return common_rules


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def _format_history(
    history: list[tuple[str, str]],
) -> str:

    return "\n".join(
        f"{role}: {content}"
        for role, content in history
    )


def _pick_domain(text: str) -> str | None:

    for domain in DOMAINS:

        if re.search(
            rf"\b{re.escape(domain)}\b",
            text,
            re.IGNORECASE,
        ):
            return domain

    return None


def _keyword_domain(question: str) -> str | None:

    lowered = question.lower()

    # HR takes precedence when clear HR terminology is present.
    hr_words = {
        "employee",
        "employees",
        "workforce",
        "attendance",
        "absenteeism",
        "payroll",
        "salary",
        "salaries",
        "payslip",
        "payslips",
        "leave",
        "leaves",
        "designation",
        "joining date",
        "working hours",
        "overtime",
        "deduction",
        "deductions",
        "allowance",
        "allowances",
        "bonus",
        "bonuses",
        "gross pay",
        "net pay",
        "gross salary",
        "net salary",
        "pf",
        "hra",
        "professional tax",
        "late arrivals",
        "late arrival",
        "department",
        "departments",
    }

    support_words = {
        "ticket",
        "tickets",
        "support",
        "priority",
        "resolution",
        "refund",
        "damaged",
    }

    sales_words = {
        "revenue",
        "sales",
        "orders",
        "products",
        "inventory",
        "channel",
        "region",
    }

    if any(word in lowered for word in hr_words):
        return "hr"

    if any(word in lowered for word in support_words):
        return "support"

    if any(word in lowered for word in sales_words):
        return "sales"

    return None


def _extract_sql(text: str) -> str:

    cleaned = text.strip()

    if cleaned.startswith("```"):

        cleaned = re.sub(
            r"^```[a-zA-Z0-9_+-]*\s*",
            "",
            cleaned,
        )

        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        )

    match = re.search(
        r"\b(with|select)\b",
        cleaned,
        re.IGNORECASE,
    )

    if match:
        cleaned = cleaned[match.start():]

    return cleaned.strip()
