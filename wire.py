"""Local loopback transport demonstration, not the planned Steam transport."""

import argparse
import json
import socket
import socketserver
import threading
import time

from protocol import v1
from sync_model import Host, Replica, ResyncRequired, state_digest


PROTOCOL_VERSIONS = (0, v1.VERSION)
HANDSHAKE_TIMEOUT = 5
CLIENT_REPLY_TIMEOUT = 5
RECONNECT_DELAY = 0.25
KEEPALIVE_IDLE = 10
KEEPALIVE_INTERVAL = 3
KEEPALIVE_PROBES = 3
MAX_FRAME_BYTES = 1024 * 1024


def _check_protocol_version(version):
    if type(version) is not int or version not in PROTOCOL_VERSIONS:
        raise ValueError("unsupported loopback protocol version")


def _encode_frame(message, protocol_version):
    if protocol_version:
        payload = v1.encode({**message, "version": protocol_version})
        if len(payload) + 1 > MAX_FRAME_BYTES:
            raise v1.ProtocolError("v1 frame exceeds the byte limit")
    else:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return payload + b"\n"


def send(stream, message, *, protocol_version=0):
    stream.write(_encode_frame(message, protocol_version))
    stream.flush()


def receive(stream, *, protocol_version=0):
    line = stream.readline(MAX_FRAME_BYTES + 1 if protocol_version else MAX_FRAME_BYTES)
    if not line:
        raise EOFError("connection closed")
    if protocol_version:
        if len(line) > MAX_FRAME_BYTES:
            raise v1.ProtocolError("v1 frame exceeds the byte limit")
        if not line.endswith(b"\n"):
            raise ConnectionError("connection closed in the middle of a v1 frame")
        return v1.decode(line[:-1])
    return json.loads(line)


def _require_hello(stream, protocol_version):
    if receive(stream, protocol_version=protocol_version)["type"] != "hello":
        raise v1.ProtocolError("expected protocol hello before snapshot")


def _validate_v1_transition(event, snapshot):
    _encode_frame({"type": "event", "data": event}, v1.VERSION)
    _encode_frame({"type": "snapshot", "data": snapshot}, v1.VERSION)


class Handler(socketserver.StreamRequestHandler):
    def _exchange_hello(self, protocol_version):
        timeout = self.connection.gettimeout()
        self.connection.settimeout(HANDSHAKE_TIMEOUT)
        try:
            send(self.wfile, {"type": "hello"}, protocol_version=protocol_version)
            _require_hello(self.rfile, protocol_version)
        finally:
            self.connection.settimeout(timeout)

    def handle(self):
        host = self.server.host_state
        protocol_version = self.server.protocol_version
        validate = _validate_v1_transition if protocol_version else None
        if protocol_version:
            try:
                self._exchange_hello(protocol_version)
            except (EOFError, OSError, v1.ProtocolError):
                return

        try:
            with self.server.state_lock:
                send(self.wfile, {"type": "snapshot", "data": host.snapshot()},
                     protocol_version=protocol_version)
                self.server.clients.add(self.wfile)
            while True:
                message = receive(self.rfile, protocol_version=protocol_version)
                if message.get("type") != "propose":
                    if protocol_version:
                        return
                    send(self.wfile, {"type": "error", "message": "unknown request"})
                    continue
                with self.server.state_lock:
                    try:
                        event = host.emit(message["kind"], message.get("target"), message.get("value"),
                                          validate=validate)
                    except (KeyError, ValueError, TypeError) as exc:
                        error = {"type": "error", "message": str(exc)}
                        if not protocol_version:
                            send(self.wfile, error)
                            continue
                        self.server.clients.discard(self.wfile)
                    else:
                        for stream in tuple(self.server.clients):
                            try:
                                send(stream, {"type": "event", "data": event},
                                     protocol_version=protocol_version)
                            except OSError:
                                self.server.clients.discard(stream)
                        continue
                send(self.wfile, error, protocol_version=protocol_version)
                return
        except (EOFError, OSError, v1.ProtocolError):
            return
        finally:
            with self.server.state_lock:
                self.server.clients.discard(self.wfile)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, *, protocol_version=0):
        _check_protocol_version(protocol_version)
        super().__init__(address, Handler)
        self.protocol_version = protocol_version
        self.host_state = Host()
        self.state_lock = threading.RLock()
        self.clients = set()


def join_replica(stream, *, protocol_version=0, replica=None):
    """Join the configured loopback protocol and verify the initial state."""
    _check_protocol_version(protocol_version)
    if protocol_version:
        _require_hello(stream, protocol_version)
        send(stream, {"type": "hello"}, protocol_version=protocol_version)
    greeting = receive(stream, protocol_version=protocol_version)
    if greeting["type"] != "snapshot":
        raise ValueError("expected snapshot")
    snapshot = greeting["data"]
    if replica is None:
        replica = Replica()
    elif (replica.session_id is not None and snapshot["session_id"] == replica.session_id
          and snapshot["sequence"] == replica.sequence
          and snapshot["digest"] != state_digest(replica.state)):
        raise ValueError("divergent snapshot at the last accepted sequence")
    replica.restore(snapshot)
    return replica


def _receive_event(stream, protocol_version):
    response = receive(stream, protocol_version=protocol_version)
    if response["type"] != "event":
        raise ValueError(response.get("message", "event rejected"))
    return response["data"]


def _enable_tcp_keepalive(connection):
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    idle_option = getattr(socket, "TCP_KEEPIDLE", getattr(socket, "TCP_KEEPALIVE", None))
    for option, value in ((idle_option, KEEPALIVE_IDLE),
                          (getattr(socket, "TCP_KEEPINTVL", None), KEEPALIVE_INTERVAL),
                          (getattr(socket, "TCP_KEEPCNT", None), KEEPALIVE_PROBES)):
        if option is not None:
            connection.setsockopt(socket.IPPROTO_TCP, option, value)


def follow_replica(port, *, reconnect_attempts):
    """Yield verified v1 state and None when a joined connection is lost."""
    if type(reconnect_attempts) is not int or reconnect_attempts < 0:
        raise ValueError("reconnect_attempts must be a nonnegative integer")

    replica = Replica()
    for attempt in range(reconnect_attempts + 1):
        joined = False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=CLIENT_REPLY_TIMEOUT) as connection:
                with connection.makefile("rwb") as stream:
                    join_replica(stream, protocol_version=v1.VERSION, replica=replica)
                    _enable_tcp_keepalive(connection)
                    joined = True
                    connection.settimeout(None)
                    yield replica
                    while True:
                        if replica.apply(_receive_event(stream, v1.VERSION)):
                            yield replica
        except (EOFError, ConnectionError, TimeoutError, ResyncRequired) as exc:
            if joined:
                yield None
            if attempt == reconnect_attempts:
                if isinstance(exc, EOFError) and joined:
                    return
                raise
            time.sleep(RECONNECT_DELAY)


def client(port, proposal=None, listen=False, event_count=1, *, protocol_version=0, on_state=None):
    _check_protocol_version(protocol_version)
    if event_count < 0:
        raise ValueError("event_count must be nonnegative")
    continuous = event_count == 0
    with socket.create_connection(("127.0.0.1", port), timeout=CLIENT_REPLY_TIMEOUT) as connection:
        with connection.makefile("rwb") as stream:
            replica = join_replica(stream, protocol_version=protocol_version)
            if on_state is not None:
                on_state(replica)
            if listen:
                print("READY", flush=True)
            if proposal is not None:
                message = {"type": "propose", **proposal}
                if protocol_version:
                    message.setdefault("target", None)
                    message.setdefault("value", None)
                send(stream, message, protocol_version=protocol_version)
            if proposal is not None or listen:
                if continuous:
                    connection.settimeout(None)
                received = 0
                while continuous or received < event_count:
                    try:
                        event = _receive_event(stream, protocol_version)
                    except EOFError:
                        if not continuous:
                            raise
                        break
                    if replica.apply(event) and on_state is not None:
                        on_state(replica)
                    received += 1
    return replica.snapshot()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host", "client"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--propose", help="JSON event proposal, client mode only")
    parser.add_argument("--listen", action="store_true", help="wait for broadcast events")
    parser.add_argument("--events", type=int, default=1,
                        help="number of broadcast events to receive; 0 listens continuously")
    parser.add_argument("--protocol-version", type=int, choices=PROTOCOL_VERSIONS, default=0,
                        help="loopback protocol version; 0 uses the unversioned format")
    args = parser.parse_args()
    if args.mode == "host":
        with Server(("127.0.0.1", args.port), protocol_version=args.protocol_version) as server:
            print(server.server_address[1], flush=True)
            server.serve_forever()
    else:
        print(json.dumps(client(args.port, json.loads(args.propose) if args.propose else None,
                                args.listen, args.events, protocol_version=args.protocol_version)))


if __name__ == "__main__":
    main()

