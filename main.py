"""Optional terminal interface for QueryPilot."""
from __future__ import annotations

from agent import DataAgent


def main() -> None:
    agent = DataAgent()
    history: list[tuple[str, str]] = []

    print("QueryPilot terminal. Type 'exit' to quit.")
    while True:
        question = input("\nQuestion: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue

        result = agent.query(question, history=history)
        print(f"\nDomain: {result.get('domain')}")
        if result.get("validated_sql"):
            print(f"SQL: {result['validated_sql']}")
        print(f"\n{result['answer']}")
        history.extend([("human", question), ("ai", result["answer"])])


if __name__ == "__main__":
    main()

