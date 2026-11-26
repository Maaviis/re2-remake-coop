import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from campaign_hits import CampaignHitFiles, CampaignHitWindow
from tests.test_enemy_witness import guid


class CampaignHitFilesTests(unittest.TestCase):
    def test_host_challenge_expires_and_only_authorizes_one_pull_from_its_visit(self):
        window = CampaignHitWindow()
        with patch('campaign_hits.time.monotonic', return_value=100):
            self.assertEqual(window.accept(b'', 'visit-1'), b'')
            expired, stale_visit, live = (bytes.fromhex(window.next()) for _ in range(3))
            self.assertEqual(window.accept(live + b'hit', 'visit-1'), b'hit')
            self.assertEqual(window.accept(live + b'hit', 'visit-1'), b'')
            self.assertEqual(window.accept(stale_visit + b'hit', 'visit-2'), b'')
            expired = bytes.fromhex(window.next())
        with patch('campaign_hits.time.monotonic', return_value=103):
            self.assertEqual(window.accept(expired + b'hit', 'visit-2'), b'')

    def test_only_fresh_scoped_hits_cross_wire_and_duplicates_do_not_renew(self):
        with TemporaryDirectory() as temporary:
            data = Path(temporary)
            files = CampaignHitFiles(data, 'a' * 32, 'b' * 32)
            document = {'schema': 1, 'request_id': 'a' * 32, 'attempt_id': 'b' * 32,
                        'at': 100, 'area': {'scenario': 1, 'map': 17, 'area': 3},
                        'hits': [{'sequence': 1, 'id': guid(1), 'kind_id': 4, 'inherit_id': -1,
                                  'default_hp': 770, 'damage': 33, 'at': 100}]}
            checkpoint = {'game_guid': guid(5), 'save_guid': guid(6), 'scenario': 1, 'location': 11}
            files.source.write_text(json.dumps(document), encoding='utf-8')
            with patch('campaign_hits.time.time', return_value=100):
                packet = files.outgoing()
                self.assertNotIn(document['request_id'].encode(), packet)
                self.assertTrue(files.accept(packet, checkpoint, document['area'], 'visit-1'))
                received = files.target.read_bytes()
                receipt = json.loads(received)
                self.assertEqual(receipt['hits'][0]['damage'], 33)
                self.assertEqual(receipt['request_id'], document['request_id'])
            with patch('campaign_hits.time.time', return_value=101):
                self.assertTrue(files.accept(packet, checkpoint, document['area'], 'visit-1'))
                self.assertEqual(files.target.read_bytes(), received)
            with patch('campaign_hits.time.time', return_value=104):
                self.assertEqual(files.outgoing(), b'')
            self.assertFalse(files.accept(b'{"hits":[{"damage":true}]}', checkpoint, document['area'], 'visit-1'))
            self.assertFalse(files.accept(packet * 100, checkpoint, document['area'], 'visit-1'))
            self.assertEqual(files.target.read_bytes(), received)

    def test_native_context_loss_withdraws_unapplied_hits(self):
        with TemporaryDirectory() as temporary:
            files = CampaignHitFiles(Path(temporary), 'a' * 32, 'b' * 32)
            area = {'scenario': 1, 'map': 17, 'area': 3}
            hit = {'sequence': 1, 'id': guid(1), 'kind_id': 4, 'inherit_id': -1,
                   'default_hp': 770, 'damage': 33}
            payload = json.dumps({'area': area, 'hits': [hit]}).encode()
            self.assertTrue(files.accept(payload, {}, area, 'visit-1'))
            self.assertEqual(json.loads(files.target.read_bytes())['host_visit'], 'visit-1')
            self.assertTrue(files.accept(b'', {}, None, None))
            self.assertEqual(json.loads(files.target.read_bytes())['hits'], [])
            self.assertTrue(files.accept(payload, {}, area, 'visit-2'))
            self.assertEqual(json.loads(files.target.read_bytes())['hits'], [])

    def test_rejects_invalid_area_nonpositive_damage_and_forged_native_scope(self):
        with TemporaryDirectory() as temporary:
            files = CampaignHitFiles(Path(temporary), 'a' * 32, 'b' * 32)
            area = {'scenario': 1, 'map': 17, 'area': 3}
            hit = {'sequence': 1, 'id': guid(1), 'kind_id': 4, 'inherit_id': -1,
                   'default_hp': 770, 'damage': 33}
            for bad_area, bad_hit in (({**area, 'scenario': False}, hit), (area, {**hit, 'damage': 0}),
                                      (area, {**hit, 'damage': 770}), (area, {**hit, 'request_id': 'x'})):
                with self.subTest(area=bad_area, hit=bad_hit):
                    self.assertFalse(files.accept(json.dumps({'area': bad_area, 'hits': [bad_hit]}).encode(), {}, area, 'visit-1'))
            self.assertFalse(files.target.exists())
