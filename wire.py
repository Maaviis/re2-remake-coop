"""Local loopback transport demonstration, not the planned Steam transport."""

import argparse
from contextlib import nullcontext
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
HOST_HEARTBEAT_INTERVAL = 1
HOST_HEARTBEAT_TIMEOUT = 5
PONG_WRITE_TIMEOUT = 1
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
    greeting = receive(stream, protocol_version=protocol_version)
    if greeting["type"] != "hello":
        raise v1.ProtocolError("expected protocol hello before snapshot")
    return greeting


def _validate_v1_transition(event, snapshot):
    _encode_frame({"type": "event", "data": event}, v1.VERSION)
    _encode_frame({"type": "snapshot", "data": snapshot}, v1.VERSION)


class Handler(socketserver.StreamRequestHandler):
    def setup(self):
        super().setup()
        self.write_lock = threading.Lock()

    def _send_event(self, event, protocol_version):
        with self.write_lock:
            send(self.wfile, {"type": "event", "data": event}, protocol_version=protocol_version)

    def _send_pong(self, nonce, protocol_version):
        with self.write_lock:
            timeout = self.connection.gettimeout()
            self.connection.settimeout(PONG_WRITE_TIMEOUT)
            try:
                send(self.wfile, {"type": "pong", "nonce": nonce}, protocol_version=protocol_version)
            except OSError:
                # A partial pong must not be followed by another frame.
                self.connection.shutdown(socket.SHUT_RDWR)
                raise
            finally:
                self.connection.settimeout(timeout)

    def _exchange_hello(self, protocol_version):
        timeout = self.connection.gettimeout()
        self.connection.settimeout(HANDSHAKE_TIMEOUT)
        try:
            send(self.wfile, {"type": "hello"}, protocol_version=protocol_version)
            return _require_hello(self.rfile, protocol_version).get("heartbeat", False)
        finally:
            self.connection.settimeout(timeout)

    def handle(self):
        host = self.server.host_state
        protocol_version = self.server.protocol_version
        validate = _validate_v1_transition if protocol_version else None
        heartbeat = False
        if protocol_version:
            try:
                heartbeat = self._exchange_hello(protocol_version)
            except (EOFError, OSError, v1.ProtocolError):
                return

        try:
            with self.server.state_lock:
                send(self.wfile, {"type": "snapshot", "data": host.snapshot()},
                     protocol_version=protocol_version)
                self.server.clients.add(self)
            while True:
                message = receive(self.rfile, protocol_version=protocol_version)
                if heartbeat and message["type"] == "ping":
                    self._send_pong(message["nonce"], protocol_version)
                    continue
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
                        self.server.clients.discard(self)
                    else:
                        for peer in tuple(self.server.clients):
                            try:
                                peer._send_event(event, protocol_version)
                            except OSError:
                                self.server.clients.discard(peer)
                        continue
                send(self.wfile, error, protocol_version=protocol_version)
                return
        except (EOFError, OSError, v1.ProtocolError):
            return
        finally:
            with self.server.state_lock:
                self.server.clients.discard(self)


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


def join_replica(stream, *, protocol_version=0, replica=None, host_heartbeat=False):
    """Join the configured loopback protocol and verify the initial state."""
    _check_protocol_version(protocol_version)
    if protocol_version:
        _require_hello(stream, protocol_version)
        hello = {"type": "hello"}
        if host_heartbeat:
            hello["heartbeat"] = True
        send(stream, hello, protocol_version=protocol_version)
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


class _TimedFrames:
    """Read complete frames across scheduling timeouts without losing buffered bytes."""

    def __init__(self, connection):
        self.connection = connection
        self.buffer = bytearray()
        self.deadline = None

    def readline(self, limit):
        deadline = self.deadline if self.deadline is not None else time.monotonic() + CLIENT_REPLY_TIMEOUT
        while True:
            end = self.buffer.find(b"\n", 0, limit)
            if end != -1 or len(self.buffer) >= limit:
                length = limit if end == -1 else end + 1
                line = bytes(self.buffer[:length])
                del self.buffer[:length]
                return line
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("v1 frame read deadline")
            self.connection.settimeout(remaining)
            chunk = self.connection.recv(min(65536, limit - len(self.buffer)))
            if not chunk:
                line = bytes(self.buffer)
                self.buffer.clear()
                return line
            self.buffer.extend(chunk)

    def write(self, data):
        self.connection.settimeout(CLIENT_REPLY_TIMEOUT)
        self.connection.sendall(data)

    def flush(self):
        pass


def _heartbeat_events(stream):
    nonce = 0
    pending = False
    deadline = time.monotonic()
    while True:
        if time.monotonic() >= deadline:
            if pending:
                raise TimeoutError("v1 host heartbeat timed out")
            nonce += 1
            send(stream, {"type": "ping", "nonce": nonce}, protocol_version=v1.VERSION)
            pending = True
            deadline = time.monotonic() + HOST_HEARTBEAT_TIMEOUT
        stream.deadline = deadline
        try:
            message = receive(stream, protocol_version=v1.VERSION)
        except TimeoutError:
            continue
        if message["type"] == "pong":
            if not pending or message["nonce"] != nonce:
                raise v1.ProtocolError("unexpected v1 heartbeat reply")
            if time.monotonic() >= deadline:
                raise TimeoutError("v1 host heartbeat timed out")
            pending = False
            deadline = time.monotonic() + HOST_HEARTBEAT_INTERVAL
        elif message["type"] == "event":
            yield message["data"]
        else:
            raise ValueError(message.get("message", "event rejected"))


def follow_replica(port, *, reconnect_attempts, host_heartbeat=False):
    """Yield verified v1 state and None when a joined connection is lost."""
    if type(reconnect_attempts) is not int or reconnect_attempts < 0:
        raise ValueError("reconnect_attempts must be a nonnegative integer")

    replica = Replica()
    for attempt in range(reconnect_attempts + 1):
        joined = False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=CLIENT_REPLY_TIMEOUT) as connection:
                stream_context = (nullcontext(_TimedFrames(connection)) if host_heartbeat
                                  else connection.makefile("rwb"))
                with stream_context as stream:
                    join_replica(stream, protocol_version=v1.VERSION, replica=replica,
                                 host_heartbeat=host_heartbeat)
                    _enable_tcp_keepalive(connection)
                    joined = True
                    if not host_heartbeat:
                        connection.settimeout(None)
                    yield replica
                    events = (_heartbeat_events(stream) if host_heartbeat
                              else iter(lambda: _receive_event(stream, v1.VERSION), None))
                    for event in events:
                        if replica.apply(event):
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

