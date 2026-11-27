import hashlib
import json
from pathlib import Path
import unittest

from protocol.v1 import ProtocolError, decode, encode
from sync_model import Host, Replica


VECTORS = Path(__file__).resolve().parents[1] / "bridge" / "protocol" / "v1-examples.json"


class ProtocolV1Tests(unittest.TestCase):
    def setUp(self):
        data = json.loads(VECTORS.read_text(encoding="utf-8"))
        self.vectors = data["messages"]
        self.canonical_state = data["canonical_reconnect_state_utf8"].encode("utf-8")

    def test_examples_round_trip_through_the_reference_codec(self):
        for name, message in self.vectors.items():
            with self.subTest(example=name):
                self.assertEqual(decode(encode(message)), message)

    def test_example_events_and_snapshot_match_the_prototype(self):
        replica = Replica()
        host = Host(session_id="example-session")
        self.assertEqual(self.vectors["initial_snapshot"],
                         {"version": 1, "type": "snapshot", "data": host.snapshot()})
        replica.restore(decode(encode(self.vectors["initial_snapshot"]))["data"])

        proposal = decode(encode(self.vectors["proposal"]))
        for name in ("player_event", "world_event", "story_event", "cutscene_event"):
            message = self.vectors[name]
            data = proposal if name == "player_event" else message["data"]
            event = host.emit(data["kind"], data["target"], data["value"])
            self.assertEqual(message, {"version": 1, "type": "event", "data": event})
            self.assertTrue(replica.apply(decode(encode(message))["data"]))

        snapshot = decode(encode(self.vectors["reconnect_snapshot"]))["data"]
        self.assertEqual(hashlib.sha256(self.canonical_state).hexdigest(), snapshot["digest"])
        self.assertEqual(json.loads(self.canonical_state), snapshot["state"])
        self.assertEqual(snapshot, host.snapshot())
        self.assertEqual(snapshot, replica.snapshot())
        reconnecting = Replica()
        reconnecting.restore(snapshot)
        self.assertEqual(reconnecting.snapshot(), replica.snapshot())

    def test_steam_pose_challenge_is_required_only_in_steam_pose_mode(self):
        request_id = "a" * 32
        for plain in ({"version": 1, "type": "hello"}, self.vectors["initial_snapshot"]):
            tagged = {**plain, "request_id": request_id}
            with self.subTest(kind=plain["type"]):
                self.assertEqual(decode(encode(plain)), plain)
                self.assertEqual(decode(encode(tagged, steam_pose=True), steam_pose=True), tagged)
                with self.assertRaises(ProtocolError):
                    encode(plain, steam_pose=True)
                with self.assertRaises(ProtocolError):
                    decode(encode(plain), steam_pose=True)
                with self.assertRaises(ProtocolError):
                    encode(tagged)
                with self.assertRaises(ProtocolError):
                    decode(encode(tagged, steam_pose=True))
                for invalid in (False, 1, "", "a" * 31, "z" * 32):
                    with self.assertRaises(ProtocolError):
                        encode({**tagged, "request_id": invalid}, steam_pose=True)

    def test_only_steam_pose_proposals_require_a_session_id(self):
        plain = self.vectors["proposal"]
        tagged = {**plain, "session_id": "host-session"}
        self.assertEqual(decode(encode(plain)), plain)
        self.assertEqual(decode(encode(tagged, steam_pose=True), steam_pose=True), tagged)
        with self.assertRaises(ProtocolError):
            decode(encode(plain), steam_pose=True)
        with self.assertRaises(ProtocolError):
            encode(tagged)
        for invalid in ("", None, 1):
            with self.assertRaises(ProtocolError):
                encode({**tagged, "session_id": invalid}, steam_pose=True)


    def test_rejects_missing_or_unsupported_versions(self):
        sample = self.vectors["proposal"]
        for message in ({k: v for k, v in sample.items() if k != "version"},
                        {**sample, "version": 2}, {**sample, "version": True},
                        {**sample, "version": 1.0}):
            with self.subTest(message=message), self.assertRaises(ProtocolError):
                decode(json.dumps(message).encode())

    def test_rejects_invalid_envelope_payload_and_metadata(self):
        event = self.vectors["world_event"]
        snapshot = self.vectors["reconnect_snapshot"]
        for message in (
            {**event, "type": "other"},
            {**event, "extra": 1},
            {**event, "data": {k: v for k, v in event["data"].items() if k != "digest"}},
            {**event, "data": {**event["data"], "sequence": True}},
            {**event, "data": {**event["data"], "sequence": 2**53}},
            {**event, "data": {**event["data"], "kind": "custom"}},
            {**event, "data": {**event["data"], "target": None}},
            {**event, "data": {**event["data"], "digest": "bad"}},
            {**snapshot, "data": {**snapshot["data"], "state": {"doors": {}}}},
        ):
            with self.subTest(message=message), self.assertRaises(ProtocolError):
                decode(json.dumps(message).encode())

    def test_rejects_non_json_values_and_ambiguous_json(self):
        sample = self.vectors["proposal"]
        for value in (float("nan"), float("inf"), {1: "non-string key"}, "\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(ProtocolError):
                encode({**sample, "value": value})
        for value in (b"NaN", b"1e309", b'{"nested":1,"nested":2}', b'"\\ud800"'):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                decode(b'{"version":1,"type":"propose","kind":"player","target":"claire","value":'
                       + value + b"}")

    def test_payload_integers_are_portable_between_runtimes(self):
        sample = self.vectors["proposal"]
        edges = {**sample, "value": [2**53 - 1, -2**53 + 1]}
        self.assertEqual(decode(encode(edges)), edges)
        for value in (2**53, -2**53):
            oversized = {**sample, "value": [value]}
            with self.subTest(value=value):
                with self.assertRaises(ProtocolError):
                    encode(oversized)
                with self.assertRaises(ProtocolError):
                    decode(json.dumps(oversized).encode())


if __name__ == "__main__":
    unittest.main()
