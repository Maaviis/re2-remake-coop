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


class CheckpointWorkspace:
    def __init__(self, data, pipe, solo, selection, stop):
        if (not isinstance(selection, dict) or set(selection) != {'namespace', 'digest'}
                or not _token(selection['namespace']) or not isinstance(selection['digest'], str)
                or not DIGEST.fullmatch(selection['digest'])):
            raise ValueError('Invalid checkpoint selection')
        self.data, self.pipe, self.solo, self.stop = Path(data), pipe, Path(solo), stop
        self.selection = dict(selection)
        self.archive = HostArchive(self.solo, selection['namespace'])
        self.manifest = self.archive.verified(selection['digest'])
        self.expected_choice = {**self.selection, 'scenario': self.manifest['scenario'],
            'difficulty': self.manifest['difficulty'],
            'saved_at': saved_time(self.manifest['timestamp']).isoformat(sep=' ', timespec='seconds')}
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
                  'lobby_revision': self.lobby_revision, 'scope': self.scope}
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
