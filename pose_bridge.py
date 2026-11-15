"""Publish the local RE2 pose and export the other player's verified pose."""

import argparse
from contextlib import contextmanager
import errno
from functools import partial
import os
from pathlib import Path
from queue import Queue
import sys
from threading import Event, Lock, Thread

from guest_pose import PoseFile, run_guest, validate_player_id
from observer import run_observer
from protocol.v1 import VERSION


@contextmanager
def lock_data_directory(data):
    # Keep the file in place so that all invocations lock the same file.
    with (data / "re2_coop_pose_bridge.lock").open("a+b") as lock:
        try:
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            raise ValueError("a pose bridge is already running for this data directory") from exc
        yield


def run_bridge(data, port, local_id, remote_id, reconnect_attempts):
    stop = Event()
    finished = Queue()
    output = PoseFile(data / "re2_coop_guest_pose.json", remote_id)
    session_lock = Lock()
    session_id = None

    def set_session(value):
        nonlocal session_id
        with session_lock:
            session_id = value

    def active_session():
        with session_lock:
            return session_id

    def run_leg(name, action):
        try:
            action()
        except Exception as exc:
            finished.put((name, exc))
        else:
            finished.put((name, None))
        finally:
            stop.set()

    legs = (
        ("guest", partial(run_guest, output, port, reconnect_attempts=reconnect_attempts,
                          host_heartbeat=True, stop=stop, on_connection=set_session)),
        ("observer", partial(run_observer, data / "re2_coop_observer.json", port, local_id,
                             protocol_version=VERSION, stop=stop, active_session=active_session,
                             reconnect_attempts=reconnect_attempts)),
    )
    workers = []
    try:
        for name, action in legs:
            worker = Thread(target=run_leg, args=(name, action), name=name)
            worker.start()
            workers.append(worker)
        # A timed wait keeps Ctrl+C interruptible on Windows.
        while not stop.wait(0.1):
            pass
    finally:
        stop.set()
        for worker in workers:
            # An in-flight handshake or reply uses the existing socket timeouts.
            while worker.is_alive():
                worker.join(0.1)

    while not finished.empty():
        name, error = finished.get_nowait()
        if error is not None:
            raise RuntimeError(f"{name}: {error}") from error
    raise RuntimeError("host connection closed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="existing REFramework data directory")
    parser.add_argument("--port", type=int, required=True, help="local v1 host or forwarded port")
    parser.add_argument("--local-player-id", required=True)
    parser.add_argument("--remote-player-id", required=True)
    parser.add_argument("--reconnect-attempts", type=int, default=3)
    args = parser.parse_args()
    if args.local_player_id == args.remote_player_id:
        parser.error("local and remote player IDs must be different")
    if not 1 <= args.port <= 65535 or args.reconnect_attempts < 0:
        parser.error("port must be 1–65535 and reconnect attempts must be nonnegative")
    if not args.data.is_dir():
        parser.error("--data must be an existing directory")
    try:
        validate_player_id(args.local_player_id)
        validate_player_id(args.remote_player_id)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        with lock_data_directory(args.data):
            run_bridge(args.data, args.port, args.local_player_id, args.remote_player_id,
                       args.reconnect_attempts)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Pose bridge stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
