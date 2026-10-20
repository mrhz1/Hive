import os
import socket
import subprocess
import sys

SERVER = os.environ.get("CARBON_SERVER", "carbon.research.sickkids.ca")
SHARE = os.environ.get("CARBON_SHARE", rf"\\{SERVER}\imagecorelab")
USER = os.environ.get("CARBON_USER", "")
PASSWORD = os.environ.get("CARBON_PASSWORD", "")


def step(label, action):
    try:
        result = action()
        print(f"OK    {label}" + (f": {result}" if result is not None else ""))
        return True
    except Exception as exc:
        print(f"FAIL  {label}: {type(exc).__name__}: {exc}")
        return False


def install(package):
    import importlib
    import site

    done = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--user", package],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout).strip()[-500:])
    user_site = site.getusersitepackages()
    if user_site not in sys.path:
        sys.path.append(user_site)
    importlib.invalidate_caches()


def kerberos_ticket():
    try:
        done = subprocess.run(["klist"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return "klist not found"
    return (done.stdout or done.stderr).strip()[:400] or "no output"


def main():
    print(f"server {SERVER}, share {SHARE}")
    if not step("name lookup", lambda: socket.gethostbyname(SERVER)):
        return
    if not step("port 445 open", lambda: socket.create_connection((SERVER, 445), timeout=10).close()):
        return
    try:
        import smbclient
    except ImportError:
        if not step("install smbprotocol", lambda: install("smbprotocol[kerberos]")):
            return
        import smbclient
    try:
        import gssapi
    except ImportError:
        step("install kerberos support", lambda: install("smbprotocol[kerberos]"))

    print(f"kerberos ticket:\n{kerberos_ticket()}")

    if step(
        "login with kerberos (no password)",
        lambda: smbclient.register_session(SERVER, auth_protocol="kerberos"),
    ):
        step("list share", lambda: sorted(smbclient.listdir(SHARE))[:20])
        return

    if not (USER and PASSWORD):
        print("SKIP  login with password: set CARBON_USER and CARBON_PASSWORD to try it")
        return
    if step(
        f"login as {USER}",
        lambda: smbclient.register_session(SERVER, username=USER, password=PASSWORD),
    ):
        step("list share", lambda: sorted(smbclient.listdir(SHARE))[:20])


if __name__ == "__main__":
    main()
