"""Local loopback transport demonstration, not the planned Steam transport."""

import argparse
import json
import socket
import socketserver
import threading

from sync_model import Host, Replica


def send(stream, message):
    stream.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
    stream.flush()


def receive(stream):
    line = stream.readline(1024 * 1024)
    if not line:
        raise EOFError("connection closed")
    return json.loads(line)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        host = self.server.host_state
        with self.server.state_lock:
            send(self.wfile, {"type": "snapshot", "data": host.snapshot()})
            self.server.clients.add(self.wfile)
        try:
            while True:
                try:
                    message = receive(self.rfile)
                except EOFError:
                    return
                if message.get("type") != "propose":
                    send(self.wfile, {"type": "error", "message": "unknown request"})
                    continue
                with self.server.state_lock:
                    try:
                        event = host.emit(message["kind"], message.get("target"), message.get("value"))
                    except (KeyError, ValueError, TypeError) as exc:
                        send(self.wfile, {"type": "error", "message": str(exc)})
                        continue
                    for stream in tuple(self.server.clients):
                        try:
                            send(stream, {"type": "event", "data": event})
                        except OSError:
                            self.server.clients.discard(stream)
        finally:
            with self.server.state_lock:
                self.server.clients.discard(self.wfile)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, Handler)
        self.host_state = Host()
        self.state_lock = threading.RLock()
        self.clients = set()


def client(port, proposal=None, listen=False):
    replica = Replica()
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.settimeout(5)
        with connection.makefile("rwb") as stream:
            greeting = receive(stream)
            if greeting["type"] != "snapshot":
                raise ValueError("expected snapshot")
            replica.restore(greeting["data"])
            if listen:
                print("READY", flush=True)
            if proposal is not None:
                send(stream, {"type": "propose", **proposal})
            if proposal is not None or listen:
                response = receive(stream)
                if response["type"] != "event":
                    raise ValueError(response.get("message", "event rejected"))
                replica.apply(response["data"])
    return replica.snapshot()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host", "client"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--propose", help="JSON event proposal, client mode only")
    parser.add_argument("--listen", action="store_true", help="wait for one broadcast event")
    args = parser.parse_args()
    if args.mode == "host":
        with Server(("127.0.0.1", args.port)) as server:
            print(server.server_address[1], flush=True)
            server.serve_forever()
    else:
        print(json.dumps(client(args.port, json.loads(args.propose) if args.propose else None,
                                args.listen)))


if __name__ == "__main__":
    main()
