import json
from copy import deepcopy
from pathlib import Path
import shutil
import time
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from checkpoint_workspace import CheckpointWorkspace, CheckpointReadiness
from coop_checkpoint import FILES, HostArchive
from lobby_sync import write_json
from save_catalog import saved_time


class CheckpointWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(TemporaryDirectory())).resolve()
        self.solo=self.root/'123/883710/remote/win64_save'
        self.solo.mkdir(parents=True)
        (self.solo/'data00-1.bin').write_bytes(b'local original system without scenario slot')
        self.data=self.root/'bridge';self.data.mkdir()
        self.archive=HostArchive(self.solo,'a'*32)
        self.archive.source.mkdir()
        before=self.archive.before_save()
        for name in FILES: (self.archive.source/name).write_bytes(b'native model '+name.encode())
        self.digest=self.archive.publish(before,dict(attempt='a'*32,release='b'*32,slot=0,scenario=0,
            difficulty=1,timestamp='639000000000000000'),lambda:None)
        self.choice={'namespace':'a'*32,'digest':self.digest}
        self.manifest=self.archive.verified(self.digest)
        self.workspace=self.solo.parent/('coop-save-'+'b'*32);self.workspace.mkdir()
        self.stop=Event()
        self.scope={'game_pid':32,'role':'H','session_id':'d'*32,'membership':{'revision':7,'session_id':'e'*32}}
        self.lobby={'revision':2,'save_slot':None,'settings':{'coop_checkpoint':{**self.choice,'scenario':0,
            'difficulty':1,'saved_at':saved_time(self.manifest['timestamp']).isoformat(sep=' ',timespec='seconds')}}}
        self.guard={'protection':{'game_pid':32,'run_id':'c'*32,'campaign_namespace':'b'*32},'guard_run_id':'lua',
            'runtime_protection':True,'in_title':True,'has_player':False,'loading_flow':False,'busy':False,
            'allowed_load_calls':0,'denied_loads':0,'campaign_mount_ready':'b'*32,'title_open':True}
        self.after_import=lambda status:None
        self.after_catalog=lambda status:None
        self.commands=[]
        owner=self
        class Pipe:
            game_pid=32;lobby_name='fixture'
            def save_directory(self):return owner.solo
            def lobby_status(self):return 'owned'
            def membership_revision(self):return 7
            def current_campaign(self, revision):return 'b'*32
            def cloud_status(self):return 'cloud-app-disabled'
            def request(self, command, **kwargs):
                owner.commands.append(command)
                if command.startswith(b'cancel-checkpoint-import '):return b'accepted cancel-checkpoint-import'
                fields=command.decode('ascii').split()
                assert fields[:3]==['import-checkpoint','7','b'*32]
                assert fields[4:6]==['a'*32,owner.digest]
                for name in FILES:shutil.copyfile(owner.archive.root/owner.digest/name,owner.workspace/name)
                status={'workspace':'b'*32,'request_id':fields[3],'archive_namespace':'a'*32,
                    'generation':owner.digest,'phase':'ready','file_index':3,'native_result':1}
                owner.after_import(status)
                write_json(owner.data/'re2_coop_native_save_guard.json',{'checkpoint_import':status,
                    'schema':1,'at':int(time.time()),'source':'steam_storage_guard','active':True,'reason':'ok',
                    'app_id':883710,'build_id':11636119,'interface':'014','guarded_methods':10,
                    'game_pid':32,'run_id':'c'*32,'campaign_namespace':'b'*32})
                catalog={'schema':1,'at':int(time.time()),'request_id':fields[3],'workspace':'b'*32,
                    'archive_namespace':'a'*32,'generation':owner.digest,'phase':'ready','game_pid':32,
                    'run_id':'c'*32,'guard_run_id':'lua',
                    'reference':{'mode':1,'slot_id':0,'timestamp':'639001000000000000','scenario':0}}
                owner.after_catalog(catalog)
                write_json(owner.data/'re2_coop_checkpoint_catalog.json',catalog)
                return b'accepted import-checkpoint'
        self.pipe=Pipe()
        self.enterContext(patch('checkpoint_workspace.read_active_guard',side_effect=lambda *a,**kw:deepcopy(self.guard)))
        self.enterContext(patch('checkpoint_workspace.read_connected_lobby',side_effect=lambda data:(deepcopy(self.scope),deepcopy(self.lobby))))
        self.enterContext(patch('checkpoint_workspace.storage_guard_active',return_value=True))

    def prepare(self):return CheckpointWorkspace(self.data,self.pipe,self.solo,self.choice,self.stop).prepare(timeout=1)

    def test_prepares_another_workspace_without_any_local_scenario_save(self):
        result=self.prepare()
        self.assertEqual(result['selection'],self.choice)
        self.assertEqual(result['protection']['campaign_namespace'],'b'*32)
        self.assertNotEqual(result['native_reference']['timestamp'], self.manifest['timestamp'])
        self.assertEqual(json.loads((self.data/'re2_coop_checkpoint_workspace.json').read_text())['phase'],'ready')
        self.assertFalse((self.data/'re2_coop_save_policy.json').exists())
        self.assertEqual(list(p.name for p in self.solo.iterdir()),['data00-1.bin'])
        self.assertEqual((self.solo/'data00-1.bin').read_bytes(),b'local original system without scenario slot')
        self.assertEqual(self.archive.verified(self.digest),self.manifest)

    def test_rejects_changed_selection_or_world_before_submitting(self):
        for key,value in [('in_title',False),('has_player',True),('busy',True),('allowed_load_calls',False)]:
            with self.subTest(key=key):
                old=self.guard[key];self.guard[key]=value
                with self.assertRaises(ValueError):self.prepare()
                self.guard[key]=old
        self.assertEqual(self.commands,[])

    def test_failed_or_incomplete_native_receipt_is_never_ready(self):
        for change in ({'phase':'failed','error':'steam_checkpoint_write_failed'}, {'file_index':2},
                       {'native_result':True},{'workspace':'d'*32}):
            with self.subTest(change=change):
                self.after_import=lambda status:status.update(change)
                with self.assertRaises(ValueError):self.prepare()
                self.assertTrue(self.commands[-1].startswith(b'cancel-checkpoint-import '))
                self.assertEqual(json.loads((self.data/'re2_coop_checkpoint_workspace.json').read_text())['phase'],'failed')
                self.assertEqual(self.archive.verified(self.digest),self.manifest)

    def test_corrupted_destination_or_changed_lobby_cannot_finish(self):
        def corrupt(status):(self.workspace/FILES[0]).write_bytes(b'wrong bytes')
        def change(status):self.lobby['revision']+=1
        for action in (corrupt,change):
            self.after_import=action
            with self.assertRaises(ValueError):self.prepare()
            self.assertEqual(json.loads((self.data/'re2_coop_checkpoint_workspace.json').read_text())['phase'],'failed')
        self.assertEqual(self.archive.verified(self.digest),self.manifest)

    def test_cancelled_preparation_keeps_immutable_checkpoint(self):
        self.after_import=lambda status:self.stop.set()
        with self.assertRaisesRegex(ValueError,'cancelled'):self.prepare()
        self.assertEqual(self.archive.verified(self.digest),self.manifest)
        self.assertFalse((self.data/'re2_coop_save_policy.json').exists())

    def test_catalog_needs_fresh_matching_scope_and_native_reference(self):
        for change in ({'phase':'failed','reason':'checkpoint_catalog_timeout'},{'at':0},{'run_id':'d'*32},
                       {'reference':{'mode':1,'slot_id':0,'timestamp':'639001000000000000','scenario':1}},
                       {'reference':{'mode':True,'slot_id':0,'timestamp':'639001000000000000','scenario':0}}):
            with self.subTest(change=change):
                self.after_catalog=lambda status:status.update(change)
                with self.assertRaises(ValueError):self.prepare()
                self.assertEqual(json.loads((self.data/'re2_coop_checkpoint_workspace.json').read_text())['phase'],'failed')
        self.assertFalse((self.data/'re2_coop_save_policy.json').exists())

    def test_waits_for_the_first_catalog_export_after_native_import(self):
        from load_witness import _read_json
        seen=[]
        def delayed(path):
            if path.name=='re2_coop_checkpoint_catalog.json':
                seen.append(path)
                if len(seen)==1:raise FileNotFoundError(path)
            return _read_json(path)
        with patch('checkpoint_workspace._read_json',side_effect=delayed):
            self.assertEqual(self.prepare()['native_reference']['scenario'],0)
        self.assertGreater(len(seen),1)

    def readiness(self):
        receipt=self.prepare()
        self.wall=float(int(time.time()))+.1
        self.mono=1000.
        self.enterContext(patch('checkpoint_workspace.time.time',side_effect=lambda:self.wall))
        self.enterContext(patch('checkpoint_workspace.time.monotonic',side_effect=lambda:self.mono))
        return receipt,CheckpointReadiness(self.data,self.pipe,self.solo,receipt,self.stop)

    def fresh_native_reports(self):
        for name in ('re2_coop_native_save_guard.json','re2_coop_checkpoint_catalog.json'):
            path=self.data/name
            value=json.loads(path.read_text());value['at']=int(self.wall)
            write_json(path,value)

    def test_readiness_waits_for_a_peer_without_importing_again_or_changing_inputs(self):
        receipt,ready=self.readiness()
        before={name:(self.workspace/name).read_bytes() for name in FILES}
        for _ in range(35):
            self.wall+=1;self.mono+=1;self.fresh_native_reports()
            self.assertEqual(ready.refresh(),receipt)
        published=json.loads(ready.path.read_text())
        self.assertEqual(published['phase'],'ready')
        self.assertEqual(published['request_id'],receipt['request_id'])
        self.assertEqual(published['at'],int(self.wall))
        self.assertEqual({name:(self.workspace/name).read_bytes() for name in FILES},before)
        self.assertEqual(self.archive.verified(self.digest),self.manifest)
        self.assertEqual(len(self.commands),1)
        self.assertFalse((self.data/'re2_coop_save_policy.json').exists())

    def test_expired_readiness_cannot_be_revived_by_fresh_native_reports(self):
        receipt,ready=self.readiness()
        self.wall+=4;self.mono+=4;self.fresh_native_reports()
        with self.assertRaisesRegex(ValueError,'expired'):ready.refresh()
        self.assertEqual(json.loads(ready.path.read_text())['phase'],'failed')
        with self.assertRaisesRegex(ValueError,'permanently lost'):ready.refresh()
        with self.assertRaisesRegex(ValueError,'expired or replaced'):
            CheckpointReadiness(self.data,self.pipe,self.solo,receipt,self.stop)
        self.assertEqual(len(self.commands),1)

    def test_replaced_readiness_is_never_overwritten_by_the_old_owner(self):
        _,ready=self.readiness()
        replacement={**ready.record,'request_id':'f'*32,'phase':'preparing'}
        write_json(ready.path,replacement)
        with self.assertRaisesRegex(ValueError,'replaced'):ready.refresh()
        self.assertEqual(json.loads(ready.path.read_text()),replacement)
        self.assertEqual(ready.state,'lost')

    def test_changed_working_bytes_revoke_readiness_but_preserve_the_archive(self):
        _,ready=self.readiness()
        (self.workspace/FILES[0]).write_bytes(b'changed after preparation')
        with self.assertRaisesRegex(ValueError,'working files changed'):ready.refresh()
        self.assertEqual(json.loads(ready.path.read_text())['phase'],'failed')
        self.assertEqual(self.archive.verified(self.digest),self.manifest)
        self.assertEqual(len(self.commands),1)

    def test_readiness_rechecks_native_completion_and_catalog_each_time(self):
        _,ready=self.readiness()
        for name,change in (
                ('re2_coop_native_save_guard.json',lambda v:v.update(at=int(self.wall)-4)),
                ('re2_coop_native_save_guard.json',lambda v:v['checkpoint_import'].update(native_result=2)),
                ('re2_coop_checkpoint_catalog.json',lambda v:v['reference'].update(timestamp='639002000000000000'))):
            if ready.state!='ready':
                receipt=self.prepare();ready=CheckpointReadiness(self.data,self.pipe,self.solo,receipt,self.stop)
            path=self.data/name;value=json.loads(path.read_text());change(value);write_json(path,value)
            with self.assertRaises(ValueError):ready.refresh()
            self.assertEqual(json.loads(ready.path.read_text())['phase'],'failed')

    def test_readiness_cannot_survive_lobby_or_lua_guard_loss(self):
        _,ready=self.readiness()
        for change in (lambda:self.lobby.update(revision=3),lambda:self.guard.update(guard_run_id='another vm'),
                       lambda:self.guard['protection'].update(run_id='f'*32)):
            old_lobby,old_guard=deepcopy((self.lobby,self.guard))
            if ready.state!='ready':
                receipt=self.prepare();ready=CheckpointReadiness(self.data,self.pipe,self.solo,receipt,self.stop)
            change()
            with self.assertRaises(ValueError):ready.refresh()
            self.assertEqual(json.loads(ready.path.read_text())['phase'],'failed')
            self.lobby,self.guard=old_lobby,old_guard

    def test_clock_rollback_closes_readiness(self):
        _,ready=self.readiness()
        self.wall-=.01
        with self.assertRaisesRegex(ValueError,'clock changed'):ready.refresh()
        self.assertEqual(ready.state,'lost')

    def test_slow_validation_cannot_extend_an_expired_preparation(self):
        import checkpoint_workspace
        _,ready=self.readiness()
        original=checkpoint_workspace._hashes
        def delayed(*args):
            result=original(*args);self.wall+=4;self.mono+=4;return result
        with patch('checkpoint_workspace._hashes',side_effect=delayed):
            with self.assertRaises(ValueError):ready.refresh()
        self.assertEqual(json.loads(ready.path.read_text())['phase'],'failed')
        self.assertEqual(ready.state,'lost')
