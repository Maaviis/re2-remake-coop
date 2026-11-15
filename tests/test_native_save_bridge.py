from copy import deepcopy
import json
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep, time
import unittest

from lobby_control import select_save, submit
from lobby_sync import write_json
from save_catalog import SaveCatalog
from steam_pose_bridge import _encode, run_bridge
from tests.test_save_catalog import source, ticks


class NativeSaveBridgeTests(unittest.TestCase):
    def test_native_choice_and_metadata_change_reach_the_other_bridge(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            host_data, guest_data = root / "host", root / "guest"
            host_data.mkdir(); guest_data.mkdir()
            catalog_path = host_data / "re2_coop_save_catalog.json"
            value = source(stamp=int(time()))
            second = deepcopy(value["entries"][1])
            second.update(slot_id=5, subtitle="Another test save")
            value["entries"].append(second)
            write_json(catalog_path, value)
            inboxes = [Queue(), Queue()]
            errors, stops = Queue(), [Event(), Event()]

            class Link:
                def __init__(self, index):
                    self.index = index
                    self.role = b"H" if index == 0 else b"G"
                    self.epoch = b"catalog-link"

                def receive(self):
                    try:
                        return inboxes[self.index].get_nowait()
                    except Empty:
                        return None

                def send(self, message):
                    inboxes[1 - self.index].put(_encode(message))

            def run(index):
                try:
                    run_bridge((host_data, guest_data)[index], Link(index), b"H" if index == 0 else b"G",
                               "leon", "claire", stop=stops[index], lobby_enabled=True,
                               save_catalog=SaveCatalog(catalog_path, allow_date="2026-11-11") if index == 0 else None)
                except BaseException as exc:
                    errors.put(exc)

            def wait(directory, predicate):
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    if not errors.empty():
                        raise errors.get()
                    try:
                        result = json.loads((directory / "re2_coop_lobby.json").read_text(encoding="utf-8"))
                        if result["connected"] and result["lobby"] and predicate(result):
                            return result
                    except (FileNotFoundError, PermissionError):
                        pass
                    sleep(0.01)
                self.fail("native save metadata did not reach the other bridge")

            threads = [Thread(target=run, args=(index,)) for index in (0, 1)]
            for thread in threads:
                thread.start()
            try:
                wait(host_data, lambda item: bool(item["catalog"]["entries"]))
                with self.assertRaises(ValueError):
                    select_save(host_data, "scenario:0")
                select_save(host_data, "scenario:4")
                selected = wait(guest_data, lambda item: item["lobby"]["data"]["save_ref"].get("slot_id") == 4)
                self.assertEqual(selected["lobby"]["data"]["save_ref"]["scenario"], 1)
                host_status = wait(host_data, lambda item: item["lobby"]["data"]["save_ref"].get("slot_id") == 4)
                # REFramework's empty Lua table becomes JSON null on this local command path.
                write_json(host_data / "re2_coop_lobby_command.json", {
                    "id": "lua-empty-settings", "written_at": int(time()),
                    "session_id": host_status["lobby"]["session_id"],
                    "revision": host_status["lobby"]["data"]["revision"], "action": "configure",
                    "value": {"save_slot": "scenario:5", "settings": None}})
                wait(guest_data, lambda item: item["lobby"]["data"]["save_ref"].get("slot_id") == 5)
                submit(host_data, "ready", True)
                submit(guest_data, "ready", True)
                before = wait(guest_data, lambda item: all(item["lobby"]["data"]["ready"].values()))
                value.update(sequence=2, observed_at=int(time()))
                value["entries"][2]["timestamp"] = ticks(11, 1)
                write_json(catalog_path, value)
                changed = wait(guest_data, lambda item: item["lobby"]["data"]["revision"] > before["lobby"]["data"]["revision"])
                self.assertFalse(any(changed["lobby"]["data"]["ready"].values()))
                self.assertNotEqual(changed["lobby"]["data"]["save_ref"], before["lobby"]["data"]["save_ref"])
            finally:
                for stop in stops:
                    stop.set()
                for thread in threads:
                    thread.join(3)
                    self.assertFalse(thread.is_alive())
                if not errors.empty():
                    raise errors.get()
