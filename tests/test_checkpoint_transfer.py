import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock,patch

import checkpoint_transfer as archive_transfer
from coop_checkpoint import FILES,HostArchive
from guest_checkpoint_archive import GuestCheckpointArchive
from pose_bridge import lock_data_directory
from protocol.snapshot_transfer import MAX_PACKET_BYTES,snapshot_packets
from steam_pose_bridge import SteamPipe
from sync_model import state_digest
from tests.test_steam_snapshot_transfer import NativePipePair,EPOCH,SESSION,REQUEST


class CheckpointTransferTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(TemporaryDirectory())).resolve()
        self.host_data,self.guest_data=self.root/'host-bridge',self.root/'guest-bridge'
        self.host_data.mkdir();self.guest_data.mkdir()
        host_solo=self.root/'123/883710/remote/win64_save';host_solo.mkdir(parents=True)
        self.guest_solo=self.root/'456/883710/remote/win64_save';self.guest_solo.mkdir(parents=True)
        (self.guest_solo/'data00-1.bin').write_bytes(b'guest system without scenario saves')
        self.payload={FILES[0]:bytes(range(256))*5000,FILES[1]:b'index'*48,FILES[2]:b'profile'*1080}
        self.host=HostArchive(host_solo,'a'*32);self.host.source.mkdir()
        before=self.host.before_save()
        for name,value in self.payload.items():(self.host.source/name).write_bytes(value)
        receipt={'attempt':'b'*32,'release':'c'*32,'slot':0,'scenario':0,'difficulty':1,'timestamp':'639000000100000000'}
        self.digest=self.host.publish(before,receipt,lambda:None)
        self.selection={'namespace':self.host.namespace,'digest':self.digest}
        previous={**self.host.verified(self.digest),'timestamp':'639000000000000000'}
        self.previous=state_digest(previous)
        with GuestCheckpointArchive(self.guest_solo,previous,self.previous,lambda:None) as receiver:
            for name,value in self.payload.items():
                for offset in range(0,len(value),archive_transfer.BLOCK_BYTES):
                    receiver.write(name,offset,value[offset:offset+archive_transfer.BLOCK_BYTES])
            receiver.finish()
        self.guest_archive=HostArchive(self.guest_solo,self.host.namespace)
        self.guest_work=self.guest_solo.parent/('coop-save-'+'d'*32)
        self.guest_work.mkdir();(self.guest_work/FILES[0]).write_bytes(b'prior working bytes')
        self.pair=NativePipePair();self.stop=Event()
        self.host_pipe,self.guest_pipe=self.pipe(b'H'),self.pipe(b'G')
        self.confirm_host,self.confirm_guest=Mock(),Mock()

    def pipe(self,role):
        pipe=self.pair.pipe(role)
        pipe.name=rf'\\.\pipe\re2-coop-steam-snapshot-{pipe.game_pid}'
        return pipe

    def run_pair(self, *, expect_error=False, timeout=8):
        def guarded(fn,*args):
            try:return fn(*args,stop=self.stop,timeout=timeout)
            except BaseException:
                self.stop.set()
                raise
        with ThreadPoolExecutor(max_workers=2) as executor:
            host=executor.submit(guarded,archive_transfer.send_archive,self.host_data,self.host_pipe,SESSION,REQUEST,
                self.host,self.digest,self.confirm_host)
            guest=executor.submit(guarded,archive_transfer.receive_archive,self.guest_data,self.guest_pipe,SESSION,REQUEST,
                self.guest_solo,self.selection,self.confirm_guest)
            results=[]
            for future in (host,guest):
                try:results.append(future.result(timeout=12))
                except (ValueError,OSError,TimeoutError) as exc:results.append(exc)
        if expect_error:
            self.assertTrue(any(isinstance(x,Exception) for x in results),results)
        else:self.assertEqual(results,[self.selection,self.selection])
        return results

    def assert_guest_preserved(self, *, transferred=False):
        expected={self.previous,self.digest} if transferred else {self.previous}
        self.assertEqual({p.name for p in self.guest_archive.root.iterdir()},expected)
        self.guest_archive.verified(self.previous)
        self.assertEqual([p.name for p in self.guest_solo.iterdir()],['data00-1.bin'])
        self.assertEqual((self.guest_solo/'data00-1.bin').read_bytes(),b'guest system without scenario saves')
        self.assertEqual((self.guest_work/FILES[0]).read_bytes(),b'prior working bytes')

    def altered_frame(self, mutate):
        original=archive_transfer._Exchange.frame
        def changed(exchange,step,kind,**payload):
            snapshot=original(exchange,step,kind,**payload)
            mutate(snapshot['state']['flags'][archive_transfer.PROFILE])
            snapshot['digest']=state_digest(snapshot['state'])
            return snapshot
        return patch.object(archive_transfer._Exchange,'frame',changed)

    def test_transfers_more_than_one_mib_using_existing_bounded_snapshot_packets(self):
        self.run_pair()
        self.assert_guest_preserved(transferred=True)
        self.assertEqual(self.guest_archive.verified(self.digest),self.host.verified(self.digest))
        for name,value in self.payload.items():self.assertEqual((self.guest_archive.root/self.digest/name).read_bytes(),value)
        self.assertGreater(len(self.pair.sent_by_host),300)
        self.assertTrue(all(p.startswith(b'R2S\x01') and len(p)<=MAX_PACKET_BYTES for p in self.pair.sent_by_host))
        self.assertLessEqual(self.pair.peak_guest_pending,8)

    def test_corrupt_native_bytes_never_publish_the_selected_generation(self):
        def corrupt(value):
            if value['kind']=='chunk' and value['file']==FILES[0] and value['offset']==0:
                data=base64.b64decode(value['data']);value['data']=base64.b64encode(b'x'*len(data)).decode('ascii')
        with self.altered_frame(corrupt):self.run_pair(expect_error=True)
        self.assert_guest_preserved()

    def test_file_sizes_and_block_paths_are_rejected_before_publication(self):
        for mutate in (lambda v:v['sizes'].update({FILES[0]:33*1024*1024}) if v['kind']=='manifest' else None,
                       lambda v:v.update(file='../escape.bin') if v['kind']=='chunk' else None,
                       lambda v:v.update(data='not base64!') if v['kind']=='chunk' else None):
            self.stop.clear();self.pair=NativePipePair();self.host_pipe,self.guest_pipe=self.pipe(b'H'),self.pipe(b'G')
            with self.altered_frame(mutate):self.run_pair(expect_error=True)
            self.assert_guest_preserved()
        self.assertFalse((self.root/'escape.bin').exists())

    def test_changed_selection_cancels_both_roles_and_keeps_the_old_generation(self):
        def lose_selection(value):
            if value['kind']=='chunk':self.confirm_host.side_effect=ValueError('selection changed')
        with self.altered_frame(lose_selection):self.run_pair(expect_error=True)
        self.assert_guest_preserved()

    def test_native_epoch_change_aborts_before_receiving_native_file_bytes(self):
        changed=Event();original=self.guest_pipe.request
        def request(data):
            result=original(data)
            if data==b'R' and changed.is_set():return result[:1]+b'epoch-02'+result[9:]
            return result
        self.guest_pipe.request=request
        with self.altered_frame(lambda v:changed.set() if v['kind']=='chunk' else None):
            self.run_pair(expect_error=True)
        self.assert_guest_preserved()

    def test_source_mutation_cannot_be_announced_as_a_complete_transfer(self):
        original=archive_transfer._Source.block
        def change(source,*args):
            data=original(source,*args)
            (source.directory/FILES[1]).write_bytes(b'changed source')
            return data
        with patch.object(archive_transfer._Source,'block',change):self.run_pair(expect_error=True)
        self.assert_guest_preserved()

    def test_uses_exclusive_snapshot_lock_and_rejects_pose_endpoints(self):
        with lock_data_directory(self.host_data,stream='snapshot'):
            with self.assertRaisesRegex(ValueError,'snapshot bridge is already running'):
                archive_transfer.send_archive(self.host_data,self.host_pipe,SESSION,REQUEST,self.host,self.digest,self.confirm_host)
        with self.assertRaisesRegex(ValueError,'dedicated snapshot pipe'):
            archive_transfer.send_archive(self.host_data,SteamPipe(123),SESSION,REQUEST,self.host,self.digest,self.confirm_host)
        self.assert_guest_preserved()

    def test_timeout_and_cancel_release_staging_and_do_not_publish(self):
        pipe=SteamPipe(123,stream='snapshot');pipe.request=Mock(side_effect=lambda data:b'G'+EPOCH if data==b'R' else b'S')
        with self.assertRaises(TimeoutError):
            archive_transfer.receive_archive(self.guest_data,pipe,SESSION,REQUEST,self.guest_solo,self.selection,
                self.confirm_guest,timeout=.05)
        with self.altered_frame(lambda v:self.stop.set() if v['kind']=='chunk' else None):
            self.run_pair(expect_error=True)
        self.assert_guest_preserved()

    def test_frames_from_an_older_transfer_cannot_replace_the_current_manifest(self):
        exchange=archive_transfer._Exchange(self.host_pipe,b'H',SESSION,'f'*32,self.selection,lambda:None,None,10)
        snapshot=exchange.frame(0,'manifest',manifest={},sizes={})
        old_request=archive_transfer.sha256(exchange.seed+(0).to_bytes(4,'big')).digest()[:16].hex()
        for packet in snapshot_packets(snapshot,old_request):self.pair.to_guest.put_nowait(packet)
        self.run_pair();self.assert_guest_preserved(transferred=True)
