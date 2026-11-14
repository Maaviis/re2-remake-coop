from contextlib import ExitStack, contextmanager
import socket
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from test_wire_v1 import running_server
from wire import join_replica, receive, send


class WireBackpressureTests(unittest.TestCase):
    @contextmanager
    def peers(self, version):
        with running_server(version) as server, ExitStack() as stack:
            stalled = stack.enter_context(socket.socket())
            stalled.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            stalled.settimeout(2)
            stalled.bind(("127.0.0.1", 0))
            stalled_address = stalled.getsockname()
            accept = server.get_request

            def accept_with_small_send_buffer():
                connection, address = accept()
                if address == stalled_address:
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
                return connection, address

            stack.enter_context(patch.object(server, "get_request", accept_with_small_send_buffer))
            stalled.connect(server.server_address)
            stalled_stream = stack.enter_context(stalled.makefile("rwb"))
            join_replica(stalled_stream, protocol_version=version)
            # Keep the first peer connected, and stop reading immediately after its snapshot.
            active = stack.enter_context(socket.create_connection(server.server_address, timeout=2))
            stream = stack.enter_context(active.makefile("rwb"))
            replica = join_replica(stream, protocol_version=version)
            yield server, stalled_address, stream, replica

    def assert_stalled_peer_disconnected(self, server, stalled_address):
        deadline = monotonic() + 3
        while monotonic() < deadline:
            with server.state_lock:
                if all(peer.client_address != stalled_address for peer in server.clients):
                    return
            sleep(0.01)
        self.fail("host did not unregister the non-reading peer")

    def exercise_non_reading_peer(self, version):
        with self.peers(version) as (server, stalled_address, stream, replica):
            for sequence in range(1, 9):
                send(stream, {"type": "propose", "kind": "flag", "target": "padding",
                              "value": str(sequence) + "x" * 96_000}, protocol_version=version)
                try:
                    response = receive(stream, protocol_version=version)
                except TimeoutError:
                    self.fail(f"healthy peer stopped receiving at sequence {sequence}")
                self.assertEqual(response["type"], "event")
                self.assertTrue(replica.apply(response["data"]))
                self.assertEqual(replica.sequence, sequence)

            with socket.create_connection(server.server_address, timeout=2) as connection:
                with connection.makefile("rwb") as fresh:
                    restored = join_replica(fresh, protocol_version=version)
                    self.assertEqual(restored.snapshot(), replica.snapshot())
            self.assert_stalled_peer_disconnected(server, stalled_address)
            self.assertEqual(server.host_state.snapshot(), replica.snapshot())

    def test_non_reading_peer_times_out_without_blocking_broadcast_or_reconnect(self):
        for version in (0, 1):
            with self.subTest(version=version):
                self.exercise_non_reading_peer(version)

    def test_full_queue_disconnects_only_stalled_peer_before_write_timeout(self):
        # The assertions have shorter deadlines than this socket write.
        with patch("wire.PEER_WRITE_TIMEOUT", 10), patch("wire.MAX_PENDING_PEER_FRAMES", 2):
            for version in (0, 1):
                with self.subTest(version=version):
                    self.exercise_non_reading_peer(version)

    def test_write_half_close_still_receives_all_committed_replies(self):
        def paced_send(stream, message, **options):
            if message["type"] == "event":
                sleep(0.07)
            send(stream, message, **options)

        with (patch("wire.PEER_WRITE_TIMEOUT", 0.1), patch("wire.send", side_effect=paced_send),
              running_server(1) as server,
              socket.create_connection(server.server_address, timeout=2) as connection,
              connection.makefile("rwb") as stream):
            replica = join_replica(stream, protocol_version=1)
            for target in ("first", "second", "third"):
                send(stream, {"type": "propose", "kind": "flag", "target": target, "value": True},
                     protocol_version=1)
            connection.shutdown(socket.SHUT_WR)

            for sequence in range(1, 4):
                reply = receive(stream, protocol_version=1)
                self.assertTrue(replica.apply(reply["data"]))
                self.assertEqual(replica.sequence, sequence)
            with self.assertRaises(EOFError):
                receive(stream, protocol_version=1)
            self.assertEqual(server.host_state.snapshot(), replica.snapshot())
