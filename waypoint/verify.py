import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import NamedTuple

from . import tls

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "artifacts", "verify")
IMAGES = os.path.join(ROOT, "docs", "src", "assets", "screenshots")
FROZEN_NOW = "2026-06-15 12:00:00"
FROZEN_NOW_ISO = "2026-06-15T12:00:00Z"
FAKETIME_LIBRARIES = (
    "/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1",
    "/usr/lib/aarch64-linux-gnu/faketime/libfaketime.so.1",
    "/usr/lib/faketime/libfaketime.so.1",
    "/usr/local/lib/faketime/libfaketime.so.1",
)
FAKETIME_INSTALL = "sudo apt-get install libfaketime"


MAX_JOBS = 4
JOBS_ENV = "VERIFY_JOBS"
DEMO_KEY = "demo-key-not-real"
NO_OUTSIDE = "http://127.0.0.1:9"


class Instance(NamedTuple):
    data: str
    url: str
    server: subprocess.Popen[bytes]
    log: str


def clean_env(data: str, base: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if not k.startswith(("OIDC_", "WAYPOINT_SECRET_KEY"))
           and k not in ("DATABASE_URL", "WAYPOINT_PUBLIC_URL", "WAYPOINT_ALLOW_NO_AUTH")}
    env.update(WAYPOINT_DATA=data, PYTHONUNBUFFERED="1", RAPIDAPI_KEY=DEMO_KEY, HTTPS_PROXY=NO_OUTSIDE, https_proxy=NO_OUTSIDE)
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(name, None)
    return env


def find_faketime(candidates: tuple[str, ...] = FAKETIME_LIBRARIES) -> str | None:
    return next((c for c in candidates if os.path.isfile(c)), None)


def frozen_env(env: dict[str, str], library: str) -> dict[str, str]:
    return {**env, "LD_PRELOAD": library, "FAKETIME": FROZEN_NOW, "FAKETIME_DONT_FAKE_MONOTONIC": "1", "TZ": "UTC"}


def missing_faketime_message() -> str:
    return (f"verify: libfaketime isn't installed, and verify needs it to freeze the clock so a screenshot changes only when the UI or its data does. "
            f"Install it with: {FAKETIME_INSTALL} (Debian and Ubuntu; verify runs on Linux, as macOS doesn't support LD_PRELOAD)")


def server_command(port: int) -> list[str]:
    return [sys.executable, os.path.join(ROOT, "run.py"), "--host", "127.0.0.1", "--port", str(port)]


def default_jobs(cpus: int | None = None) -> int:
    return max(1, min(MAX_JOBS, (os.cpu_count() or 1) if cpus is None else cpus))


def resolve_jobs(flag: int | None, env: Mapping[str, str] | None = None, cpus: int | None = None) -> int:
    given = os.environ if env is None else env
    if flag is None and not given.get(JOBS_ENV, "").strip():
        return default_jobs(cpus)
    text = str(flag) if flag is not None else given[JOBS_ENV].strip()
    try:
        jobs = int(text)
    except ValueError:
        jobs = 0
    if jobs < 1:
        raise ValueError(f"{'--jobs' if flag is not None else JOBS_ENV} must be a whole number of 1 or more, not {text!r}")
    return jobs


def node_command(node: str, frontend: str, urls: list[str], pages: list[str], flows: list[str]) -> list[str]:
    command = [node, os.path.join(frontend, "verify", "verify.mjs")]
    for url in urls:
        command += ["--url", url]
    for flow in flows:
        command += ["--flow", flow]
    return [*command, "--out", OUT, "--images", IMAGES, "--now", FROZEN_NOW_ISO, *pages]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, server: subprocess.Popen, timeout: float = 60) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if server.poll() is not None:
            raise RuntimeError(f"the server exited with code {server.returncode} before it was ready")
        try:
            with tls.urlopen(url, 2, allow_http=True, handlers=(urllib.request.ProxyHandler({}),)):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    raise RuntimeError(f"the server wasn't answering at {url} after {timeout:.0f} seconds")


def log_tail(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()[-2000:]
    except OSError:
        return ""


def stop_instances(instances: list[Instance]) -> None:
    for instance in instances:
        instance.server.terminate()
    for instance in instances:
        try:
            instance.server.wait(10)
        except subprocess.TimeoutExpired:
            instance.server.kill()


def start_instances(root: str, jobs: int, library: str) -> list[Instance]:
    folders = [os.path.join(root, f"instance-{i + 1}") for i in range(jobs)]
    os.mkdir(folders[0])
    seeded = subprocess.run([sys.executable, os.path.join(ROOT, "run.py"), "demo"], env=frozen_env(clean_env(folders[0]), library), cwd=ROOT,
                            capture_output=True, text=True)
    if seeded.returncode:
        raise RuntimeError(f"couldn't fill the demo database:\n{seeded.stdout}{seeded.stderr}")
    for folder in folders[1:]:
        shutil.copytree(folders[0], folder)
    started: list[Instance] = []
    try:
        for folder in folders:
            port = free_port()
            log = os.path.join(folder, "server.log")
            with open(log, "w") as out:
                server = subprocess.Popen(server_command(port), env=frozen_env(clean_env(folder), library), cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
            started.append(Instance(folder, f"http://127.0.0.1:{port}", server, log))
        for instance in started:
            try:
                wait_ready(instance.url, instance.server)
            except RuntimeError as e:
                raise RuntimeError(f"{e}\n{log_tail(instance.log)}") from e
    except BaseException:
        stop_instances(started)
        raise
    return started


def run(pages: list[str], jobs: int | None = None, flows: list[str] | None = None) -> int:
    frontend = os.path.join(ROOT, "frontend")
    if not os.path.isdir(os.path.join(frontend, "node_modules", "@playwright")):
        print("verify: the web app's packages aren't installed. Run: cd frontend && npm ci", file=sys.stderr)
        return 2
    if not os.path.isfile(os.path.join(ROOT, "waypoint", "static", "app", "index.html")):
        print("verify: the web app isn't built. Run: cd frontend && npm run build (make verify does it)", file=sys.stderr)
        return 2
    node = shutil.which("node")
    if not node:
        print("verify: Node isn't installed (the web app needs it too).", file=sys.stderr)
        return 2
    library = find_faketime()
    if not library:
        print(missing_faketime_message(), file=sys.stderr)
        return 2
    try:
        count = resolve_jobs(jobs)
    except ValueError as e:
        print(f"verify: {e}", file=sys.stderr)
        return 2
    root = tempfile.mkdtemp(prefix="waypoint-verify-")
    instances: list[Instance] = []
    try:
        try:
            instances = start_instances(root, count, library)
        except RuntimeError as e:
            print(f"verify: {e}", file=sys.stderr)
            return 2
        urls = [i.url for i in instances]
        print(f"verify: demo data served at {', '.join(urls)}" + (f" ({count} servers, each with its own copy of the data)" if count > 1 else ""))
        code = subprocess.run(node_command(node, frontend, urls, pages, flows or []), cwd=frontend, env=clean_env(instances[0].data)).returncode
        for instance in instances:
            if instance.server.poll() is not None:
                print(f"verify: the server at {instance.url} exited with code {instance.server.returncode}\n{log_tail(instance.log)}", file=sys.stderr)
                code = code or 1
        return code
    finally:
        stop_instances(instances)
        shutil.rmtree(root, ignore_errors=True)
