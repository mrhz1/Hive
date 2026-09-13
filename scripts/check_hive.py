import os
import sys
import time

from dotenv import load_dotenv
from impala.dbapi import connect

load_dotenv(".env.local")

DEFAULT_TIMEOUT = 150.0

RETRY_SECONDS = 5.0


def _timeout() -> float:
    try:
        return float(os.environ.get("HIVE_CHECK_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def attempt(host, port, database, auth_mechanism, user):
    conn = connect(
        host=host,
        port=port,
        database=database,
        auth_mechanism=auth_mechanism,
        user=user,
    )
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES")
        return cursor.fetchall()
    finally:
        conn.close()


def main() -> int:
    host = os.environ["HIVE_HOST"]
    port = int(os.environ["HIVE_PORT"])
    database = os.environ["HIVE_DB"]
    auth_mechanism = os.environ["HIVE_AUTH"]
    user = os.environ["HIVE_USER"]

    deadline = time.monotonic() + _timeout()
    waited = False
    failure = None

    while True:
        try:
            rows = attempt(host, port, database, auth_mechanism, user)
            break
        except Exception as exc:
            failure = exc

        if time.monotonic() + RETRY_SECONDS >= deadline:
            print(
                f"FAILED to reach hive at {host}:{port} "
                f"(auth={auth_mechanism}, user={user}) -- {failure}",
                file=sys.stderr,
            )
            print(
                "\nIf this says 'TSocket read 0 bytes', HiveServer2 closed the "
                "connection. Either it is still starting -- check "
                "`docker compose ps` and `docker compose logs -f hiveserver2` "
                "for 'Starting HiveServer2' -- or HIVE_AUTH in .env.local "
                "disagrees with hive.server2.authentication in "
                "conf/hive-site.xml (both should be NOSASL locally).",
                file=sys.stderr,
            )
            return 1

        if not waited:
            print(
                f"hive is not answering yet ({failure}); "
                f"retrying for up to {_timeout():.0f}s...",
                file=sys.stderr,
            )
            waited = True

        time.sleep(RETRY_SECONDS)

    print(f"Connected to {host}:{port} (auth={auth_mechanism}, user={user})")
    print("Databases:")
    for row in rows:
        print(f"  - {row[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
