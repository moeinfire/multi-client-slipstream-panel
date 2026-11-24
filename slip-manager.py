#!/usr/bin/env python3
"""Supervise one or more standalone Slipstream client listeners."""

import os
import signal
import subprocess
import sys
import threading
import time
import queue
from datetime import datetime

BIN = os.environ.get("SLIPSTREAM_BIN", "/usr/local/bin/slipstream-client")
RESOLVER = os.environ.get("SLIPSTREAM_RESOLVER", "8.8.8.8:53")
RETRY_SECONDS = int(os.environ.get("SLIPSTREAM_RETRY_SECONDS", "300"))
ERROR_GRACE_SECONDS = int(os.environ.get("SLIPSTREAM_ERROR_GRACE_SECONDS", "30"))
LOGDIR = os.environ.get("SLIPSTREAM_LOGDIR", "/var/log/slipstream")
TARGETS_RAW = os.environ.get("SLIPSTREAM_TARGETS", "r.iooq.ir:20817")

TARGETS = []
for item in TARGETS_RAW.split(","):
    item = item.strip()
    if not item:
        continue
    try:
        domain, port = item.rsplit(":", 1)
        port = int(port)
        if not domain or not 1 <= port <= 65535:
            raise ValueError
        TARGETS.append((domain, port))
    except ValueError:
        raise SystemExit(f"Invalid SLIPSTREAM_TARGETS entry: {item!r}; expected domain:port")

os.makedirs(LOGDIR, exist_ok=True)
stop_event = threading.Event()
children = {}
children_lock = threading.Lock()


def log(message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def terminate_process(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def manage_target(domain, port):
    key = f"{domain}:{port}"
    logfile = os.path.join(LOGDIR, f"{port}.log")

    while not stop_event.is_set():
        log(f"[{key}] Starting Slipstream")
        try:
            proc = subprocess.Popen(
                [
                    BIN,
                    "--resolver", RESOLVER,
                    "--domain", domain,
                    "--tcp-listen-port", str(port),
                    "--congestion-control", "bbr",
                    "--keep-alive-interval", "1000",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            log(f"[{key}] Start failed: {exc}")
            if stop_event.wait(RETRY_SECONDS):
                break
            continue

        with children_lock:
            children[key] = proc

        lines = queue.Queue()

        def reader():
            try:
                for line in proc.stdout:
                    lines.put(("line", line.rstrip("\n")))
            finally:
                lines.put(("eof", ""))

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()
        suspect_since = None
        reason = "process exited"
        restart_needed = False

        try:
            with open(logfile, "a", buffering=1) as log_file:
                while not stop_event.is_set():
                    try:
                        kind, line = lines.get(timeout=1)
                    except queue.Empty:
                        kind, line = None, ""

                    if kind == "line":
                        log_file.write(line + "\n")
                        log(f"[{key}] {line}")
                        lower = line.lower()

                        if "connection ready" in lower:
                            suspect_since = None
                            continue
                        if "address already in use" in lower:
                            reason = "local port is already in use"
                            restart_needed = True
                            break
                        if "connection closed" in lower or "client error" in lower:
                            if suspect_since is None:
                                suspect_since = time.monotonic()
                                reason = "connection error; waiting for recovery"
                    elif kind == "eof":
                        reason = "Slipstream process exited"
                        restart_needed = True
                        break

                    if proc.poll() is not None:
                        reason = f"process exited with code {proc.returncode}"
                        restart_needed = True
                        break
                    if (
                        suspect_since is not None
                        and time.monotonic() - suspect_since >= ERROR_GRACE_SECONDS
                    ):
                        reason = f"no recovery confirmation within {ERROR_GRACE_SECONDS} seconds"
                        restart_needed = True
                        break
        finally:
            terminate_process(proc)
            reader_thread.join(timeout=2)
            with children_lock:
                if children.get(key) is proc:
                    children.pop(key, None)

        if stop_event.is_set():
            break
        log(f"[{key}] {reason}; restarting in {RETRY_SECONDS} seconds")
        if stop_event.wait(RETRY_SECONDS):
            break


def shutdown(signum, frame):
    if stop_event.is_set():
        return
    log("Stopping manager and managed Slipstream processes...")
    stop_event.set()
    with children_lock:
        active = list(children.values())
    for proc in active:
        terminate_process(proc)


def main():
    if not os.path.isfile(BIN) or not os.access(BIN, os.X_OK):
        log(f"ERROR: {BIN} not found or not executable.")
        return 1
    if not TARGETS:
        log("ERROR: no valid Slipstream targets configured.")
        return 1

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    threads = []
    for domain, port in TARGETS:
        thread = threading.Thread(target=manage_target, args=(domain, port), daemon=True)
        thread.start()
        threads.append(thread)

    log("Manager started.")
    try:
        while not stop_event.wait(1):
            pass
    finally:
        shutdown(None, None)
        for thread in threads:
            thread.join(timeout=8)
        log("Manager stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
