from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from coop_checkpoint import FILES, HostArchive
from guest_checkpoint_archive import GuestCheckpointArchive, MAX_CHUNK_BYTES
from sync_model import state_digest


class GuestCheckpointArchiveTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.solo = self.root/'123/883710/remote/win64_save'
        self.solo.mkdir(parents=True)
        (self.solo/'data00-1.bin').write_bytes(b'guest settings without any scenario save')
        self.payload = {name: (b'native checkpoint model '+name.encode())*3000 for name in FILES}
        self.manifest = {'schema':1,'build':11636119,'namespace':'a'*32,'attempt':'b'*32,
            'release':'c'*32,'slot':0,'scenario':0,'difficulty':1,'timestamp':'639000000000000000',
            'files':{name:sha256(value).hexdigest() for name,value in self.payload.items()}}
        self.digest = state_digest(self.manifest)
        self.confirm = Mock()
        self.archive = HostArchive(self.solo,self.manifest['namespace'])

    def receiver(self, manifest=None, digest=None):
        return GuestCheckpointArchive(self.solo, manifest or self.manifest, digest or self.digest, self.confirm)

    def send(self, receiver, payload=None):
        for name,value in (payload or self.payload).items():
            for offset in range(0,len(value),MAX_CHUNK_BYTES):
                receiver.write(name,offset,value[offset:offset+MAX_CHUNK_BYTES])

    def test_receives_a_complete_generation_without_changing_guest_solo_or_workspace(self):
        workspace = self.solo.parent/('coop-save-'+'d'*32)
        workspace.mkdir();(workspace/'data000.bin').write_bytes(b'earlier working bytes')
        with self.receiver() as receiver:
            self.send(receiver)
            self.assertEqual(HostArchive.recoverable(self.solo),[])
            result = receiver.finish()
            self.assertEqual(receiver.phase,'complete')
        self.assertEqual(result,{'namespace':'a'*32,'digest':self.digest})
        self.assertEqual(self.archive.verified(self.digest),self.manifest)
        self.assertEqual([p.name for p in self.solo.iterdir()],['data00-1.bin'])
        self.assertEqual((self.solo/'data00-1.bin').read_bytes(),b'guest settings without any scenario save')
        self.assertEqual((workspace/'data000.bin').read_bytes(),b'earlier working bytes')
        self.assertEqual([p.name for p in self.archive.root.iterdir()],[self.digest])
        self.assertGreater(self.confirm.call_count,3)

    def test_partial_or_corrupt_second_generation_keeps_the_previous_checkpoint(self):
        with self.receiver() as receiver:
            self.send(receiver);receiver.finish()
        previous = self.archive.verified(self.digest)
        next_manifest={**self.manifest,'timestamp':'639000000100000000'}
        next_digest=state_digest(next_manifest)
        with self.receiver(next_manifest,next_digest) as receiver:
            receiver.write(FILES[0],0,b'unfinished')
            with self.assertRaisesRegex(ValueError,'incomplete'):receiver.finish()
        with self.receiver(next_manifest,next_digest) as receiver:
            self.send(receiver,{**self.payload,FILES[1]:b'corrupt index'})
            with self.assertRaisesRegex(ValueError,'differ'):receiver.finish()
        self.assertEqual(self.archive.verified(self.digest),previous)
        self.assertEqual([p.name for p in self.archive.root.iterdir()],[self.digest])

    def test_disconnect_before_publication_keeps_all_bytes_out_of_the_catalog(self):
        with self.receiver() as receiver:
            self.send(receiver)
            self.confirm.side_effect=ValueError('Steam selection or connection lost')
            with self.assertRaisesRegex(ValueError,'connection lost'):receiver.finish()
        self.assertEqual(HostArchive.recoverable(self.solo),[])
        self.assertEqual(list(self.archive.root.iterdir()),[])

    def test_invalid_chunks_abort_without_path_escape_or_late_restart(self):
        for name,offset,chunk in [('../escape.bin',0,b'x'),(FILES[0],True,b'x'),(FILES[0],1,b'x'),
                                   (FILES[0],0,b''),(FILES[0],0,b'x'*(MAX_CHUNK_BYTES+1))]:
            with self.subTest(name=name,offset=offset,size=len(chunk)),self.receiver() as receiver:
                with self.assertRaises(ValueError):receiver.write(name,offset,chunk)
                self.assertEqual(receiver.phase,'aborted')
                with self.assertRaises(ValueError):receiver.write(FILES[0],0,b'late')
        with patch('guest_checkpoint_archive.MAX_SAVE_BYTES',1),self.receiver() as receiver:
            with self.assertRaises(ValueError):receiver.write(FILES[0],0,b'too large')
        self.assertEqual(list(self.archive.root.iterdir()),[])
        self.assertFalse((self.root/'escape.bin').exists())

    def test_manifest_digest_and_namespace_are_checked_before_staging(self):
        for bad in ({**self.manifest,'build':1},{**self.manifest,'namespace':'../escape'},
                    {**self.manifest,'scenario':1},{**self.manifest,'files':{FILES[0]:'0'*64}}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.receiver(bad)
        self.assertFalse(self.archive.root.exists())

    def test_duplicate_generation_is_verified_without_replacing_its_files(self):
        with self.receiver() as receiver:self.send(receiver);receiver.finish()
        files=[self.archive.root/self.digest/name for name in (*FILES,'manifest.json')]
        before={p:(p.stat().st_ino,p.stat().st_mtime_ns,p.read_bytes()) for p in files}
        with self.receiver() as receiver:self.send(receiver);receiver.finish()
        self.assertEqual({p:(p.stat().st_ino,p.stat().st_mtime_ns,p.read_bytes()) for p in files},before)
        files[0].write_bytes(b'damaged existing archive')
        with self.receiver() as receiver:
            self.send(receiver)
            with self.assertRaises(ValueError):receiver.finish()
        self.assertEqual(files[0].read_bytes(),b'damaged existing archive')

    def test_input_manifest_is_frozen_and_context_exit_removes_unfinished_staging(self):
        supplied=deepcopy(self.manifest)
        with self.receiver(supplied) as receiver:
            supplied['files'][FILES[0]]='0'*64
            self.send(receiver);receiver.finish()
        self.assertEqual(self.archive.verified(self.digest),self.manifest)
        with self.receiver() as receiver:receiver.write(FILES[0],0,b'partial')
        self.assertEqual([p.name for p in self.archive.root.iterdir()],[self.digest])

    def test_renamed_archive_directory_is_not_followed(self):
        # Parent identities are checked again even when a same-named directory appears.
        with self.receiver() as receiver:
            original=receiver._parents[self.archive.root]
            with patch('guest_checkpoint_archive._directory_id',side_effect=lambda p,**kw:
                       ('changed' if p==self.archive.root else receiver._parents[p])):
                with self.assertRaisesRegex(ValueError,'directory changed'):
                    receiver.write(FILES[0],0,b'x')
            self.assertNotEqual(original,'changed')

    def test_completed_generation_is_discovered_in_another_process(self):
        with self.receiver() as receiver:self.send(receiver);receiver.finish()
        import subprocess,sys
        code='from coop_checkpoint import HostArchive;import json,sys;print(json.dumps(HostArchive.recoverable(sys.argv[1])))'
        choices=json.loads(subprocess.check_output([sys.executable,'-B','-c',code,str(self.solo)]))
        self.assertEqual([item['digest'] for item in choices],[self.digest])
