"""Move immutable native checkpoint files over the existing authenticated snapshot lane.

The caller authenticates the selected Steam peer and keeps its lobby/game binding
current through confirm(). This optional transfer never grants a native load.
"""
import base64
from contextlib import ExitStack
from copy import deepcopy
import math
import os
from pathlib import Path
from hashlib import sha256
import time

from campaign_save_copy import _directory_id, _file_signature
from coop_checkpoint import DIGEST, FILES, HostArchive, _signatures, _token, _validate
from guest_checkpoint_archive import GuestCheckpointArchive, MAX_CHUNK_BYTES
from load_preflight import MAX_SAVE_BYTES
from pose_bridge import lock_data_directory
from steam_snapshot_transfer import transfer
from steam_pose_bridge import SteamPipe
from sync_model import Replica, state_digest


PROFILE = 'native_checkpoint_archive_v1'
BLOCK_BYTES = MAX_CHUNK_BYTES


def _selection(value):
    if (not isinstance(value, dict) or set(value) != {'namespace','digest'} or not _token(value['namespace'])
            or not isinstance(value['digest'],str) or not DIGEST.fullmatch(value['digest'])):
        raise ValueError('Invalid selected checkpoint transfer')
    return dict(value)


class _Exchange:
    def __init__(self, transport, role, session, request, selection, confirm, stop, timeout):
        if (not _token(session) or not _token(request) or not callable(confirm)
                or type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 300):
            raise ValueError('Invalid checkpoint transfer scope or timeout')
        if not isinstance(transport,SteamPipe) or transport.name!=rf'\\.\pipe\re2-coop-steam-snapshot-{transport.game_pid}':
            raise ValueError('Checkpoint archive transfer requires the dedicated snapshot pipe')
        self.transport,self.role,self.session,self.request = transport,role,session,request
        self.selection,self.confirm,self.stop = _selection(selection),confirm,stop
        self.deadline,self.epoch = time.monotonic()+timeout,None
        self.seed = PROFILE.encode('ascii')+bytes.fromhex(session+request+self.selection['digest'])

    def check(self, *, require_link=True):
        if self.stop is not None and self.stop.is_set():
            raise ValueError('Checkpoint transfer cancelled')
        if time.monotonic() >= self.deadline:
            raise TimeoutError('Checkpoint transfer expired')
        self.confirm()
        if require_link or self.epoch is not None:
            epoch = self.transport.epoch
            if self.transport.role != self.role or not isinstance(epoch,bytes) or len(epoch)!=8:
                raise OSError('Checkpoint transfer has no matching native Steam peer')
            if self.epoch is None:
                self.epoch=epoch
            elif self.epoch!=epoch:
                raise OSError('Native Steam peer changed during checkpoint transfer')

    def frame(self, step, kind, **payload):
        replica=Replica(session_id=self.session,sequence=step)
        replica.state['flags'][PROFILE]={'profile':PROFILE,'selection':self.selection,'step':step,'kind':kind,**payload}
        return replica.snapshot()

    def payload(self, snapshot, step, kind, fields):
        self.check()
        state=snapshot['state']
        if (snapshot['session_id']!=self.session or type(snapshot['sequence']) is not int or snapshot['sequence']!=step
                or set(state['flags'])!={PROFILE} or state['cutscene'] is not None
                or any(value for key,value in state.items() if key not in ('flags','cutscene'))):
            raise ValueError('Unexpected checkpoint snapshot contents')
        value=state['flags'][PROFILE]
        if (not isinstance(value,dict) or set(value)!={'profile','selection','step','kind',*fields}
                or value['profile']!=PROFILE or value['selection']!=self.selection
                or type(value['step']) is not int or value['step']!=step or value['kind']!=kind):
            raise ValueError('Checkpoint transfer phase or selection changed')
        return value

    def segment(self, step, *, capture=None, verify=None):
        self.check(require_link=False)
        request=sha256(self.seed+step.to_bytes(4,'big')).digest()[:16].hex()
        def guarded_capture():
            self.check()
            snapshot=capture()
            self.check()
            return snapshot
        def guarded_verify(snapshot):
            self.check()
            verify(snapshot)
            self.check()
        transfer(self.transport,self.role,self.session,request,
                 capture=guarded_capture if capture else None,verify=guarded_verify if verify else None,
                 expected_epoch=self.epoch,timeout=min(30,self.deadline-time.monotonic()),
                 on_idle=self.check,stop=self.stop)
        self.check()


class _Source:
    def __init__(self, stack, archive, digest):
        self.archive,self.digest=archive,digest
        self.manifest=deepcopy(archive.verified(digest))
        self.directory=archive.root/digest
        self.parents={p:_directory_id(p) for p in (archive.root.parent,archive.root,self.directory)}
        self.signatures=_signatures(self.directory)
        self.sizes={name:self.signatures[name][1] for name in FILES}
        self.streams={name:stack.enter_context((self.directory/name).open('rb')) for name in FILES}
        self.check()

    def check(self):
        if (any(_directory_id(p)!=identity for p,identity in self.parents.items())
                or any(_file_signature(os.fstat(f.fileno()))!=self.signatures[name] for name,f in self.streams.items())
                or _signatures(self.directory)!=self.signatures):
            raise ValueError('Selected checkpoint source changed during transfer')

    def block(self, name, offset, size):
        self.check()
        stream=self.streams[name]
        stream.seek(offset)
        chunk=stream.read(size)
        self.check()
        if len(chunk)!=size:
            raise ValueError('Checkpoint source read was incomplete')
        return base64.b64encode(chunk).decode('ascii')

    def finish(self):
        self.check()
        if self.archive.verified(self.digest)!=self.manifest:
            raise ValueError('Checkpoint manifest changed during transfer')


def send_archive(data, transport, session_id, request_id, archive, digest, confirm, *, stop=None, timeout=120):
    """Serve one selected archive; success means the guest verified and published it."""
    if not isinstance(archive,HostArchive):
        raise ValueError('A verified local host archive is required')
    exchange=_Exchange(transport,b'H',session_id,request_id,{'namespace':archive.namespace,'digest':digest},confirm,stop,timeout)
    with lock_data_directory(Path(data),stream='snapshot'),ExitStack() as stack:
        exchange.check(require_link=False)
        source=_Source(stack,archive,digest)
        exchange.segment(0,capture=lambda: exchange.frame(0,'manifest',manifest=source.manifest,sizes=source.sizes))
        step=1
        for name in FILES:
            for offset in range(0,source.sizes[name],BLOCK_BYTES):
                def capture(name=name,offset=offset,step=step):
                    encoded=source.block(name,offset,min(BLOCK_BYTES,source.sizes[name]-offset))
                    return exchange.frame(step,'chunk',file=name,offset=offset,data=encoded)
                exchange.segment(step,capture=capture)
                step+=1
        def commit():
            source.finish()
            exchange.check()
            return exchange.frame(step,'commit')
        exchange.segment(step,capture=commit)
        source.finish()
        exchange.check()
        return dict(exchange.selection)


def receive_archive(data, transport, session_id, request_id, solo, selection, confirm, *, stop=None, timeout=120):
    """Stage a selected generation on the guest, keeping its solo and working saves intact."""
    exchange=_Exchange(transport,b'G',session_id,request_id,selection,confirm,stop,timeout)
    with lock_data_directory(Path(data),stream='snapshot'),ExitStack() as stack:
        receiver,sizes=None,None
        def manifest(snapshot):
            nonlocal receiver,sizes
            value=exchange.payload(snapshot,0,'manifest',{'manifest','sizes'})
            selected=deepcopy(value['manifest'])
            _validate(selected)
            if selected['namespace']!=exchange.selection['namespace'] or state_digest(selected)!=exchange.selection['digest']:
                raise ValueError('Host manifest differs from the selected checkpoint')
            sizes=value['sizes']
            if (not isinstance(sizes,dict) or set(sizes)!=set(FILES)
                    or any(type(size) is not int or not 0<size<=MAX_SAVE_BYTES for size in sizes.values())):
                raise ValueError('Unsupported checkpoint transfer file sizes')
            receiver=stack.enter_context(GuestCheckpointArchive(solo,selected,exchange.selection['digest'],exchange.check))
        exchange.segment(0,verify=manifest)
        step=1
        for name in FILES:
            for offset in range(0,sizes[name],BLOCK_BYTES):
                def chunk(snapshot,name=name,offset=offset,step=step):
                    value=exchange.payload(snapshot,step,'chunk',{'file','offset','data'})
                    encoded=value['data']
                    if (value['file']!=name or type(value['offset']) is not int or value['offset']!=offset
                            or not isinstance(encoded,str) or not 0<len(encoded)<=4*((BLOCK_BYTES+2)//3)):
                        raise ValueError('Invalid checkpoint transfer block')
                    contents=base64.b64decode(encoded,validate=True)
                    if (len(contents)!=min(BLOCK_BYTES,sizes[name]-offset)
                            or base64.b64encode(contents).decode('ascii')!=encoded):
                        raise ValueError('Checkpoint block length or encoding changed')
                    receiver.write(name,offset,contents)
                exchange.segment(step,verify=chunk)
                step+=1
        result=None
        def commit(snapshot):
            nonlocal result
            exchange.payload(snapshot,step,'commit',set())
            result=receiver.finish()
        exchange.segment(step,verify=commit)
        return result
