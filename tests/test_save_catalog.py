from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from protocol.v1 import encode, decode, ProtocolError
from save_catalog import SaveCatalog, saved_time
from steam_pose_bridge import PoseGuest, PoseHost


def ticks(day, second=0):
    delta = datetime(2026, 11, day, 23, 28, second) - datetime.min
    return str((delta.days * 86400 + delta.seconds) * 10_000_000)


def source(sequence=1, stamp=100):
    return {"schema": 1, "source": "re2", "tdb": 70, "mode": 1, "run_id": "catalog-test",
            "sequence": sequence, "observed_at": stamp, "available": True, "reason": "ok",
            "entries": [{"slot_id": slot, "timestamp": ticks(day), "scenario": 1,
                         "title": "Test", "subtitle": f"Test save {slot}", "detail": "Test metadata"}
                        for slot, day in ((0, 12), (4, 11))]}


class SaveCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "catalog.json"
        self.clock = patch("save_catalog.time.time", return_value=100).start()
        self.addCleanup(patch.stopall)
        self.write(source())

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def test_real_metadata_keys_and_date_filter_preserve_calendar_ticks(self):
        catalog = SaveCatalog(self.path, allow_date="2026-11-11")
        view = catalog.snapshot()
        self.assertEqual([entry["key"] for entry in view["entries"]], ["scenario:4"])
        selected = catalog.select("scenario:4")
        self.assertEqual(selected["scenario"], 1)
        self.assertEqual(saved_time(selected["timestamp"]), datetime(2026, 11, 11, 23, 28))
        with self.assertRaises(ValueError):
            catalog.select("scenario:0")
        with self.assertRaises(ValueError):
            catalog.select("data004Slot.bin")

    def test_partial_write_does_not_renew_lease_and_busy_clears_immediately(self):
        catalog = SaveCatalog(self.path)
        self.assertTrue(catalog.snapshot()["available"])
        self.path.write_text('{"schema":', encoding="utf-8")
        self.clock.return_value = 102
        self.assertTrue(catalog.snapshot()["available"])
        self.clock.return_value = 104
        self.assertFalse(catalog.snapshot()["available"])
        self.clock.return_value = 100
        busy = {**source(2), "available": False, "reason": "save_service_busy", "entries": None}
        self.write(busy)
        self.assertEqual(catalog.snapshot()["reason"], "save_service_busy")
        self.assertEqual(catalog.snapshot()["entries"], [])

    def test_old_source_sequence_cannot_replace_current_metadata(self):
        catalog = SaveCatalog(self.path)
        self.write(source(2))
        current = catalog.snapshot()
        old = source(1, 101)
        old["entries"][1]["subtitle"] = "Older data"
        self.write(old)
        self.clock.return_value = 101
        self.assertEqual(catalog.snapshot(), current)
        self.clock.return_value = 104
        self.assertFalse(catalog.snapshot()["available"])

    def test_malformed_native_catalog_never_produces_a_selection(self):
        for change in ("duplicate", "scenario", "timestamp", "tdb"):
            value = source()
            if change == "duplicate":
                value["entries"].append(deepcopy(value["entries"][0]))
            elif change == "scenario":
                value["entries"][0]["scenario"] = True
            elif change == "timestamp":
                value["entries"][0]["timestamp"] = "6.39e17"
            else:
                value["tdb"] = 69
            self.write(value)
            with self.subTest(change=change):
                self.assertFalse(SaveCatalog(self.path).snapshot()["available"])

    def test_selection_and_changes_are_bound_to_host_readiness(self):
        catalog = SaveCatalog(self.path, allow_date="2026-11-11")
        host = PoseHost("leon", "claire", lobby_config={"catalog": catalog})
        guest = PoseGuest("leon", "claire")
        guest.receive(host.receive(guest.hello(), now=100))
        revision = host.lobby.snapshot()["data"]["revision"]
        with self.assertRaises(ValueError):
            host.lobby.configure("scenario:0", {}, revision)
        with self.assertRaises(ValueError):
            host.lobby.configure("scenario:4", {"campaign": "leon"}, revision)
        host.lobby.configure("scenario:4", {}, revision)
        selected = decode(encode(host.lobby.snapshot(), steam_pose=True), steam_pose=True)
        self.assertEqual(selected["data"]["save_ref"]["slot_id"], 4)
        self.assertTrue(guest.receive(selected))
        host.lobby.set_ready("leon", True, host.lobby.lobby.revision)
        delayed = guest.lobby.ready_message(True)
        host.receive(delayed, now=100)
        self.assertTrue(all(host.lobby.lobby.ready.values()))
        changed = source(2)
        changed["entries"][1]["timestamp"] = ticks(11, 1)
        self.write(changed)
        refreshed = host.lobby.snapshot()
        self.assertFalse(any(refreshed["data"]["ready"].values()))
        self.assertNotEqual(refreshed["data"]["save_ref"], selected["data"]["save_ref"])
        host.receive(delayed, now=100)
        self.assertFalse(any(host.lobby.lobby.ready.values()))
        self.assertTrue(guest.receive(refreshed))
        self.clock.return_value = 104
        missing = host.lobby.snapshot()
        self.assertEqual(missing["data"]["save_ref"], {"available": False})
        self.assertTrue(guest.receive(missing))
        with self.assertRaises(ValueError):
            guest.lobby.ready_message(True)

    def test_reference_mismatch_is_rejected_by_steam_codec(self):
        host = PoseHost("leon", "claire", lobby_config={"catalog": SaveCatalog(self.path),
                                                          "save_slot": "scenario:4"})
        frame = host.lobby.snapshot()
        frame["data"]["save_ref"]["slot_id"] = 0
        with self.assertRaises(ProtocolError):
            encode(frame, steam_pose=True)
        frame["data"]["save_ref"] = {"available": 0}
        with self.assertRaises(ProtocolError):
            encode(frame, steam_pose=True)
