from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import socket
from threading import Event, Thread
from time import monotonic
import unittest
from unittest.mock import patch

from protocol import v1
from sync_model import Host
from wire import Server, _TimedFrames, client, follow_replica, receive, send


class GuestHeartbeatTests(unittest.TestCase):
    def test_idle_guest_survives_repeated_matching_pongs(self):
        host = Host()
        with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as pool:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(3)

            def serve():
                connection, _ = listener.accept()
                with connection, connection.makefile("rwb") as stream:
                    connection.settimeout(3)
                    send(stream, {"type": "hello"}, protocol_version=1)
                    self.assertTrue(receive(stream, protocol_version=1)["heartbeat"])
                    send(stream, {"type": "snapshot", "data": host.snapshot()}, protocol_version=1)
                    for expected_nonce in (1, 2, 3):
                        request = receive(stream, protocol_version=1)
                        self.assertEqual(request, {"version": 1, "type": "ping", "nonce": expected_nonce})
                        send(stream, {"type": "pong", "nonce": expected_nonce}, protocol_version=1)
                    event = host.emit("flag", "after-idle", True)
                    send(stream, {"type": "event", "data": event}, protocol_version=1)

            serving = pool.submit(serve)
            with (patch("wire.HOST_HEARTBEAT_INTERVAL", 0.05),
                  closing(follow_replica(listener.getsockname()[1], reconnect_attempts=0,
                                         host_heartbeat=True)) as updates):
                self.assertEqual(next(updates).sequence, 0)
                self.assertEqual(next(updates).snapshot(), host.snapshot())
            serving.result(timeout=3)

    def test_blocked_pong_does_not_hold_the_host_state_lock(self):
        pong_started, release_pong = Event(), Event()

        def pause_pong(stream, message, **options):
            if message["type"] == "pong":
                pong_started.set()
                if not release_pong.wait(4):
                    raise TimeoutError("test pong was not released")
            send(stream, message, **options)

        with Server(("127.0.0.1", 0), protocol_version=1) as server:
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
            thread.start()
            try:
                with socket.create_connection(server.server_address, timeout=2) as conn:
                    with conn.makefile("rwb") as stream, patch("wire.send", side_effect=pause_pong):
                        receive(stream, protocol_version=1)
                        send(stream, {"type": "hello", "heartbeat": True}, protocol_version=1)
                        receive(stream, protocol_version=1)
                        send(stream, {"type": "ping", "nonce": 1}, protocol_version=1)
                        self.assertTrue(pong_started.wait(2))
                        try:
                            with patch("wire.CLIENT_REPLY_TIMEOUT", 1):
                                self.assertEqual(client(server.server_address[1], protocol_version=1)["sequence"], 0)
                        finally:
                            release_pong.set()
                        self.assertEqual(receive(stream, protocol_version=1)["type"], "pong")
            finally:
                release_pong.set()
                server.shutdown()
                thread.join(timeout=2)

    def test_idle_host_answers_only_after_heartbeat_negotiation(self):
        with Server(("127.0.0.1", 0), protocol_version=1) as server:
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
            thread.start()
            try:
                for negotiate in (True, False):
                    with self.subTest(negotiate=negotiate):
                        with socket.create_connection(server.server_address, timeout=2) as conn:
                            with conn.makefile("rwb") as stream:
                                self.assertEqual(receive(stream, protocol_version=1)["type"], "hello")
                                hello = {"type": "hello", "heartbeat": True} if negotiate else {"type": "hello"}
                                send(stream, hello, protocol_version=1)
                                self.assertEqual(receive(stream, protocol_version=1)["data"]["sequence"], 0)
                                send(stream, {"type": "ping", "nonce": 7}, protocol_version=1)
                                if negotiate:
                                    reply = receive(stream, protocol_version=1)
                                    self.assertEqual(reply, {"version": 1, "type": "pong", "nonce": 7})
                                else:
                                    with self.assertRaises(EOFError):
                                        receive(stream, protocol_version=1)
                self.assertEqual(server.host_state.sequence, 0)
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_silent_application_rejoins_even_while_first_tcp_socket_stays_open(self):
        host = Host()
        rejoined = Event()
        with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as pool:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(3)

            def join(connection):
                connection.settimeout(2)
                stream = connection.makefile("rwb")
                send(stream, {"type": "hello"}, protocol_version=1)
                self.assertIs(receive(stream, protocol_version=1)["heartbeat"], True)
                send(stream, {"type": "snapshot", "data": host.snapshot()}, protocol_version=1)
                return stream

            def serve():
                first, _ = listener.accept()
                with first, join(first) as stream:
                    self.assertEqual(receive(stream, protocol_version=1)["type"], "ping")
                    # Keep the socket open and ignore the request, as a stalled app would.
                    host.emit("door", "hall", "open")
                    second, _ = listener.accept()
                    with second, join(second) as stream:
                        probe = receive(stream, protocol_version=1)
                        self.assertEqual(probe["type"], "ping")
                        send(stream, {"type": "pong", "nonce": probe["nonce"]}, protocol_version=1)
                        event = host.emit("flag", "recovered", True)
                        send(stream, {"type": "event", "data": event}, protocol_version=1)
                        self.assertTrue(rejoined.wait(2))

            work = pool.submit(serve)
            with (patch("wire.HOST_HEARTBEAT_TIMEOUT", 0.25),
                  closing(follow_replica(listener.getsockname()[1], reconnect_attempts=1,
                                         host_heartbeat=True)) as updates):
                self.assertEqual(next(updates).sequence, 0)
                self.assertIsNone(next(updates))
                self.assertEqual(next(updates).sequence, 1)
                self.assertEqual(next(updates).snapshot(), host.snapshot())
                rejoined.set()
            work.result(timeout=3)

    def test_frame_reader_keeps_partial_data_across_a_scheduling_timeout(self):
        source, destination = socket.socketpair()
        with source, destination:
            source.sendall(b'{"version":1,"type":')
            frames = _TimedFrames(destination)
            frames.deadline = monotonic() + 0.05
            with self.assertRaises(TimeoutError):
                receive(frames, protocol_version=1)
            source.sendall(b'"pong","nonce":3}\n{"version":1,"type":"pong","nonce":4}\n')
            frames.deadline = monotonic() + 2
            self.assertEqual(receive(frames, protocol_version=1)["nonce"], 3)
            self.assertEqual(receive(frames, protocol_version=1)["nonce"], 4)

    def test_rejects_malformed_heartbeat_messages(self):
        for message in (
            {"type": "hello", "heartbeat": False}, {"type": "hello", "heartbeat": 1},
            {"type": "ping", "nonce": True}, {"type": "pong", "nonce": 0},
            {"type": "ping", "nonce": 1, "extra": 1},
        ):
            with self.subTest(message=message), self.assertRaises(v1.ProtocolError):
                v1.encode({"version": 1, **message})


if __name__ == "__main__":
    unittest.main()
