"""Smoke test: confirm HiveServer2 is reachable via impyla with the same env vars used on Cloudera AI."""
import os
import sys

from dotenv import load_dotenv
from impala.dbapi import connect

load_dotenv(".env.local")


def main() -> int:
    host = os.environ["HIVE_HOST"]
    port = int(os.environ["HIVE_PORT"])
    database = os.environ["HIVE_DB"]
    auth_mechanism = os.environ["HIVE_AUTH"]
    user = os.environ["HIVE_USER"]

    try:
        conn = connect(
            host=host,
            port=port,
            database=database,
            auth_mechanism=auth_mechanism,
            user=user,
        )
    except Exception as exc:
        print(f"FAILED to connect to hive at {host}:{port} -- {exc}", file=sys.stderr)
        return 1

    try:
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES")
        rows = cursor.fetchall()
    except Exception as exc:
        print(f"FAILED to run SHOW DATABASES -- {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"Connected to {host}:{port} (auth={auth_mechanism}, user={user})")
    print("Databases:")
    for row in rows:
        print(f"  - {row[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
