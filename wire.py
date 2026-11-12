"""Local loopback transport demonstration, not the planned Steam transport."""

import argparse
import json
import socket
import socketserver
import threading

from protocol import v1
from sync_model import Host, Replica


PROTOCOL_VERSIONS = (0, v1.VERSION)
HANDSHAKE_TIMEOUT = 5
MAX_FRAME_BYTES = 1024 * 1024


def _check_protocol_version(version):
    if type(version) is not int or version not in PROTOCOL_VERSIONS:
        raise ValueError("unsupported loopback protocol version")


def send(stream, message, *, protocol_version=0):
    if protocol_version:
        payload = v1.encode({**message, "version": protocol_version})
    else:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stream.write(payload + b"\n")
    stream.flush()


def receive(stream, *, protocol_version=0):
    line = stream.readline(MAX_FRAME_BYTES + 1 if protocol_version else MAX_FRAME_BYTES)
    if not line:
        raise EOFError("connection closed")
    if protocol_version:
        if len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
            raise v1.ProtocolError("expected a complete v1 frame within the byte limit")
        return v1.decode(line[:-1])
    return json.loads(line)


def _require_hello(stream, protocol_version):
    if receive(stream, protocol_version=protocol_version)["type"] != "hello":
        raise v1.ProtocolError("expected protocol hello before snapshot")


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
                        event = host.emit(message["kind"], message.get("target"), message.get("value"))
                    except (KeyError, ValueError, TypeError) as exc:
                        send(self.wfile, {"type": "error", "message": str(exc)},
                             protocol_version=protocol_version)
                        continue
                    for stream in tuple(self.server.clients):
                        try:
                            send(stream, {"type": "event", "data": event},
                                 protocol_version=protocol_version)
                        except OSError:
                            self.server.clients.discard(stream)
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


def client(port, proposal=None, listen=False, event_count=1, *, protocol_version=0):
    _check_protocol_version(protocol_version)
    if event_count < 0:
        raise ValueError("event_count must be nonnegative")
    replica = Replica()
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.settimeout(5)
        with connection.makefile("rwb") as stream:
            if protocol_version:
                _require_hello(stream, protocol_version)
                send(stream, {"type": "hello"}, protocol_version=protocol_version)
            greeting = receive(stream, protocol_version=protocol_version)
            if greeting["type"] != "snapshot":
                raise ValueError("expected snapshot")
            replica.restore(greeting["data"])
            if listen:
                print("READY", flush=True)
            if proposal is not None:
                message = {"type": "propose", **proposal}
                if protocol_version:
                    message.setdefault("target", None)
                    message.setdefault("value", None)
                send(stream, message, protocol_version=protocol_version)
            if proposal is not None or listen:
                received = 0
                while event_count == 0 or received < event_count:
                    response = receive(stream, protocol_version=protocol_version)
                    if response["type"] != "event":
                        raise ValueError(response.get("message", "event rejected"))
                    replica.apply(response["data"])
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

