import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app import app, db, BudgetCycle, Transaction, User


LOCAL_DB_PATHS = [
    Path(__file__).resolve().parent / "budget.db",
    Path(__file__).resolve().parent / "instance" / "local_budget.db",
]


def parse_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        value = value.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            try:
                dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    return value


def migrate_table(local_conn, model, table_name, columns, row_factory=None):
    rows = local_conn.execute(
        f"SELECT {', '.join(columns)} FROM {table_name}"
    ).fetchall()

    migrated = 0
    for row in rows:
        data = dict(zip(columns, row))
        if row_factory:
            data = row_factory(data)

        if model is User:
            existing = User.query.filter_by(username=data.get("username")).first()
            if existing is not None:
                continue

        if model is Transaction:
            existing = Transaction.query.filter_by(id=data.get("id")).first()
            if existing is not None:
                continue

        if model is BudgetCycle:
            existing = BudgetCycle.query.filter_by(id=data.get("id")).first()
            if existing is not None:
                continue

        obj = model(**data)
        db.session.add(obj)
        migrated += 1

    return migrated


def main():
    local_db_path = next((p for p in LOCAL_DB_PATHS if p.exists()), None)
    if local_db_path is None:
        raise FileNotFoundError("No local SQLite database file found")

    print(f"Using local database: {local_db_path}")

    with app.app_context():
        db.create_all()

        with sqlite3.connect(local_db_path) as local_conn:
            local_conn.row_factory = sqlite3.Row

            user_count = migrate_table(
                local_conn,
                User,
                "users",
                ["id", "username", "password"],
            )

            tx_count = migrate_table(
                local_conn,
                Transaction,
                "transactions",
                ["id", "user_id", "title", "amount", "category", "date", "type", "description"],
                row_factory=lambda data: {
                    **data,
                    "date": parse_datetime(data["date"]),
                },
            )

            cycle_count = migrate_table(
                local_conn,
                BudgetCycle,
                "budget_cycle",
                ["id", "user_id", "reset_day", "last_reset_at"],
                row_factory=lambda data: {
                    **data,
                    "last_reset_at": parse_datetime(data["last_reset_at"]),
                },
            )

        db.session.commit()

        print(f"Migrated users: {user_count}")
        print(f"Migrated transactions: {tx_count}")
        print(f"Migrated budget cycles: {cycle_count}")

        print("Users now in Supabase:", User.query.count())
        print("Transactions now in Supabase:", Transaction.query.count())


if __name__ == "__main__":
    main()
