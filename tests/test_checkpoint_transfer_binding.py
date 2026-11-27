from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from checkpoint_transfer_binding import ArchiveTransferBinding
from steam_pose_bridge import SteamPipe


class ArchiveTransferBindingTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(TemporaryDirectory())).resolve()
        self.solo=self.root/'123/883710/remote/win64_save';self.solo.mkdir(parents=True)
        (self.solo/'data00-1.bin').write_bytes(b'initialized guest profile without scenario files')
        self.choice={'namespace':'a'*32,'digest':'b'*64}
        self.scope={'game_pid':32,'role':'H','session_id':'c'*32,
                    'membership':{'revision':7,'session_id':'d'*32}}
        self.lobby={'revision':2,'settings':{'coop_checkpoint':{**self.choice,'scenario':0,'difficulty':1,
            'saved_at':'2026-11-26 12:00:00'}},'save_slot':None}
        self.guard={'protection':{'game_pid':32,'run_id':'e'*32},'guard_run_id':'vm',
            'runtime_protection':True,'in_title':True,'has_player':False,'loading_flow':False,'busy':False,
            'allowed_load_calls':0,'denied_loads':0,'writes':{}}
        self.pipe=SteamPipe(32,stream='snapshot')
        self.pipe.save_directory=lambda:self.solo
        self.pipe.lobby_status=lambda:'owned'
        self.pipe.membership_revision=lambda:7
        self.pipe.cloud_status=lambda:'cloud-app-disabled'
        self.pipe.request=lambda command,**kw:b'peer-round-trip-verified'
        self.enterContext(patch('checkpoint_transfer_binding.read_active_guard',side_effect=lambda *a,**kw:deepcopy(self.guard)))
        self.enterContext(patch('checkpoint_transfer_binding.read_connected_lobby',side_effect=lambda data:(deepcopy(self.scope),deepcopy(self.lobby))))
        self.enterContext(patch('checkpoint_transfer_binding.storage_guard_active',return_value=True))

    def test_binds_a_title_profile_without_a_scenario_save(self):
        binding=ArchiveTransferBinding(self.root,self.pipe,self.solo,self.choice,b'H')
        binding.confirm()
        self.assertEqual([p.name for p in self.solo.iterdir()],['data00-1.bin'])

    def test_selection_membership_and_guard_changes_are_rejected_after_construction(self):
        for action in (lambda:self.lobby.update(revision=3),lambda:self.scope['membership'].update(revision=8),
                       lambda:self.guard.update(guard_run_id='another vm'),lambda:self.guard.update(has_player=True),
                       lambda:self.guard['protection'].update(run_id='f'*32)):
            before=(deepcopy(self.scope),deepcopy(self.lobby),deepcopy(self.guard))
            binding=ArchiveTransferBinding(self.root,self.pipe,self.solo,self.choice,b'H')
            action()
            with self.assertRaises(ValueError):binding.confirm()
            self.scope,self.lobby,self.guard=before

    def test_cloud_or_profile_change_and_wrong_role_cannot_enter(self):
        with self.assertRaises(ValueError):ArchiveTransferBinding(self.root,self.pipe,self.solo,self.choice,b'G')
        self.pipe.cloud_status=lambda:'cloud-enabled'
        with self.assertRaises(ValueError):ArchiveTransferBinding(self.root,self.pipe,self.solo,self.choice,b'H')
        self.pipe.cloud_status=lambda:'cloud-app-disabled'
        binding=ArchiveTransferBinding(self.root,self.pipe,self.solo,self.choice,b'H')
        other=self.root/'other';other.mkdir();self.pipe.save_directory=lambda:other
        with self.assertRaises(ValueError):binding.confirm()

    def test_entry_point_uses_only_the_bound_profile_and_snapshot_session(self):
        binding=ArchiveTransferBinding(self.root,self.pipe,self.solo,self.choice,b'H')
        with patch('checkpoint_transfer_binding.send_archive',return_value=self.choice) as send:
            self.assertEqual(binding.exchange('f'*32),self.choice)
            args=send.call_args.args
            self.assertEqual(args[:4],(self.root,self.pipe,self.scope['session_id'],'f'*32))
            self.assertEqual(args[4].root,self.solo.parent.parent/'re2-coop-checkpoints'/self.choice['namespace'])
            self.assertEqual(args[5],self.choice['digest'])
        self.scope['role']='G';self.pipe.lobby_status=lambda:'joined'
        binding=ArchiveTransferBinding(self.root,self.pipe,self.solo,self.choice,b'G')
        with patch('checkpoint_transfer_binding.receive_archive',return_value=self.choice) as receive:
            self.assertEqual(binding.exchange('f'*32),self.choice)
            self.assertEqual(receive.call_args.args[4:6],(self.solo,self.choice))
