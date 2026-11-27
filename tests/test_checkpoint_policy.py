from copy import deepcopy
import json
import time
import unittest
from unittest.mock import patch

from checkpoint_workspace import CheckpointWorkspace, read_prepared_checkpoint
from load_preflight import NativeSaveSource, checkpoint_save_reference, read_staged_load
from lobby_sync import write_json
from readonly_save_control import arm
from sync_model import state_digest
from tests import test_checkpoint_workspace as workspace_fixtures


class CheckpointPolicyTests(unittest.TestCase):
    def setUp(self):
        workspace_fixtures.CheckpointWorkspaceTests.setUp(self)
        self.now = float(int(time.time())) + .1
        self.enterContext(patch('checkpoint_workspace.time.time', side_effect=lambda: self.now))
        self.lobby.update(host_id='host', guest_id='guest', connected=True,
                          ready={'host': True, 'guest': True})
        self.lobby['load_check'] = {'phase': 'prepared', 'reason': '', 'revision': self.lobby['revision'],
            'attempt_id': 'f'*32, 'save_digest': self.digest, 'admission': 1,
            'campaign_start': True, 'checkpoint_version': 1}
        self.guard.update(schema=1, active=True, hooks=26, at=int(self.now), protection_active=True,
                          checkpoint_supported=True, command_id='', command_error='', load_request_id='')
        self.policy = self.data/'re2_coop_save_policy.json'
        self.pipe.lobby_status = lambda: 'owned' if self.scope['role']=='H' else 'joined'
        original = self.pipe.request
        self.pipe.request = lambda command, **kw: b'peer-ready' if command==b'peer-status' else original(command, **kw)
        self.enterContext(patch('readonly_save_control.read_active_guard', side_effect=lambda *a,**kw:deepcopy(self.guard)))
        self.enterContext(patch('readonly_save_control.SteamPipe', return_value=self.pipe))
        self.enterContext(patch('readonly_save_control._storage_guard_active', return_value=True))
        self.enterContext(patch('load_preflight.read_save_protection', return_value=self.guard['protection']))
        self.publish_lobby()

    def publish_lobby(self):
        self.message = {'version':1, 'type':'lobby_state', 'session_id':self.scope['session_id'],
            'sequence':1, 'data':deepcopy(self.lobby), 'digest':state_digest(self.lobby)}
        write_json(self.data/'re2_coop_lobby.json', {'schema':1, 'written_at':int(self.now), 'connected':True,
            'game_pid':32, 'role':self.scope['role'], 'steam_lobby':self.pipe.lobby_status(),
            'steam_membership':self.scope['membership'], 'lobby':self.message})

    def prepare(self):
        return CheckpointWorkspace(self.data,self.pipe,self.solo,self.choice,self.stop).prepare(timeout=1)

    def arm(self, **changes):
        options = dict(load=True, require_receipt=True, prepared_lobby=self.solo,
                       expected_game_pid=32, expected_role=self.scope['role'], checkpoint=self.choice)
        options.update(changes)
        return arm(self.data, None, None, **options)

    def test_roles_share_archive_digest_without_sharing_solo_catalog_or_local_slot_time(self):
        policies = []
        for role,stamp in (('H','639001000000000000'),('G','639002000000000000')):
            self.scope['role']=role
            self.after_catalog=lambda value: value['reference'].update(timestamp=stamp)
            self.publish_lobby()
            receipt=self.prepare()
            request=self.arm()
            value=json.loads(self.policy.read_bytes())
            self.assertEqual(value['schema'],5)
            self.assertEqual(value['checkpoint'],self.choice)
            self.assertEqual(value['reference'],receipt['native_reference'])
            self.assertEqual(value['preparation_id'],receipt['request_id'])
            self.assertEqual(value['lobby_load']['save_digest'],self.digest)
            self.assertEqual(value['id'],request)
            policies.append(value)
            self.policy.unlink()
        self.assertNotEqual(policies[0]['id'],policies[1]['id'])
        self.assertNotEqual(policies[0]['reference']['timestamp'],policies[1]['reference']['timestamp'])
        self.assertEqual(policies[0]['checkpoint'],policies[1]['checkpoint'])
        self.assertFalse((self.data/'re2_coop_save_catalog.json').exists())
        self.assertEqual([p.name for p in self.solo.iterdir()],['data00-1.bin'])
        self.assertEqual(len(self.commands),2,'arming issued another native import or load')

    def test_expired_or_changed_preparation_cannot_replace_the_previous_policy(self):
        self.prepare(); self.arm(); before=self.policy.read_bytes()
        path=self.data/'re2_coop_checkpoint_workspace.json'
        saved=json.loads(path.read_bytes())
        for update in ({'at':int(self.now)-4},{'phase':'preparing'},{'request_id':'0'*32}):
            write_json(path,{**saved,**update})
            with self.assertRaises(ValueError):self.arm()
            self.assertEqual(self.policy.read_bytes(),before)
        write_json(path,saved)
        (self.workspace/'data000.bin').write_bytes(b'changed after native confirmation')
        with self.assertRaises(ValueError):self.arm()
        self.assertEqual(self.policy.read_bytes(),before)
        self.assertEqual(self.archive.verified(self.digest),self.manifest)

    def test_each_arm_rechecks_membership_cloud_peer_and_supported_probe(self):
        self.prepare();self.arm();before=self.policy.read_bytes()
        for method,value in (('membership_revision',8),('cloud_status','cloud-enabled'),('lobby_status','joined')):
            old=getattr(self.pipe,method)
            setattr(self.pipe,method,lambda:value)
            with self.assertRaises(ValueError):self.arm()
            setattr(self.pipe,method,old)
            self.assertEqual(self.policy.read_bytes(),before)
        self.guard['checkpoint_supported']=False
        with self.assertRaises(ValueError):self.arm()
        self.assertEqual(self.policy.read_bytes(),before)

    def test_reading_a_receipt_is_read_only_and_checks_the_entire_native_preparation(self):
        receipt=self.prepare()
        path=self.data/'re2_coop_checkpoint_workspace.json'
        before=path.read_bytes()
        self.assertEqual(read_prepared_checkpoint(self.data,self.pipe,self.solo,self.choice),receipt)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(len(self.commands),1)
        source=NativeSaveSource(self.data,self.solo,allow_date=None,campaign_binding=self.guard['protection'])
        selected=self.lobby['settings']['coop_checkpoint']
        self.assertEqual(source.checkpoint_receipt(selected,self.pipe),receipt)
        with self.assertRaises(ValueError):source.checkpoint_receipt({**selected,'difficulty':2},self.pipe)
        self.assertFalse(self.policy.exists())

    def test_staged_ack_needs_native_nonce_reference_and_fresh_matching_workspace(self):
        receipt=self.prepare();request=self.arm()
        policy=json.loads(self.policy.read_bytes())
        staged={'id':request,'requested_at':policy['at'],'preparation_id':receipt['request_id'],
                'checkpoint':self.choice,'reference':receipt['native_reference']}
        self.guard['staged_load']=staged
        status=self.data/'re2_coop_save_guard.json'
        write_json(status,self.guard)
        args=self.data,self.message,self.scope['role'],32,self.scope['membership']
        self.assertEqual(read_staged_load(*args),request)
        for field,value in (('preparation_id','0'*32),('reference',{**receipt['native_reference'],'timestamp':'1'})):
            self.guard['staged_load']={**staged,field:value};write_json(status,self.guard)
            self.assertIsNone(read_staged_load(*args))
        self.guard['staged_load']=staged;write_json(status,self.guard)
        path=self.data/'re2_coop_checkpoint_workspace.json'
        saved=json.loads(path.read_bytes());saved['at']=int(self.now)-4;write_json(path,saved)
        self.assertIsNone(read_staged_load(*args))

    def test_ordinary_load_and_checkpoint_attempt_cannot_be_mixed_or_downgraded(self):
        self.prepare()
        for change in ({'checkpoint_version':True},{'save_digest':'0'*64},{'campaign_start':False}):
            before=deepcopy(self.lobby['load_check']);self.lobby['load_check'].update(change);self.publish_lobby()
            with self.assertRaises(ValueError):self.arm()
            self.lobby['load_check']=before
        self.publish_lobby()
        with self.assertRaises(ValueError):
            arm(self.data,'scenario:0',None,load=True,prepared_lobby=self.solo,
                expected_game_pid=32,expected_role='H',checkpoint=self.choice)
        self.assertFalse(self.policy.exists())

    def test_existing_witnesses_accept_only_a_validated_native_slot_zero_reference(self):
        receipt=self.prepare();reference=receipt['native_reference']
        adapted=checkpoint_save_reference(reference)
        self.assertEqual({key:adapted[key] for key in reference},reference)
        for change in ({'slot_id':4},{'mode':True},{'scenario':False},{'timestamp':'0'}):
            with self.assertRaises(ValueError):checkpoint_save_reference({**reference,**change})

    def test_campaign_stage_hands_the_admitted_slot_zero_to_existing_release_and_combat(self):
        from campaign_start import campaign_stage
        self.guard['load_menu_busy']=False
        receipt=self.prepare()
        with patch('campaign_start.threading.Thread') as worker:
            worker.return_value.is_alive.return_value=False
            stage=campaign_stage(self.data,32,self.solo,None,self.stop,
                                 expected_role='H',sync_enemies=True,checkpoint_available=True)
            request=stage(checkpoint=self.choice)
            self.assertEqual(json.loads(self.policy.read_bytes())['id'],request)
            self.assertEqual(worker.call_args.kwargs['kwargs']['enemy_reference']['slot_id'],0)
            self.assertEqual(worker.call_args.kwargs['kwargs']['enemy_reference']['timestamp'],
                             receipt['native_reference']['timestamp'])
            worker.return_value.start.assert_called_once()
            self.assertEqual(len(self.commands),1,'the stage function issued another native operation')
        previous=self.policy.read_bytes()
        unsupported=campaign_stage(self.data,32,self.solo,None,self.stop,expected_role='H',sync_enemies=True)
        with self.assertRaises(ValueError):unsupported(checkpoint=self.choice)
        self.assertEqual(self.policy.read_bytes(),previous)

    def test_staging_cannot_adopt_another_attempt_or_repeat_import(self):
        receipt = self.prepare()
        for attempt, preparation in [('0'*32, receipt['request_id']), ('f'*32, '0'*32)]:
            with self.assertRaises(ValueError):
                self.arm(expected_attempt=attempt, expected_preparation=preparation)
        self.assertFalse(self.policy.exists())

    def controller(self):
        from checkpoint_start import CheckpointStartController
        self.enterContext(patch('checkpoint_start.read_active_guard', side_effect=lambda *a, **kw: deepcopy(self.guard)))
        self.guard['load_menu_busy'] = False
        self.enterContext(patch('campaign_setup._steam_for_save'))
        self.enterContext(patch('campaign_setup.storage_guard_active', return_value=True))
        self.enterContext(patch('campaign_start._confirm_loaded_campaign'))
        choice = self.lobby['settings']['coop_checkpoint']
        controller = CheckpointStartController(self.data, 32, b'H', self.stop, choice, 7,
                                               pipe_factory=lambda pid: self.pipe)
        self.addCleanup(controller.close)
        return controller

    def until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(condition())

    def test_blocked_import_never_blocks_the_lobby_and_only_real_stage_stops_refresh(self):
        from threading import Event
        entered, proceed = Event(), Event()
        def slow_import(_):
            entered.set()
            proceed.wait(2)
        self.after_import = slow_import
        controller = self.controller()
        controller.start()
        self.assertTrue(entered.wait(1))
        self.assertFalse(controller.ready)
        proceed.set()
        self.until(lambda: controller.ready)
        choice = self.lobby['settings']['coop_checkpoint']
        self.assertEqual(controller.source.resolve_checkpoint(choice), self.digest)
        with self.assertRaises(ValueError):
            controller.source.resolve_checkpoint({**choice, 'scenario': 1})
        self.assertFalse(controller.staged('0'*32))
        controller.stage('f'*32)
        controller.stage('f'*32)
        self.until(lambda: controller.request_id is not None)
        policy = json.loads(self.policy.read_bytes())
        self.assertEqual(policy['id'], controller.request_id)
        self.assertEqual(policy['schema'], 5)
        self.assertEqual(len(self.commands), 1)
        self.assertFalse(controller.staged('0'*32))
        self.until(lambda: controller.staged(controller.request_id))
        # Let the other PC take longer than a native proof's lifetime.
        for _ in range(5):
            self.now += 1
            for name in ('re2_coop_native_save_guard.json', 're2_coop_checkpoint_catalog.json'):
                path = self.data/name
                write_json(path, {**json.loads(path.read_bytes()), 'at': int(self.now)})
            path = self.data/'re2_coop_checkpoint_workspace.json'
            def refreshed():
                try:
                    return json.loads(path.read_bytes())['at'] == int(self.now)
                except PermissionError:
                    return False  # Windows can deny a reader during the atomic replacement.
            self.until(refreshed)
            self.assertTrue(controller.staged(controller.request_id))
        self.until(lambda: controller.staged(controller.request_id, releasing=True))
        self.now += 4
        self.assertFalse(controller.staged(controller.request_id, releasing=True))
        self.assertEqual(controller.request_id, policy['id'])
        self.assertEqual(len(self.commands), 1)
        controller.cancel()
        self.assertFalse(controller.ready)
        with self.assertRaises(ValueError):
            controller.source.resolve_checkpoint(choice)

    def test_failed_refresh_withdraws_readiness_permanently_without_reimport(self):
        controller = self.controller()
        controller.start()
        self.until(lambda: controller.ready)
        (self.workspace/'data000.bin').write_bytes(b'changed working checkpoint')
        self.until(lambda: controller.error is not None)
        self.assertFalse(controller.ready)
        self.assertFalse(self.policy.exists())
        self.assertEqual(len(self.commands), 1)

    def test_long_arm_renews_the_same_verified_preparation_between_native_checks(self):
        from save_protection import active_save_identity
        def check_identity(*args):
            self.now += 1.6
            self.publish_lobby()
            for name in ('re2_coop_native_save_guard.json', 're2_coop_checkpoint_catalog.json'):
                path = self.data/name
                write_json(path, {**json.loads(path.read_bytes()), 'at': int(self.now)})
            return active_save_identity(*args)
        controller = self.controller()
        controller.start()
        self.until(lambda: controller.ready)
        with patch('readonly_save_control._active_save_identity', side_effect=check_identity):
            controller.stage('f'*32)
            self.until(lambda: controller.request_id is not None or controller.error is not None)
        self.assertIsNone(controller.error)
        self.assertEqual(controller.request_id, json.loads(self.policy.read_bytes())['id'])
        self.assertEqual(len(self.commands), 1)
