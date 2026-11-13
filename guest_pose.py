"""Export one remote player's verified pose to a local REFramework diagnostic."""

import argparse
from contextlib import closing
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

from wire import follow_replica


HEARTBEAT_SECONDS = 1
REPLACE_ATTEMPTS = 5
REPLACE_RETRY_SECONDS = 0.02
FLOAT32_MAX = 3.4028234663852886e38
MAX_PLAYER_ID_BYTES = 128


def _vector(value, size):
    if (not isinstance(value, list) or len(value) != size
            or any(type(component) not in (float, int) or not -FLOAT32_MAX <= component <= FLOAT32_MAX
                   for component in value)):
        return None
    return value


def _pose(value):
    if not isinstance(value, dict):
        return None
    position = _vector(value.get("position"), 3)
    rotation = _vector(value.get("rotation"), 4)
    if position is None or rotation is None:
        return None
    length = math.hypot(*rotation)
    if length == 0:
        return None
    return {"position": position, "rotation": [component / length for component in rotation]}


class PoseFile:
    """Maintain a lease on an atomic, local view of one player in the guest state."""

    def __init__(self, path, player_id):
        if (not player_id or len(player_id.encode("utf-8")) > MAX_PLAYER_ID_BYTES
                or any(not character.isprintable() for character in player_id)):
            raise ValueError("player ID must be printable and fit in 128 UTF-8 bytes")
        self.path = Path(path)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.state = {"schema": 1, "player_id": player_id, "connected": False,
                      "session_id": None, "sequence": None, "pose": None}
        self.heartbeat = threading.Thread(target=self._heartbeat)

    def __enter__(self):
        self._write()
        self.heartbeat.start()
        return self

    def __exit__(self, exc_type, *_):
        self.stop.set()
        self.heartbeat.join()
        try:
            self.disconnect()
        except OSError as exc:
            if exc_type is None:
                raise
            print(f"Could not clear guest pose file: {exc}", file=sys.stderr)

    def update(self, replica):
        pose = _pose(replica.state["players"].get(self.state["player_id"]))
        with self.lock:
            self.state.update(connected=True, session_id=replica.session_id,
                              sequence=replica.sequence, pose=pose)
            self._write()

    def disconnect(self):
        with self.lock:
            self.state.update(connected=False, pose=None)
            self._write()

    def _heartbeat(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            with self.lock:
                if self.state["connected"]:
                    try:
                        self._write()
                    except OSError:
                        # A failed heartbeat never extends the published lease.
                        continue

    def _write(self):
        data = {**self.state, "written_at": int(time.time())}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.path.parent, prefix=self.path.name + ".",
                                             suffix=".tmp", encoding="utf-8", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            for attempt in range(REPLACE_ATTEMPTS):
                try:
                    os.replace(temporary, self.path)
                    break
                except PermissionError:
                    # On Windows a reader may briefly hold the file without delete sharing.
                    if attempt + 1 == REPLACE_ATTEMPTS:
                        raise
                    time.sleep(REPLACE_RETRY_SECONDS)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="path to reframework/data/re2_coop_guest_pose.json")
    parser.add_argument("--remote-player-id", required=True,
                        help="player ID published by the other instance's observer")
    parser.add_argument("--reconnect-attempts", type=int, default=3,
                        help="total reconnect attempts after the first connection (default: 3)")
    parser.add_argument("--host-heartbeat", action="store_true",
                        help="require application heartbeat replies from a compatible v1 host")
    args = parser.parse_args()
    if args.reconnect_attempts < 0:
        parser.error("--reconnect-attempts must be nonnegative")
    try:
        output = PoseFile(args.output, args.remote_player_id)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output, closing(follow_replica(args.port, reconnect_attempts=args.reconnect_attempts,
                                           host_heartbeat=args.host_heartbeat)) as updates:
            ready = False
            for replica in updates:
                if replica is None:
                    output.disconnect()
                    ready = False
                else:
                    output.update(replica)
                    if not ready:
                        print("READY", flush=True)
                        ready = True
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
