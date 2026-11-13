from contextlib import contextmanager
from io import BytesIO
import json
import select
import socket
import threading
import unittest
from unittest.mock import patch

from protocol.v1 import ProtocolError
from wire import Server, client, receive


@contextmanager
def running_server(protocol_version):
    with Server(("127.0.0.1", 0), protocol_version=protocol_version) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=2)


class VersionedWireTests(unittest.TestCase):
    def test_host_rejects_wrong_first_message_without_sending_a_snapshot(self):
        for first_message in (
            {"type": "hello", "version": 2},
            {"type": "hello"},
            {"type": "propose", "version": 1, "kind": "flag", "target": "intro", "value": True},
        ):
            with self.subTest(first_message=first_message), running_server(1) as server:
                with socket.create_connection(server.server_address, timeout=2) as peer:
                    with peer.makefile("rwb") as stream:
                        self.assertEqual(json.loads(stream.readline()), {"version": 1, "type": "hello"})
                        stream.write(json.dumps(first_message).encode() + b"\n")
                        stream.flush()
                        self.assertEqual(stream.readline(), b"")
                self.assertEqual(server.host_state.sequence, 0)
                self.assertFalse(server.clients)
                self.assertEqual(client(server.server_address[1], protocol_version=1)["sequence"], 0)

    def test_legacy_host_snapshot_is_never_applied_by_versioned_client(self):
        with running_server(0) as server, patch("wire.Replica.restore") as restore:
            with self.assertRaisesRegex(ProtocolError, "unsupported protocol version"):
                client(server.server_address[1], protocol_version=1)
            restore.assert_not_called()

    def test_legacy_client_fails_at_versioned_greeting(self):
        with running_server(1) as server, patch("wire.Replica.restore") as restore:
            with self.assertRaisesRegex(ValueError, "expected snapshot"):
                client(server.server_address[1])
            restore.assert_not_called()
            self.assertFalse(server.clients)

    def test_inactive_peer_times_out_without_blocking_another_guest(self):
        with patch("wire.HANDSHAKE_TIMEOUT", 1), running_server(1) as server:
            with socket.create_connection(server.server_address, timeout=2) as peer:
                with peer.makefile("rb") as stream:
                    self.assertEqual(json.loads(stream.readline()), {"version": 1, "type": "hello"})
                    self.assertEqual(client(server.server_address[1], protocol_version=1)["sequence"], 0)
                    self.assertEqual(select.select([peer], [], [], 0)[0], [])
                    self.assertEqual(stream.readline(), b"")

    def test_versioned_frame_limit_counts_the_newline(self):
        hello = b'{"version":1,"type":"hello"}\n'
        with patch("wire.MAX_FRAME_BYTES", len(hello)):
            self.assertEqual(receive(BytesIO(hello), protocol_version=1)["type"], "hello")
            with self.assertRaisesRegex(ProtocolError, "byte limit"):
                receive(BytesIO(b" " + hello), protocol_version=1)

    def test_rejects_proposal_that_would_make_event_too_large(self):
        proposal = {"kind": "door", "target": "hall", "value": "x" * 850}
        with patch("wire.MAX_FRAME_BYTES", 1024), running_server(1) as server:
            port = server.server_address[1]
            with self.assertRaisesRegex(ValueError, "byte limit"):
                client(port, proposal=proposal, protocol_version=1)
            self.assertEqual(server.host_state.sequence, 0)
            self.assertEqual(client(port, protocol_version=1)["state"]["doors"], {})

    def test_rejects_proposal_that_would_make_reconnect_snapshot_too_large(self):
        first = {"kind": "door", "target": "hall", "value": "x" * 500}
        second = {"kind": "door", "target": "lobby", "value": "x" * 500}
        with patch("wire.MAX_FRAME_BYTES", 1024), running_server(1) as server:
            port = server.server_address[1]
            accepted = client(port, proposal=first, protocol_version=1)
            with self.assertRaisesRegex(ValueError, "byte limit"):
                client(port, proposal=second, protocol_version=1)
            self.assertEqual(server.host_state.sequence, 1)
            self.assertEqual(client(port, protocol_version=1), accepted)

    def test_unterminated_proposal_is_rejected_after_handshake(self):
        with running_server(1) as server:
            with socket.create_connection(server.server_address, timeout=2) as peer:
                with peer.makefile("rwb") as stream:
                    self.assertEqual(json.loads(stream.readline()), {"version": 1, "type": "hello"})
                    stream.write(b'{"version":1,"type":"hello"}\n')
                    stream.flush()
                    self.assertEqual(json.loads(stream.readline())["type"], "snapshot")
                    stream.write(b'{"version":1,"type":"propose","kind":"flag","target":"intro","value":true}')
                    stream.flush()
                    peer.shutdown(socket.SHUT_WR)
                    self.assertEqual(stream.readline(), b"")
            self.assertEqual(server.host_state.sequence, 0)


if __name__ == "__main__":
    unittest.main()
