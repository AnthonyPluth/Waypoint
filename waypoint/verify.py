import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from . import tls

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "artifacts", "verify")


DEMO_KEY = "demo-key-not-real"
NO_OUTSIDE = "http://127.0.0.1:9"


def clean_env(data: str, base: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if not k.startswith(("OIDC_", "WAYPOINT_SECRET_KEY"))
           and k not in ("DATABASE_URL", "WAYPOINT_PUBLIC_URL", "WAYPOINT_ALLOW_NO_AUTH")}
    env.update(WAYPOINT_DATA=data, PYTHONUNBUFFERED="1", RAPIDAPI_KEY=DEMO_KEY, HTTPS_PROXY=NO_OUTSIDE, https_proxy=NO_OUTSIDE)
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(name, None)
    return env


def server_command(port: int) -> list[str]:
    return [sys.executable, os.path.join(ROOT, "run.py"), "--host", "127.0.0.1", "--port", str(port)]


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


def run(pages: list[str]) -> int:
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
    data = tempfile.mkdtemp(prefix="waypoint-verify-")
    env = clean_env(data)
    server = None
    try:
        seeded = subprocess.run([sys.executable, os.path.join(ROOT, "run.py"), "demo"], env=env, cwd=ROOT,
                                capture_output=True, text=True)
        if seeded.returncode:
            print(f"verify: couldn't fill the demo database:\n{seeded.stdout}{seeded.stderr}", file=sys.stderr)
            return 2
        port = free_port()
        log_path = os.path.join(data, "server.log")
        with open(log_path, "w") as log:
            server = subprocess.Popen(server_command(port),
                                      env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            url = f"http://127.0.0.1:{port}"
            try:
                wait_ready(url, server)
            except RuntimeError as e:
                log.flush()
                with open(log_path) as f:
                    print(f"verify: {e}\n{f.read()[-2000:]}", file=sys.stderr)
                return 2
            print(f"verify: demo data served at {url}")
            return subprocess.run([node, os.path.join(frontend, "verify", "verify.mjs"), "--url", url, "--out", OUT, *pages],
                                  cwd=frontend, env=env).returncode
    finally:
        if server:
            server.terminate()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()
        shutil.rmtree(data, ignore_errors=True)
