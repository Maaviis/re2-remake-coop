import json
from pathlib import Path
import tempfile
import unittest

from save_protection import read_save_protection


def protection_documents(now=100):
    common = {'schema': 1, 'active': True, 'at': now, 'game_pid': 42,
              'run_id': 'a' * 32, 'app_id': 883710, 'build_id': 11636119}
    return ({**common, 'source': 'steam_storage_guard', 'reason': 'ok',
             'interface': '014', 'guarded_methods': 10},
            {**common, 'source': 'inherited_save_locks', 'locked_files': 12})


def write_protection(data, native=None, launch=None):
    defaults = protection_documents()
    for name, value in (('native_save_guard', defaults[0] if native is None else native),
                        ('protected_launch', defaults[1] if launch is None else launch)):
        (data / ('re2_coop_' + name + '.json')).write_text(json.dumps(value), encoding='utf-8')


class SaveProtectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)

    def test_current_receipts_bind_both_layers_to_one_game(self):
        write_protection(self.data)
        self.assertEqual(read_save_protection(self.data, now=103), {'game_pid': 42, 'run_id': 'a' * 32})

    def test_missing_old_future_or_inactive_receipts_are_rejected(self):
        with self.assertRaises(OSError):
            read_save_protection(self.data, now=100)
        native, launch = protection_documents()
        for changes in ({'at': 96}, {'at': 101}, {'active': False}, {'active': 1},
                        {'game_pid': True}, {'run_id': 'x' * 32}, {'app_id': 1},
                        {'schema': True}, {'build_id': 0}):
            for index in (0, 1):
                values = [native.copy(), launch.copy()]
                values[index].update(changes)
                write_protection(self.data, *values)
                with self.subTest(changes=changes, index=index), self.assertRaises(ValueError):
                    read_save_protection(self.data, now=100)

    def test_different_process_or_launch_and_partial_native_guard_are_rejected(self):
        native, launch = protection_documents()
        for changes in ({'game_pid': 43}, {'run_id': 'b' * 32}, {'locked_files': 0}, {'locked_files': True}):
            write_protection(self.data, native, {**launch, **changes})
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                read_save_protection(self.data, now=100)
        for changes in ({'interface': '016'}, {'guarded_methods': 9}, {'guarded_methods': True}, {'reason': 'storage_table_changed'}):
            write_protection(self.data, {**native, **changes}, launch)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                read_save_protection(self.data, now=100)
