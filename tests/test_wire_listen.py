from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
import socket
import time
import unittest
from unittest.mock import patch

from sync_model import Host
from wire import client, receive, send


class ContinuousListenerTests(unittest.TestCase):
    def test_waits_during_idle_play_and_returns_last_snapshot_on_clean_eof(self):
        for version in (0, 1):
            with self.subTest(version=version):
                self._exercise_idle_disconnect(version)

    def _exercise_idle_disconnect(self, version):
        with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as executor:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(3)
            host = Host()

            def serve():
                connection, _ = listener.accept()
                with connection, connection.makefile("rwb") as stream:
                    if version:
                        send(stream, {"type": "hello"}, protocol_version=version)
                        self.assertEqual(receive(stream, protocol_version=version)["type"], "hello")
                    send(stream, {"type": "snapshot", "data": host.snapshot()},
                         protocol_version=version)
                    time.sleep(0.65)
                    event = host.emit("door", "hall", "open")
                    send(stream, {"type": "event", "data": event}, protocol_version=version)

            serving = executor.submit(serve)
            with patch("wire.CLIENT_REPLY_TIMEOUT", 0.4), redirect_stdout(StringIO()):
                state = client(listener.getsockname()[1], listen=True, event_count=0,
                               protocol_version=version)
            serving.result(timeout=3)
            self.assertEqual(state, host.snapshot())
            self.assertEqual(state["sequence"], 1)


if __name__ == "__main__":
    unittest.main()
