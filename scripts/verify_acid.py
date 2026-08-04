"""Prove transactional ORC actually works: insert a row, SELECT it, DELETE
it by id, confirm it's gone. Run with: make verify
"""
import os
import sys

from dotenv import load_dotenv
from impala.dbapi import connect

load_dotenv(".env.local")

# ids are application-generated UUID STRINGs (Hive has no sequences).
TEST_ID = "acid-test-00000000-0000-0000-0000-000000000000"


def connect_from_env():
    return connect(
        host=os.environ["HIVE_HOST"],
        port=int(os.environ["HIVE_PORT"]),
        database=os.environ["HIVE_DB"],
        auth_mechanism=os.environ["HIVE_AUTH"],
        user=os.environ["HIVE_USER"],
    )


def main() -> int:
    try:
        conn = connect_from_env()
    except Exception as exc:
        print(f"FAILED to connect to hive -- {exc}", file=sys.stderr)
        return 1

    try:
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO `users` (`id`, `username`, `email`, `first_name`, "
            "`last_name`, `status`, `is_active`, `role_id`, `created_at`) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                TEST_ID,
                "acid-test",
                "acid-test@example.com",
                "Acid",
                "Test",
                "active",
                True,
                None,
                "2026-08-01 00:00:00",
            ),
        )
        print(f"inserted row id={TEST_ID}")

        cursor.execute(
            "SELECT `id`, `username` FROM `users` WHERE `id` = %s", (TEST_ID,)
        )
        rows = cursor.fetchall()
        if not rows:
            print(f"FAILED: row id={TEST_ID} not found after INSERT", file=sys.stderr)
            return 1
        print(f"SELECT confirmed row present: {rows}")

        cursor.execute("DELETE FROM `users` WHERE `id` = %s", (TEST_ID,))
        print(f"deleted row id={TEST_ID}")

        cursor.execute(
            "SELECT `id` FROM `users` WHERE `id` = %s", (TEST_ID,)
        )
        rows_after = cursor.fetchall()
        if rows_after:
            print(
                f"FAILED: row id={TEST_ID} still present after DELETE -- "
                "table is not transactional (check STORED AS ORC + managed table)",
                file=sys.stderr,
            )
            return 1

    except Exception as exc:
        print(f"FAILED during ACID verification -- {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print("ACID verification passed: INSERT, SELECT, DELETE all worked as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
