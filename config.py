
"""Domain configuration for QueryPilot."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainConfig:
    name: str
    description: str
    tables: tuple[str, ...]
    sample_questions: tuple[str, ...]


DOMAINS: dict[str, DomainConfig] = {
    "sales": DomainConfig(
        name="sales",
        description=(
            "Revenue, order trends, product sales, customer segments, regions, "
            "channels, and inventory questions."
        ),
        tables=("orders", "customers", "products"),
        sample_questions=(
            "What is revenue by region?",
            "Which products generated the most revenue?",
            "Show monthly revenue by channel.",
            "Which products are below reorder level?",
        ),
    ),

    "support": DomainConfig(
        name="support",
        description=(
            "Support ticket volume, ticket status, priority, resolution time, "
            "categories, and customer support operations."
        ),
        tables=("support_tickets", "customers", "orders", "products"),
        sample_questions=(
            "How many open support tickets are there by priority?",
            "What is the average resolution time by ticket category?",
            "Which customer segments have the most urgent tickets?",
            "Show support tickets by status.",
        ),
    ),

    "hr": DomainConfig(
        name="hr",
        description=(
            "Human resources analytics covering employee information, "
            "departments, designations, employment status, attendance, "
            "absenteeism, working hours, late arrivals, leave applications, "
            "leave applications and utilization, monthly payroll, salaries, "
            "allowances, bonuses, overtime, deductions, PF, taxes, and "
            "net salary. Use employee_id to join related HR tables."
        ),
        tables=(
            "employees",
            "attendance",
            "leaves",
            "payroll",
        ),
        sample_questions=(
            "How many employees are there in each department?",
            "Which department has the highest absenteeism?",
            "Show monthly attendance percentage by department.",
            "Which employees have taken the most approved leaves?",
            "Show leave requests by approval status and leave type.",
            "Calculate gross and net payroll by department and month.",
            "Which department has the highest total deductions?",
            "Compare overtime pay across departments.",
        ),
    ),
}


DEFAULT_DOMAIN = "sales"
