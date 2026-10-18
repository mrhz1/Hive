import os
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"
NAMES = ["HIVE_HOST", "HIVE_PORT", "HIVE_DB", "HIVE_AUTH", "HIVE_USER", "HIVE_SERVICE",
         "READ_ENGINE", "CML_IMPALA_CONNECTION", "KRB5_CONFIG", "KRB5CCNAME"]


def file_values():
    found = {}
    if not ENV_FILE.is_file():
        return found
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def main():
    print(f"code folder {ROOT}")
    print(f".env.local  {ENV_FILE} {'found' if ENV_FILE.is_file() else 'NOT FOUND'}")
    in_file = file_values()
    before = {name: os.environ.get(name) for name in NAMES}

    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)

    print("\nsetting                 used by the app          from")
    for name in NAMES:
        used = os.environ.get(name)
        if before[name] is not None:
            source = "Cloudera environment variable"
            if name in in_file and in_file[name] != before[name]:
                source += f" (OVERRIDES .env.local value {in_file[name]!r})"
        elif name in in_file:
            source = ".env.local"
        else:
            source = "not set"
        print(f"  {name:22s}{str(used):25s}{source}")

    host = os.environ.get("HIVE_HOST", "")
    print(f"\nname lookup of {host}:")
    try:
        address = socket.gethostbyname(host)
        print(f"  address {address}")
        print(f"  full name {socket.getfqdn(host)}")
        print(f"  reverse name {socket.gethostbyaddr(address)[0]}")
    except OSError as exc:
        print(f"  failed: {exc}")

    try:
        done = subprocess.run(["klist"], capture_output=True, text=True, timeout=10)
        print("\nklist:\n" + (done.stdout or done.stderr).strip())
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"\nklist failed: {exc}")

    from impala.dbapi import connect
    service = os.environ.get("HIVE_SERVICE", "hive")
    print(f"\nconnecting to hive as the app does (service {service}/{host})")
    try:
        connection = connect(
            host=host,
            port=int(os.environ["HIVE_PORT"]),
            database=os.environ["HIVE_DB"],
            auth_mechanism=os.environ["HIVE_AUTH"],
            user=os.environ["HIVE_USER"],
            kerberos_service_name=service,
        )
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        print(f"OK    hive answered {cursor.fetchall()}")
        connection.close()
    except Exception as exc:
        print(f"FAIL  {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
