"""Stage received native checkpoint bytes outside the guest's Steam remote tree.

This is a local sink, not a Steam protocol or a load permission. The caller owns
peer authentication and must raise from confirm() when its selected generation,
connection or game binding is lost.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from campaign_save_copy import _directory_id
from coop_checkpoint import DIGEST, FILES, HostArchive, _hashes, _signatures, _validate
from load_preflight import MAX_SAVE_BYTES
from sync_model import state_digest


MAX_CHUNK_BYTES = 64 * 1024


class GuestCheckpointArchive:
    """Receive the three fixed files, then publish their intact immutable generation."""

    def __init__(self, solo, manifest, digest, confirm):
        manifest = deepcopy(manifest)
        _validate(manifest)
        if (not isinstance(digest, str) or not DIGEST.fullmatch(digest)
                or state_digest(manifest) != digest or not callable(confirm)):
            raise ValueError('Invalid received checkpoint selection')
        self.archive = HostArchive(Path(solo), manifest['namespace'])
        self.manifest, self.digest, self.confirm = manifest, digest, confirm
        self.phase = 'receiving'
        self._temporary, self._streams, self._offsets = None, {}, dict.fromkeys(FILES, 0)
        confirm()
        for parent in (self.archive.root.parent, self.archive.root):
            parent.mkdir(exist_ok=True)
            _directory_id(parent)
        self._parents = {parent: _directory_id(parent) for parent in
                         (self.archive.root.parent.parent, self.archive.root.parent, self.archive.root)}
        try:
            self._temporary = TemporaryDirectory(prefix='.pending-receive-', dir=self.archive.root)
            self._generation = Path(self._temporary.name)/'generation'
            self._generation.mkdir()
            self._parents[self._generation] = _directory_id(self._generation)
            for name in FILES:
                self._streams[name] = (self._generation/name).open('xb')
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _current(self):
        if self.phase != 'receiving':
            raise ValueError('Checkpoint receiver is already closed')
        self.confirm()
        if any(_directory_id(parent) != identity for parent, identity in self._parents.items()):
            raise ValueError('Checkpoint archive directory changed during reception')

    def write(self, name, offset, chunk):
        """Append one ordered bounded chunk; packet deduplication belongs to the transport."""
        try:
            self._current()
            if (not isinstance(name, str) or name not in FILES or type(offset) is not int
                    or offset != self._offsets[name] or not isinstance(chunk, bytes)
                    or not 0 < len(chunk) <= MAX_CHUNK_BYTES or offset+len(chunk) > MAX_SAVE_BYTES):
                raise ValueError('Invalid received checkpoint file chunk')
            stream = self._streams[name]
            if stream.write(chunk) != len(chunk):
                raise OSError('Incomplete checkpoint staging write')
            self._offsets[name] += len(chunk)
        except BaseException:
            self.close()
            raise

    def finish(self):
        """Return the selection only after bytes, manifest and final binding all agree."""
        try:
            self._current()
            if not all(self._offsets.values()):
                raise ValueError('Received checkpoint files are incomplete')
            for stream in self._streams.values():
                stream.flush()
                os.fsync(stream.fileno())
            self._close_streams()
            signatures = _signatures(self._generation)
            if _hashes(self._generation, signatures) != self.manifest['files']:
                raise ValueError('Received checkpoint bytes differ from the selected manifest')
            with (self._generation/'manifest.json').open('x', encoding='utf-8') as stream:
                json.dump(self.manifest, stream)
                stream.flush()
                os.fsync(stream.fileno())
            self._current()
            if _signatures(self._generation) != signatures:
                raise ValueError('Received checkpoint changed during confirmation')
            target = self.archive.root/self.digest
            if _directory_id(target, missing_ok=True) is not None:
                self.archive.verified(self.digest)
            else:
                try:
                    self._generation.rename(target)
                except OSError:
                    # Another receiver may have published the identical generation.
                    # Verification never repairs or overwrites an existing generation.
                    self.archive.verified(self.digest)
            self.archive.verified(self.digest)
            self.phase = 'complete'
            return {'namespace': self.manifest['namespace'], 'digest': self.digest}
        finally:
            self.close()

    def _close_streams(self):
        streams, self._streams = self._streams, {}
        try:
            for stream in streams.values():
                stream.close()
        finally:
            for stream in streams.values():
                if not stream.closed:
                    stream.close()

    def close(self):
        if self.phase == 'receiving':
            self.phase = 'aborted'
        try:
            self._close_streams()
        finally:
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None
