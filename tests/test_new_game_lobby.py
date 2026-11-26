import unittest
from unittest.mock import Mock

from lobby_sync import LobbyGuest, LobbyHost, validate_state
from protocol.v1 import decode, encode
from sync_model import state_digest


class NewGameLobbyTests(unittest.TestCase):
    def setUp(self):
        self.selection = {'scenario': 'LEON_A', 'difficulty': 'NORMAL'}
        self.catalog = Mock()
        self.catalog.snapshot.return_value = {'reason': 'no_eligible_saves', 'entries': []}
        self.source = Mock()
        self.source.resolve_new_game.side_effect = lambda value: state_digest({'new_game': value})
        self.host = LobbyHost('session', 'h', 'g', catalog=self.catalog, load_source=self.source)
        self.host.connect()
        self.guest = LobbyGuest('h', 'g', catalog=self.catalog)

    def select(self, selection):
        self.host.select_new_game(selection, self.host.lobby.revision)
        message = self.host.snapshot()
        self.assertTrue(self.guest.receive(decode(encode(message, steam_pose=True), steam_pose=True), 'session'))
        return message['data']

    def test_both_stage_same_fresh_intent_without_a_slot(self):
        state = self.select(self.selection)
        self.assertIsNone(state['save_slot'])
        self.assertNotIn('save_ref', state)
        revision = state['revision']
        consent = self.guest.ready_message(True, campaign_consent=True)
        self.assertEqual(consent, decode(encode(consent, steam_pose=True), steam_pose=True))
        self.host.set_ready('g', True, revision, new_game_identity=consent['new_game_identity'], campaign_consent=True)
        self.host.set_ready('h', True, revision)
        self.host.check_load(revision, start_campaign=True)
        self.guest.receive(self.host.snapshot(), 'session')
        self.assertTrue(self.host.acknowledge_load(self.guest.load_ack(self.source)))
        self.guest.receive(self.host.snapshot(), 'session')
        self.assertTrue(self.host.acknowledge_load(self.guest.load_ack(self.source, stage_id='b'*32)))
        self.assertTrue(self.host.begin_start('a'*32))
        message = self.host.snapshot()
        self.guest.receive(message, 'session')
        self.assertIsNotNone(self.guest.start_deadline(self.guest.current_message(), 'b'*32))
        self.assertEqual(message['data']['load_check']['save_digest'], state_digest({'new_game': self.selection}))
        self.catalog.select.assert_not_called()
        self.source.fingerprint.assert_not_called()

    def test_selection_revision_and_mode_are_bound_to_consent(self):
        state = self.select(self.selection)
        rev = state['revision']
        with self.assertRaises(ValueError):
            self.host.set_ready('g', True, rev, save_identity=state_digest({'new_game': self.selection}))
        with self.assertRaises(ValueError):
            validate_state({**state, 'save_slot': 'scenario:4'})
        with self.assertRaises(ValueError):
            self.host.select_new_game({'scenario':'LEON_B', 'difficulty':'NORMAL'}, rev)
        self.host.set_ready('h', True, rev)
        changed = self.select({**self.selection, 'scenario':'CLAIRE_A'})
        self.assertFalse(any(changed['ready'].values()))
        with self.assertRaises(ValueError):
            self.host.set_ready('h', True, rev)
        self.host.configure('scenario:4', {}, changed['revision'])
        self.assertNotIn('new_game', self.host.snapshot()['data'])
