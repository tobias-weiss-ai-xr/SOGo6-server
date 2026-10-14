#!/usr/bin/env python3
"""Prove the SSE/gunicorn fix: a sleeping SSE generator must NOT get its worker killed.

Runs gunicorn twice against a minimal WSGI app that mimics app/api/v1/user/ApiLiveUpdates.py
(time.sleep in the response iterator): once with the old sync workers, once with gthread.
With a short --timeout, sync gets the worker killed (stream dies, WORKER TIMEOUT in log);
gthread keeps the worker alive and the stream open.

Usage: python3 tests/test_api/test_sse_worker_survives.py
Exit 0 = gthread survives past the timeout window (fix works).
"""
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = '''\
import time
def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/event-stream"),
                              ("Cache-Control", "no-cache")])
    def gen():
        yield b"event: connected\\n\\n"
        while True:
            time.sleep(2)
            yield b"data: heartbeat\\n\\n"
    return gen()
'''

TIMEOUT_S = 4          # gunicorn worker timeout, shorter than the poll gap
OBSERVE_S = 10         # observe the stream well past 2x the timeout window


def run(worker_class: str, port: int) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "sseapp.py").write_text(APP)
        proc = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "--bind", f"127.0.0.1:{port}",
             "--workers", "1", "--timeout", str(TIMEOUT_S),
             "--worker-class", worker_class, "sseapp:app"],
            cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            time.sleep(1.5)
            sock = socket.create_connection(("127.0.0.1", port), timeout=3)
            sock.sendall(b"GET /api/sse HTTP/1.1\r\nHost: x\r\n\r\n")
            sock.settimeout(1.0)
            buf = b""
            deadline = time.time() + OBSERVE_S
            while time.time() < deadline:
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue  # keep observing until the deadline
                if not chunk:
                    break  # stream closed (worker killed / connection dropped)
                buf += chunk
            observed_for = OBSERVE_S
            beats = buf.count(b"data: heartbeat")
            sock.close()
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
            worker_killed = "WORKER TIMEOUT" in out
            log = f"[{worker_class}] heartbeats_in_{observed_for}s={beats} worker_killed={worker_killed}"
            # healthy: stream kept yielding heartbeats well past the timeout window
            return beats >= 3 and not worker_killed, log
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


def main() -> int:
    ok_sync, log_sync = run("sync", 5098)
    print(log_sync, " (old behavior — documented, not asserted)")
    ok_gthread, log_gthread = run("gthread", 5099)
    print(log_gthread)
    print("PASS" if ok_gthread else "FAIL: gthread did not survive the timeout window")
    return 0 if ok_gthread else 1


if __name__ == "__main__":
    sys.exit(main())
