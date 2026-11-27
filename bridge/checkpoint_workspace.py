"""Prepare immutable native checkpoint bytes through RE2's existing guarded writer.

This is an internal preparation component. Its receipt does not authorize a game load.
"""
from copy import deepcopy
from pathlib import Path
import secrets
import time

from campaign_save_copy import _directory_id
from coop_checkpoint import DIGEST, FILES, HostArchive, _hashes, _signatures, _token
from load_witness import _read_json
from lobby_sync import write_json
from pose_bridge import lock_data_directory
from readonly_save_control import read_active_guard, read_connected_lobby
from save_catalog import saved_time
from save_protection import active_save_identity, storage_guard_active


def selected_archive(solo, selection):
    """Verify the immutable generation and derive its complete lobby choice."""
    if (not isinstance(selection, dict) or set(selection) != {'namespace', 'digest'}
            or not _token(selection['namespace']) or not isinstance(selection['digest'], str)
            or not DIGEST.fullmatch(selection['digest'])):
        raise ValueError('Invalid checkpoint selection')
    archive = HostArchive(Path(solo), selection['namespace'])
    manifest = archive.verified(selection['digest'])
    choice = {**selection, 'scenario': manifest['scenario'], 'difficulty': manifest['difficulty'],
              'saved_at': saved_time(manifest['timestamp']).isoformat(sep=' ', timespec='seconds')}
    return archive, manifest, choice


class CheckpointWorkspace:
    def __init__(self, data, pipe, solo, selection, stop):
        self.archive, self.manifest, self.expected_choice = selected_archive(solo, selection)
        self.data, self.pipe, self.solo, self.stop = Path(data), pipe, Path(solo), stop
        self.selection = dict(selection)
        self.scope, lobby = read_connected_lobby(self.data)
        self.lobby_revision = lobby['revision']
        guard = read_active_guard(self.data, protected=True, runtime_directory=self.solo)
        self.binding = deepcopy(guard['protection'])
        self.guard_run = guard.get('guard_run_id')
        namespace = self.binding.get('campaign_namespace')
        if not _token(namespace) or not isinstance(self.guard_run, str) or not self.guard_run:
            raise ValueError('A current native campaign mount is required')
        self.target = self.solo.parent / ('coop-save-' + namespace)
        self.target_identity = _directory_id(self.target)
        self.solo_identity = active_save_identity(pipe, self.solo)
        self.check()

    def check(self):
        if self.stop.is_set():
            raise ValueError('Checkpoint preparation cancelled')
        guard = read_active_guard(self.data, protected=True, runtime_directory=self.solo)
        scope, lobby = read_connected_lobby(self.data)
        if (scope != self.scope or lobby['revision'] != self.lobby_revision
                or lobby['settings'].get('coop_checkpoint') != self.expected_choice
                or lobby['save_slot'] is not None or 'new_game' in lobby
                or guard.get('protection') != self.binding or guard.get('guard_run_id') != self.guard_run
                or self.pipe.game_pid != self.binding['game_pid'] or scope['game_pid'] != self.pipe.game_pid
                or guard.get('runtime_protection') is not True or guard.get('in_title') is not True
                or guard.get('has_player') is not False or guard.get('loading_flow') is not False
                or guard.get('busy') is not False or type(guard.get('denied_loads')) is not int or guard['denied_loads'] != 0
                or type(guard.get('allowed_load_calls')) is not int or guard['allowed_load_calls'] != 0
                or guard.get('campaign_mount_ready') != self.binding['campaign_namespace']
                or not (guard.get('title_open') is True or guard.get('main_menu_busy') is True)
                or self.pipe.lobby_status() != ('owned' if scope['role'] == 'H' else 'joined')
                or self.pipe.membership_revision() != scope['membership']['revision']
                or self.pipe.current_campaign(scope['membership']['revision']) != self.binding['campaign_namespace']
                or self.pipe.cloud_status() not in ('cloud-app-disabled', 'cloud-account-disabled')
                or not storage_guard_active(self.solo)
                or active_save_identity(self.pipe, self.solo) != self.solo_identity
                or _directory_id(self.target) != self.target_identity):
            raise ValueError('Checkpoint title, protection, selection or Steam membership changed')
        return guard

    def prepare(self, *, timeout=48):
        if type(timeout) not in (int, float) or not 0 < timeout <= 60:
            raise ValueError('Checkpoint preparation timeout must be within 60 seconds')
        request = secrets.token_hex(16)
        anchor = {'schema': 1, 'game_pid': self.pipe.game_pid, 'request_id': request,
                  'selection': self.selection, 'protection': self.binding,
                  'lobby_revision': self.lobby_revision, 'scope': self.scope, 'guard_run_id': self.guard_run}
        def publish(phase, **fields):
            write_json(self.data/'re2_coop_checkpoint_workspace.json',
                       {**anchor, 'at': int(time.time()), 'phase': phase, **fields})
        with lock_data_directory(self.data, stream='checkpoint_workspace'):
            try:
                self.check()
                if self.archive.verified(self.selection['digest']) != self.manifest:
                    raise ValueError('Selected checkpoint changed')
                descriptor = ' '.join((str(self.scope['membership']['revision']),
                    self.binding['campaign_namespace'], request, self.selection['namespace'], self.selection['digest'],
                    *(self.manifest['files'][name] for name in FILES)))
                publish('preparing')
                reply = self.pipe.request(b'import-checkpoint ' + descriptor.encode('ascii'), pipe_name=self.pipe.lobby_name)
                if reply != b'accepted import-checkpoint':
                    raise ValueError('Native checkpoint preparation rejected: ' + reply.decode('utf-8', errors='replace'))
                deadline = time.monotonic() + timeout
                while not self.stop.wait(.1):
                    self.check()
                    native = _read_json(self.data/'re2_coop_native_save_guard.json')
                    if not isinstance(native, dict):
                        raise ValueError('Invalid native checkpoint report')
                    status = native.get('checkpoint_import') or {}
                    if not isinstance(status, dict):
                        raise ValueError('Invalid native checkpoint status')
                    if status.get('request_id') == request:
                        if (status.get('workspace') != self.binding['campaign_namespace']
                                or status.get('archive_namespace') != self.selection['namespace']
                                or status.get('generation') != self.selection['digest']):
                            raise ValueError('Native checkpoint scope changed')
                        if status.get('phase') == 'failed':
                            raise ValueError('Native checkpoint import failed: ' + str(status.get('error')))
                        if status.get('phase') == 'ready':
                            if (type(status.get('file_index')) is not int or status['file_index'] != 3
                                    or type(status.get('native_result')) is not int or status['native_result'] != 1):
                                raise ValueError('Native checkpoint completion is incomplete')
                            signatures = _signatures(self.target)
                            if _hashes(self.target, signatures) != self.manifest['files']:
                                raise ValueError('Prepared checkpoint bytes differ from the archive')
                            if self.archive.verified(self.selection['digest']) != self.manifest:
                                raise ValueError('Selected checkpoint changed')
                            self.check()
                            if _signatures(self.target) != signatures:
                                raise ValueError('Prepared checkpoint files changed during confirmation')
                            try:
                                catalog = _read_json(self.data/'re2_coop_checkpoint_catalog.json')
                            except FileNotFoundError:
                                catalog = None
                            if (not isinstance(catalog, dict) or catalog.get('request_id') != request):
                                if time.monotonic() >= deadline:
                                    raise ValueError('Native checkpoint catalog timed out')
                                continue
                            if (catalog.get('workspace') != self.binding['campaign_namespace']
                                    or catalog.get('archive_namespace') != self.selection['namespace']
                                    or catalog.get('generation') != self.selection['digest']
                                    or catalog.get('game_pid') != self.pipe.game_pid
                                    or catalog.get('run_id') != self.binding['run_id']
                                    or catalog.get('guard_run_id') != self.guard_run
                                    or type(catalog.get('schema')) is not int or catalog['schema'] != 1
                                    or type(catalog.get('at')) is not int or not 0 <= time.time()-catalog['at'] <= 3):
                                raise ValueError('Native checkpoint catalog binding changed')
                            if catalog.get('phase') == 'failed':
                                raise ValueError('Native checkpoint catalog failed: ' + str(catalog.get('reason')))
                            if catalog.get('phase') != 'ready':
                                if time.monotonic() >= deadline:
                                    raise ValueError('Native checkpoint catalog timed out')
                                continue
                            reference = catalog.get('reference')
                            if (not isinstance(reference, dict) or set(reference) != {'mode','slot_id','timestamp','scenario'}
                                    or type(reference['mode']) is not int or reference['mode'] != 1
                                    or type(reference['slot_id']) is not int or reference['slot_id'] != 0
                                    or type(reference['scenario']) is not int or reference['scenario'] != self.manifest['scenario']):
                                raise ValueError('Native checkpoint catalog reference differs from the selection')
                            saved_time(reference['timestamp'])
                            self.check()
                            if _signatures(self.target) != signatures:
                                raise ValueError('Prepared checkpoint files changed during catalog refresh')
                            result = {**anchor, 'files': dict(self.manifest['files']), 'native_reference': dict(reference),
                                      'scenario': self.manifest['scenario'], 'difficulty': self.manifest['difficulty']}
                            publish('ready', files=result['files'], native_reference=result['native_reference'])
                            return result
                    if time.monotonic() >= deadline:
                        raise ValueError('Native checkpoint preparation timed out')
                raise ValueError('Checkpoint preparation cancelled')
            except BaseException as exc:
                publish('failed', reason=str(exc))
                try:
                    self.pipe.request(b'cancel-checkpoint-import ' + request.encode('ascii'), pipe_name=self.pipe.lobby_name)
                except (OSError, ValueError):
                    pass  # No positive receipt is issued, even if cancellation cannot be acknowledged.
                raise


def _checkpoint_reference(reference, scenario):
    if (not isinstance(reference, dict) or set(reference) != {'mode', 'slot_id', 'timestamp', 'scenario'}
            or type(reference['mode']) is not int or reference['mode'] != 1
            or type(reference['slot_id']) is not int or reference['slot_id'] != 0
            or type(reference['scenario']) is not int or reference['scenario'] != scenario):
        raise ValueError('Checkpoint readiness has a different native reference')
    saved_time(reference['timestamp'])


class CheckpointReadiness:
    """Renew a still-live preparation after rechecking its native inputs and scope.

    The controller must refresh while waiting at the title, then stop before
    submitting the native load. Expiry or any loss permanently closes this object.
    No import, native load, pause release or new preparation nonce is issued here.
    """

    def __init__(self, data, pipe, solo, receipt, stop):
        fields = {'schema', 'game_pid', 'request_id', 'selection', 'protection',
                  'lobby_revision', 'scope', 'guard_run_id', 'files', 'native_reference',
                  'scenario', 'difficulty'}
        receipt = deepcopy(receipt)
        if (not isinstance(receipt, dict) or set(receipt) != fields
                or type(receipt['schema']) is not int or receipt['schema'] != 1
                or type(receipt['game_pid']) is not int or not _token(receipt['request_id'])
                or type(receipt['lobby_revision']) is not int
                or type(receipt['scenario']) is not int or type(receipt['difficulty']) is not int):
            raise ValueError('Invalid checkpoint preparation receipt')
        self.workspace = CheckpointWorkspace(data, pipe, solo, receipt['selection'], stop)
        workspace = self.workspace
        if (receipt['game_pid'] != pipe.game_pid or receipt['scope'] != workspace.scope
                or receipt['protection'] != workspace.binding or receipt['guard_run_id'] != workspace.guard_run
                or receipt['lobby_revision'] != workspace.lobby_revision
                or receipt['files'] != workspace.manifest['files']
                or receipt['scenario'] != workspace.manifest['scenario']
                or receipt['difficulty'] != workspace.manifest['difficulty']):
            raise ValueError('Checkpoint readiness does not belong to this preparation')
        reference = receipt['native_reference']
        _checkpoint_reference(reference, workspace.manifest['scenario'])
        self.receipt = receipt
        self.anchor = {key: value for key, value in receipt.items()
                       if key not in ('files', 'native_reference', 'scenario', 'difficulty')}
        self.template = {**self.anchor, 'phase': 'ready', 'files': receipt['files'],
                         'native_reference': reference}
        self.path = workspace.data/'re2_coop_checkpoint_workspace.json'
        self.state = 'ready'
        with lock_data_directory(workspace.data, stream='checkpoint_workspace'):
            self.record = _read_json(self.path)
            wall, mono = time.time(), time.monotonic()
            at = self.record.get('at') if isinstance(self.record, dict) else None
            if (type(at) is not int or not 0 <= wall-at <= 3
                    or self.record != {**self.template, 'at': at}):
                raise ValueError('Checkpoint readiness is expired or replaced')
            self.last_wall, self.last_mono = wall, mono
            self.deadline = mono + at+3-wall
            self._verify()
            self._clock()
            if _read_json(self.path) != self.record:
                raise ValueError('Checkpoint readiness was replaced during validation')

    def _clock(self):
        wall, mono = time.time(), time.monotonic()
        if (wall < self.last_wall or mono < self.last_mono or mono >= self.deadline
                or not 0 <= wall-self.record['at'] <= 3):
            raise ValueError('Checkpoint readiness expired or its clock changed')
        return wall, mono

    def _proofs(self):
        workspace, receipt = self.workspace, self.receipt
        native = _read_json(workspace.data/'re2_coop_native_save_guard.json')
        catalog = _read_json(workspace.data/'re2_coop_checkpoint_catalog.json')
        now = time.time()
        if (not isinstance(native, dict) or not isinstance(catalog, dict)
                or any(type(value.get('at')) is not int or not 0 <= now-value['at'] <= 3
                       for value in (native, catalog))):
            raise ValueError('Fresh native import and checkpoint catalog are required')
        job = native.get('checkpoint_import') or {}
        expected = {'request_id': receipt['request_id'], 'workspace': workspace.binding['campaign_namespace'],
                    'archive_namespace': workspace.selection['namespace'], 'generation': workspace.selection['digest']}
        if (type(native.get('schema')) is not int or native['schema'] != 1
                or native.get('source') != 'steam_storage_guard' or native.get('active') is not True
                or native.get('reason') != 'ok' or native.get('app_id') != 883710 or native.get('build_id') != 11636119
                or native.get('interface') != '014' or native.get('guarded_methods') != 10
                or native.get('game_pid') != receipt['game_pid'] or native.get('run_id') != workspace.binding['run_id']
                or native.get('campaign_namespace') != workspace.binding['campaign_namespace']
                or not isinstance(job, dict) or any(job.get(key) != value for key, value in expected.items())
                or job.get('phase') != 'ready' or type(job.get('file_index')) is not int or job['file_index'] != 3
                or type(job.get('native_result')) is not int or job['native_result'] != 1):
            raise ValueError('The completed native checkpoint import changed')
        if (type(catalog.get('schema')) is not int or catalog['schema'] != 1 or catalog.get('phase') != 'ready'
                or any(catalog.get(key) != value for key, value in expected.items())
                or catalog.get('game_pid') != receipt['game_pid'] or catalog.get('run_id') != workspace.binding['run_id']
                or catalog.get('guard_run_id') != workspace.guard_run or catalog.get('reference') != receipt['native_reference']):
            raise ValueError('The confirmed native checkpoint catalog changed')
        _checkpoint_reference(catalog.get('reference'), workspace.manifest['scenario'])

    def _verify(self):
        workspace = self.workspace
        workspace.check()
        self._proofs()
        if workspace.archive.verified(workspace.selection['digest']) != workspace.manifest:
            raise ValueError('The immutable checkpoint archive changed')
        signatures = _signatures(workspace.target)
        if _hashes(workspace.target, signatures) != workspace.manifest['files']:
            raise ValueError('Checkpoint working files changed after preparation')
        workspace.check()
        self._proofs()
        if (_signatures(workspace.target) != signatures
                or workspace.archive.verified(workspace.selection['digest']) != workspace.manifest):
            raise ValueError('Checkpoint inputs changed during readiness validation')

    def refresh(self):
        """Return the original receipt only after publishing a fresh verified proof."""
        if self.state != 'ready':
            raise ValueError('Checkpoint readiness is permanently lost')
        with lock_data_directory(self.workspace.data, stream='checkpoint_workspace'):
            try:
                self._clock()
                if _read_json(self.path) != self.record:
                    raise ValueError('Checkpoint readiness was replaced')
                self._verify()
                wall, mono = self._clock()
                if _read_json(self.path) != self.record:
                    raise ValueError('Checkpoint readiness was replaced during validation')
                record = {**self.template, 'at': int(wall)}
                write_json(self.path, record)
                self.record = record
                self.last_wall, self.last_mono = wall, mono
                self.deadline = mono + record['at']+3-wall
                return deepcopy(self.receipt)
            except BaseException:
                self.state = 'lost'
                try:
                    if _read_json(self.path) == self.record:
                        write_json(self.path, {**self.anchor, 'at': int(time.time()),
                            'phase': 'failed', 'reason': 'checkpoint_readiness_lost'})
                except (OSError, ValueError):
                    pass  # A replaced owner is never overwritten; the old proof also expires.
                raise
