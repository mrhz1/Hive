"""Find out how this Cloudera session can reach Ozone. Run in a Cloudera Session:

    python scripts/ozone_probe.py ofs://<service>/<volume>/<bucket>/UAT
    python scripts/ozone_probe.py ofs://<service>/<volume>/<bucket>/UAT --write-test

Without --write-test it only lists the folder. With --write-test it writes a small
test file (and a 5 MB one, to time it) under <root>/_hive_probe/, reads them back and
deletes them. It never touches anything else, and prints no file contents or secrets,
so the output is safe to paste back.
"""

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime


def show(label, value):
    print(f"  {label:<28} {value}")


def run(cmd, data=None, timeout=120):
    started = time.perf_counter()
    try:
        done = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}", 0.0
    took = time.perf_counter() - started
    text = (done.stdout or b"").decode(errors="replace") + (done.stderr or b"").decode(errors="replace")
    return done.returncode, text.strip(), took


def environment():
    print("\n[environment]")
    for name in ("HADOOP_CONF_DIR", "HADOOP_HOME", "JAVA_HOME", "OZONE_CONF_DIR", "KRB5CCNAME", "CLASSPATH"):
        value = os.environ.get(name)
        show(name, "(not set)" if value is None else (value if name != "CLASSPATH" else f"set, {len(value)} chars"))
    for tool in ("ozone", "hdfs", "hadoop", "klist", "java"):
        show(f"which {tool}", shutil.which(tool) or "not found")
    if shutil.which("klist"):
        code, text, _ = run(["klist"])
        principal = next((l.split(":", 1)[1].strip() for l in text.splitlines() if "principal" in l.lower()), None)
        show("kerberos ticket", f"yes ({principal})" if code == 0 and principal else "none (klist failed)")
    for module in ("pyarrow", "fsspec", "boto3", "requests_kerberos", "hdfs"):
        try:
            mod = __import__(module)
            show(f"python {module}", getattr(mod, "__version__", "installed"))
        except Exception:  # noqa: BLE001
            show(f"python {module}", "not installed")


def cli(root, write):
    results = {}
    for tool in ("ozone", "hdfs"):
        if not shutil.which(tool):
            continue
        base = [tool, "fs"] if tool == "ozone" else [tool, "dfs"]
        print(f"\n[{tool} command line]")
        code, text, took = run(base + ["-ls", root])
        lines = [l for l in text.splitlines() if l.strip() and not l.startswith(("WARN", "INFO", "SLF4J"))]
        show("list root", f"{'OK' if code == 0 else 'FAILED'} in {took:.1f}s, {len(lines)} lines")
        if code != 0:
            print("   ", "\n    ".join(lines[-5:]))
            continue
        results[tool] = True
        if write:
            folder = f"{root.rstrip('/')}/_hive_probe"
            name = f"{folder}/probe-{tool}-{datetime.now():%Y%m%d%H%M%S}.txt"
            run(base + ["-mkdir", "-p", folder])
            code, text, took = run(base + ["-put", "-f", "-", name], data=b"hive ozone probe\n")
            show("write small file", f"{'OK' if code == 0 else 'FAILED: ' + text[-200:]} in {took:.1f}s")
            code, text, took = run(base + ["-cat", name])
            show("read it back", f"{'OK' if code == 0 and 'hive ozone probe' in text else 'FAILED'} in {took:.1f}s")
            big = name.replace(".txt", "-5mb.bin")
            code, text, took = run(base + ["-put", "-f", "-", big], data=os.urandom(5 * 1024 * 1024))
            show("write 5 MB", f"{'OK' if code == 0 else 'FAILED'} in {took:.1f}s")
            code, text, took = run(base + ["-rm", "-skipTrash", name, big])
            show("delete test files", f"{'OK' if code == 0 else 'FAILED: ' + text[-200:]} in {took:.1f}s")
    return results


def _prepare_libhdfs():
    """pyarrow needs the Hadoop jars on CLASSPATH and the native libhdfs library."""
    if not os.environ.get("CLASSPATH"):
        for tool in ("hdfs", "hadoop"):
            if shutil.which(tool):
                code, text, _ = run([tool, "classpath", "--glob"])
                if code == 0:
                    os.environ["CLASSPATH"] = text.splitlines()[-1]
                    show("CLASSPATH", f"from '{tool} classpath --glob' ({len(os.environ['CLASSPATH'])} chars)")
                    break
    if not os.environ.get("ARROW_LIBHDFS_DIR"):
        for folder in ("/usr/lib/hadoop/lib/native", "/usr/lib64", "/usr/lib/hadoop-hdfs/lib/native",
                       "/opt/cloudera/parcels/CDH/lib64", "/opt/ozone-addon/lib"):
            if os.path.isdir(folder) and any(n.startswith("libhdfs.so") for n in os.listdir(folder)):
                os.environ["ARROW_LIBHDFS_DIR"] = folder
                break
    show("ARROW_LIBHDFS_DIR", os.environ.get("ARROW_LIBHDFS_DIR") or "libhdfs.so not found")


def python_client(root, write):
    print("\n[python: pyarrow]")
    try:
        from pyarrow import fs
    except Exception as exc:  # noqa: BLE001
        show("pyarrow", f"not installed ({exc}); try: pip install pyarrow")
        return False
    _prepare_libhdfs()
    scheme, rest = root.split("://", 1)
    service, _, path = rest.partition("/")
    path = "/" + path
    try:
        started = time.perf_counter()
        filesystem = fs.HadoopFileSystem(f"{scheme}://{service}", 0)
        infos = filesystem.get_file_info(fs.FileSelector(path, recursive=False))
        show("list root", f"OK in {time.perf_counter() - started:.2f}s, {len(infos)} entries")
    except Exception as exc:  # noqa: BLE001
        show("list root", f"FAILED: {type(exc).__name__}: {str(exc)[:400]}")
        return False
    if write:
        folder = f"{path.rstrip('/')}/_hive_probe"
        try:
            filesystem.create_dir(folder)
            started = time.perf_counter()
            for n in range(20):
                with filesystem.open_output_stream(f"{folder}/small-{n}.txt") as out:
                    out.write(b"hive ozone probe\n")
            show("write 20 small files", f"OK in {time.perf_counter() - started:.2f}s")
            name = f"{folder}/probe-5mb.bin"
            started = time.perf_counter()
            with filesystem.open_output_stream(name) as out:
                out.write(os.urandom(5 * 1024 * 1024))
            show("write 5 MB", f"OK in {time.perf_counter() - started:.2f}s")
            started = time.perf_counter()
            with filesystem.open_input_file(name) as stream:
                stream.seek(1024)
                ok = len(stream.read(10)) == 10
            show("random read", f"{'OK' if ok else 'FAILED'} in {time.perf_counter() - started:.2f}s")
            started = time.perf_counter()
            filesystem.move(name, f"{folder}/renamed.bin")
            show("rename", f"OK in {time.perf_counter() - started:.2f}s")
            filesystem.delete_dir(folder)
            show("delete test folder", "OK")
        except Exception as exc:  # noqa: BLE001
            show("write test", f"FAILED: {type(exc).__name__}: {str(exc)[:400]}")
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    root, write = args[0], "--write-test" in sys.argv
    if "prd" in root.lower() and write:
        sys.exit("Refusing --write-test on a PRD path; use the UAT folder")
    print(f"Ozone root: {root}  (write test: {'yes' if write else 'no'})")
    environment()
    cli(root, write)
    python_client(root, write)
    print("\nDone. Paste this whole output back.")


if __name__ == "__main__":
    main()
