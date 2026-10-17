import os
import socket
from getpass import getpass

SERVER = "carbon.research.sickkids.ca"
SHARE = rf"\\{SERVER}\expedition"
USER = r"SICKKIDS\dap_carbon"


def step(label, action):
    try:
        result = action()
        print(f"OK    {label}" + (f": {result}" if result is not None else ""))
        return True
    except Exception as exc:
        print(f"FAIL  {label}: {type(exc).__name__}: {exc}")
        return False


def install_smbprotocol():
    import importlib
    import site
    import subprocess
    import sys

    done = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--user", "smbprotocol"],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout).strip()[-500:])
    user_site = site.getusersitepackages()
    if user_site not in sys.path:
        sys.path.append(user_site)
    importlib.invalidate_caches()


def main():
    if not step("name lookup", lambda: socket.gethostbyname(SERVER)):
        return
    if not step("port 445 open", lambda: socket.create_connection((SERVER, 445), timeout=10).close()):
        return
    try:
        import smbclient
    except ImportError:
        if not step("install smbprotocol", install_smbprotocol):
            return
        import smbclient

    password = os.environ.get("CARBON_PASSWORD") or getpass(f"Password for {USER}: ")
    if not step(
        "login",
        lambda: smbclient.register_session(SERVER, username=USER, password=password),
    ):
        return
    step("list share", lambda: sorted(smbclient.listdir(SHARE))[:20])


if __name__ == "__main__":
    main()
