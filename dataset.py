
"""Load QueryPilot sample datasets into an in-memory SQLite database."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"


# ---------------------------------------------------------
# TABLE REGISTRY
# ---------------------------------------------------------

TABLE_FILES: dict[str, str] = {
    # Sales
    "products": "products.csv",
    "customers": "customers.csv",
    "orders": "orders.csv",

    # Support
    "support_tickets": "support_tickets.csv",

    # HR
    "employees": "employees.csv",
    "attendance": "attendance.csv",
    "leaves": "leaves.csv",
    "payroll": "payroll.csv",
}


# ---------------------------------------------------------
# TABLE DESCRIPTIONS
# ---------------------------------------------------------

TABLE_DESCRIPTIONS: dict[str, str] = {
    # Sales
    "products": (
        "Product catalog with price, category, inventory, "
        "and reorder threshold."
    ),
    "customers": (
        "Customer profile table with segment, region, and signup date."
    ),
    "orders": (
        "Order line items with date, customer, product, quantity, "
        "channel, and status. Each order_id may appear in multiple rows."
    ),

    # Support
    "support_tickets": (
        "Customer support tickets with category, priority, "
        "status, and resolution hours."
    ),

    # HR
    "employees": (
        "Employee master records containing employee details, department, "
        "designation, employment type, location, joining date, employment "
        "status, and basic monthly salary. One row per employee."
    ),
    "attendance": (
        "Daily employee attendance records containing attendance date, "
        "check-in, check-out, attendance status, and working hours. "
        "One row per employee per scheduled weekday. Weekends are omitted."
    ),
    "leaves": (
        "Employee leave applications containing leave type, start date, "
        "end date, leave days, approval status, and reason category. "
        "One row per leave application."
    ),
    "payroll": (
        "Monthly employee payroll records containing basic pay, HRA, "
        "special allowance, transport allowance, overtime hours and pay, "
        "bonus, gross salary, PF deduction, professional tax, income tax, "
        "other deductions, total deductions, and net salary. "
        "One row per employee per pay period. Monetary values are in INR."
    ),
}


# ---------------------------------------------------------
# COLUMN DESCRIPTIONS
# ---------------------------------------------------------

COLUMN_DESCRIPTIONS: dict[str, dict[str, str]] = {

    # SALES

    "products": {
        "product_id": "Primary product identifier.",
        "product_name": "Human-readable product name.",
        "category": "Product category.",
        "unit_price": "Current listed unit price in USD.",
        "inventory": "Current units on hand.",
        "reorder_level": "Inventory threshold where replenishment should be considered.",
    },

    "customers": {
        "customer_id": "Primary customer identifier.",
        "customer_name": "Customer display name.",
        "segment": "Customer segment: consumer, small_business, or enterprise.",
        "region": "US sales region.",
        "signup_date": "Customer signup date as YYYY-MM-DD.",
    },

    "orders": {
        "order_id": "Order identifier. May repeat across order line items.",
        "order_date": "Order date as YYYY-MM-DD.",
        "customer_id": "Foreign key into customers.",
        "product_id": "Foreign key into products.",
        "quantity": "Number of units ordered.",
        "unit_price": "Unit sale price in USD at order time.",
        "channel": "Sales channel: web, retail, or partner.",
        "status": "Order state such as delivered, shipped, returned, cancelled, or processing.",
    },

    # SUPPORT

    "support_tickets": {
        "ticket_id": "Primary support ticket identifier.",
        "created_date": "Ticket creation date as YYYY-MM-DD.",
        "customer_id": "Foreign key into customers.",
        "category": "Support issue category.",
        "priority": "Ticket priority: low, normal, high, or urgent.",
        "status": "Ticket state: open, closed, or pending_customer.",
        "resolution_hours": "Hours to close the ticket. Open tickets use 0.0.",
    },

    # HR

    "employees": {
        "employee_id": "Primary employee identifier. Used to join all HR tables.",
        "employee_name": "Employee full name.",
        "department": "Employee department.",
        "designation": "Employee job title or designation.",
        "employment_type": "Full-time or Contract.",
        "location": "Employee work location.",
        "joining_date": "Employee joining date as YYYY-MM-DD.",
        "employment_status": "Current employment status.",
        "basic_monthly_salary": "Employee basic monthly salary in INR.",
        "manager_id": "Employee ID of the reporting manager, if assigned.",
    },

    "attendance": {
        "attendance_id": "Primary attendance record identifier.",
        "employee_id": "Foreign key into employees.",
        "attendance_date": "Attendance date as YYYY-MM-DD.",
        "check_in": "Employee check-in time in HH:MM format.",
        "check_out": "Employee check-out time in HH:MM format.",
        "attendance_status": "Present, Absent, or On Leave.",
        "working_hours": "Total working hours for the day, excluding one-hour break.",
    },

    "leaves": {
        "leave_id": "Primary leave application identifier.",
        "employee_id": "Foreign key into employees.",
        "leave_type": "Annual, Sick, Casual, or Unpaid.",
        "start_date": "Leave start date as YYYY-MM-DD.",
        "end_date": "Leave end date as YYYY-MM-DD.",
        "leave_days": "Number of leave days requested.",
        "approval_status": "Approved, Pending, or Rejected.",
        "reason_category": "Personal, Medical, Family, or Vacation.",
    },

    "payroll": {
        "payroll_id": "Primary payroll record identifier.",
        "employee_id": "Foreign key into employees.",
        "pay_period": "Payroll month in YYYY-MM format.",
        "basic_pay": "Basic monthly salary in INR.",
        "hra": "House Rent Allowance in INR.",
        "special_allowance": "Special allowance in INR.",
        "transport_allowance": "Transport allowance in INR.",
        "overtime_hours": "Overtime hours worked.",
        "overtime_pay": "Overtime compensation in INR.",
        "bonus": "Additional bonus in INR.",
        "gross_salary": "Total earnings before deductions in INR.",
        "pf_deduction": "Provident Fund deduction in INR.",
        "professional_tax": "Professional tax deduction in INR.",
        "income_tax": "Illustrative income tax deduction in INR.",
        "other_deductions": "Other deductions in INR.",
        "total_deductions": "Sum of all payroll deductions in INR.",
        "net_salary": "Take-home salary after deductions in INR.",
    },
}


# ---------------------------------------------------------
# SQLITE COLUMN TYPES
# ---------------------------------------------------------

# SQLite uses dynamic typing, but explicit numeric affinities
# improve aggregation and comparison reliability.

INTEGER_COLUMNS = {
    "inventory",
    "reorder_level",
    "quantity",
    "leave_days",
    "overtime_hours",
}

REAL_COLUMNS = {
    "unit_price",
    "resolution_hours",
    "working_hours",
    "basic_monthly_salary",
    "basic_pay",
    "hra",
    "special_allowance",
    "transport_allowance",
    "overtime_pay",
    "bonus",
    "gross_salary",
    "pf_deduction",
    "professional_tax",
    "income_tax",
    "other_deductions",
    "total_deductions",
    "net_salary",
}


# ---------------------------------------------------------
# QUERY RESULT
# ---------------------------------------------------------

@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]


# ---------------------------------------------------------
# DEMO DATASET
# ---------------------------------------------------------

class DemoDataset:
    """SQLite-backed QueryPilot dataset.

    The database is rebuilt in memory from CSV files whenever
    the application starts.
    """

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir

        self.connection = sqlite3.connect(
            ":memory:",
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row

        self._load()

    @property
    def table_names(self) -> set[str]:
        return set(TABLE_FILES)

    def schema_text(
        self,
        table_names: tuple[str, ...] | list[str] | set[str],
    ) -> str:
        """Generate schema information for the LLM."""

        blocks: list[str] = []

        for table_name in table_names:

            if table_name not in TABLE_FILES:
                raise ValueError(f"Unknown table: {table_name}")

            columns = self._columns(table_name)
            column_lines = []

            for column in columns:
                description = COLUMN_DESCRIPTIONS.get(
                    table_name, {}
                ).get(column, "")

                column_type = self._column_type(column)

                suffix = f" - {description}" if description else ""

                column_lines.append(
                    f"  - {column} ({column_type}){suffix}"
                )

            blocks.append(
                "\n".join(
                    [
                        f"Table: {table_name}",
                        f"Description: {TABLE_DESCRIPTIONS.get(table_name, '')}",
                        "Columns:",
                        *column_lines,
                    ]
                )
            )

        return "\n\n".join(blocks)

    def execute(self, sql: str) -> QueryResult:
        """Execute a validated SQL query."""

        cursor = self.connection.execute(sql)

        columns = [
            description[0]
            for description in cursor.description or []
        ]

        rows = [
            dict(row)
            for row in cursor.fetchall()
        ]

        return QueryResult(
            sql=sql,
            columns=columns,
            rows=rows,
        )

    def preview(
        self,
        table_name: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return a small table preview."""

        if table_name not in self.table_names:
            raise ValueError(f"Unknown table: {table_name}")

        cursor = self.connection.execute(
            f"SELECT * FROM {self._quote_identifier(table_name)} LIMIT ?",
            (limit,),
        )

        return [
            dict(row)
            for row in cursor.fetchall()
        ]

    # -----------------------------------------------------
    # DATA LOADING
    # -----------------------------------------------------

    def _load(self) -> None:
        """Load every registered CSV into SQLite."""

        for table_name, filename in TABLE_FILES.items():

            path = self.data_dir / filename

            if not path.exists():
                raise FileNotFoundError(
                    f"Dataset file not found: {path}\n"
                    f"Please place {filename} inside the data directory."
                )

            self._load_csv(table_name, path)

    def _load_csv(
        self,
        table_name: str,
        path: Path,
    ) -> None:
        """Load a CSV file into a SQLite table."""

        with path.open(
            newline="",
            encoding="utf-8-sig",
        ) as handle:

            reader = csv.DictReader(handle)
            rows = list(reader)

            if not reader.fieldnames:
                raise ValueError(f"{path} has no header row")

            fieldnames = reader.fieldnames

        columns = [
            self._quote_identifier(column)
            for column in fieldnames
        ]

        column_definitions = []

        for column in fieldnames:
            sql_type = self._column_type(column)

            column_definitions.append(
                f"{self._quote_identifier(column)} {sql_type}"
            )

        self.connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS
            {self._quote_identifier(table_name)}
            ({', '.join(column_definitions)})
            """
        )

        # Rebuild the table whenever the application starts.
        self.connection.execute(
            f"DELETE FROM {self._quote_identifier(table_name)}"
        )

        placeholders = ", ".join(
            "?" for _ in fieldnames
        )

        quoted_columns = ", ".join(columns)

        values = [
            tuple(
                row.get(column) or None
                for column in fieldnames
            )
            for row in rows
        ]

        self.connection.executemany(
            f"""
            INSERT INTO {self._quote_identifier(table_name)}
            ({quoted_columns})
            VALUES ({placeholders})
            """,
            values,
        )

        self.connection.commit()

    # -----------------------------------------------------
    # SCHEMA HELPERS
    # -----------------------------------------------------

    def _columns(self, table_name: str) -> list[str]:

        cursor = self.connection.execute(
            f"PRAGMA table_info({self._quote_identifier(table_name)})"
        )

        return [
            row["name"]
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _column_type(column: str) -> str:

        if column in INTEGER_COLUMNS:
            return "INTEGER"

        if column in REAL_COLUMNS:
            return "REAL"

        return "TEXT"

    @staticmethod
    def _quote_identifier(identifier: str) -> str:

        escaped = identifier.replace('"', '""')

        return f'"{escaped}"'
