"""Compare fresh native checkpoints for the same admitted Steam lobby load."""


from load_witness import LoadStateFile, new_game_checkpoint
from load_preflight import TOKEN, checkpoint_save_reference, validate_checkpoint
from readonly_save_control import read_active_guard, read_connected_lobby
from save_catalog import IDENTITY_FIELDS, validate_reference
from sync_model import Replica, state_digest
from prepared_load_pause import held_pause


SCOPE = 'prepared_load_checkpoint'
_ATTEMPT_FIELDS = ('revision', 'attempt_id', 'save_digest')
_LOAD_TRANSITION_REASONS = {'selection_changed', 'local_source_unavailable',
                            'guest_source_unavailable', 'guest_ack_expired', 'start_window_expired'}


class PreparedCheckpoint:
    def __init__(self, data, game_pid, role, *, checkpoint_policy=None):
        self.data = data
        self.game_pid = game_pid
        self.role = role
        self.reader = LoadStateFile(data)
        self.checkpoint_policy = checkpoint_policy

    def _read_binding(self, guard):
        link, lobby = read_connected_lobby(self.data)
        if link['game_pid'] != self.game_pid or link['role'] != self.role:
            raise ValueError('checkpoint comparison requires the current Steam role and game process')
        if guard['protection']['game_pid'] != self.game_pid:
            raise ValueError('checkpoint comparison requires the protected game process')
        admitted = guard.get('prepared_load')
        policy = self.checkpoint_policy
        if policy is not None:
            expected = {key: policy[key] for key in ('checkpoint', 'preparation_id', 'reference')}
            if (policy['schema'] != 5 or guard['protection'] != policy['protection']
                    or guard.get('policy_id') != policy['id'] or guard.get('load_request_id') != policy['id']
                    or admitted != {**expected, 'scope': policy['lobby_load']}):
                raise ValueError('Native checkpoint differs from the staged preparation')
        if not isinstance(admitted, dict) or set(admitted) not in ({'scope', 'reference'}, {'scope', 'new_game'},
                {'scope', 'reference', 'checkpoint', 'preparation_id'}):
            raise ValueError('no native load admitted by the prepared Steam lobby')
        check = lobby.get('load_check')
        run_id = guard.get('guard_run_id')
        if (not check or check['phase'] == 'checking' or not isinstance(run_id, str) or not 0 < len(run_id) <= 128
                or (check['phase'] == 'failed' and check['reason'] not in _LOAD_TRANSITION_REASONS)):
            raise ValueError('the prepared load is no longer current')
        shared = {'session_id': link['session_id'], **{field: check[field] for field in _ATTEMPT_FIELDS}}
        scope = {**link, **shared, 'guard_run_id': run_id}
        if admitted['scope'] != scope:
            raise ValueError('native load belongs to a different Steam lobby attempt or save')
        if 'new_game' in admitted:
            from lobby_sync import validate_new_game

            selection = admitted['new_game']
            validate_new_game(selection)
            if (lobby.get('new_game') != selection or 'save_ref' in lobby or lobby.get('save_slot') is not None
                    or check.get('campaign_start') is not True or check.get('admission') != 1
                    or lobby['revision'] != check['revision'] or not all(lobby['ready'].values())
                    or not (check['phase'] == 'starting' and check['start'][self.role] == state_digest(scope)[:32]
                            or check['phase'] == 'failed' and check['reason'] == 'start_window_expired')
                    or state_digest({'new_game': selection}) != shared['save_digest']):
                raise ValueError('native new game belongs to a different Steam lobby attempt or selection')
            return scope, selection, shared
        if 'checkpoint' in admitted:
            checkpoint = admitted['checkpoint']
            validate_checkpoint(checkpoint)
            reference = checkpoint_save_reference(admitted['reference'])
            choice = lobby['settings'].get('coop_checkpoint')
            validate_checkpoint(choice, metadata=True)
            preparation = admitted['preparation_id']
            if (not isinstance(preparation, str) or not TOKEN.fullmatch(preparation)
                    or any(choice[key] != value for key, value in checkpoint.items())
                    or checkpoint['digest'] != shared['save_digest'] or choice['scenario'] != reference['scenario']
                    or lobby.get('new_game') is not None or 'save_ref' in lobby or lobby.get('save_slot') is not None
                    or check.get('checkpoint_version') != 1 or check.get('campaign_start') is not True
                    or check.get('admission') != 1 or lobby['revision'] != check['revision']
                    or not all(lobby['ready'].values())
                    or not (check['phase'] == 'starting' and check['start'][self.role] == state_digest(scope)[:32]
                            or check['phase'] == 'failed' and check['reason'] == 'start_window_expired')
                    or type(guard.get('allowed_load_calls')) is not int or guard['allowed_load_calls'] != 1
                    or guard.get('runtime_protection') is not True
                    or not TOKEN.fullmatch(guard['protection'].get('campaign_namespace', ''))
                    or guard.get('campaign_mount_ready') != guard['protection']['campaign_namespace']):
                raise ValueError('native checkpoint belongs to another archive, mount or shared attempt')
            return scope, reference, {**shared, 'checkpoint': dict(choice)}
        reference = admitted['reference']
        validate_reference(reference)
        selected = lobby.get('save_ref', {})
        if ('new_game' in lobby or lobby['save_slot'] != f"scenario:{reference['slot_id']}"
                or (selected.get('available') is True
                    and any(reference[field] != selected[field] for field in IDENTITY_FIELDS))):
            raise ValueError('native load belongs to a different Steam lobby attempt or save')
        return scope, reference, shared

    def _capture(self, session_id):
        guard = read_active_guard(self.data, protected=True)
        binding = self._read_binding(guard)
        scope, reference, shared = binding
        request_id = state_digest(scope)[:32]
        pause = held_pause(guard, request_id)
        new_game = 'new_game' in guard['prepared_load']
        resuming = 'checkpoint' in guard['prepared_load']
        if resuming and scope['session_id'] != session_id:
            raise ValueError('checkpoint archive belongs to another Steam session')
        if new_game:
            if scope['session_id'] != session_id:
                raise ValueError('new game checkpoint belongs to a different Steam session')
            checkpoint = new_game_checkpoint(guard, request_id, reference)
        else:
            checkpoint = self.reader.for_load(request_id, reference)['state']['checkpoint']
            if resuming and checkpoint['difficulty'] != shared['checkpoint']['difficulty']:
                raise ValueError('native checkpoint difficulty differs from the selected archive')
        latest = read_active_guard(self.data, protected=True)
        if (latest['protection'] != guard['protection'] or self._read_binding(latest) != binding
                or held_pause(latest, request_id) != pause
                or latest.get('load_request_id') != request_id
                or latest.get('policy_id') != request_id or latest.get('load_phase') != 'scene_loaded'
                or latest.get('load_error') != '' or type(latest.get('denied_loads')) is not int
                or latest['denied_loads'] != 0 or latest.get('writes') not in (None, {})
                or new_game and new_game_checkpoint(latest, request_id, reference) != checkpoint):
            raise ValueError('native load binding changed while reading the checkpoint')
        view = {'schema': 4 if resuming else 3 if new_game else 2, **shared, 'native_pause_held': True,
                'checkpoint_digest': state_digest(checkpoint)}
        model = Replica(session_id=session_id, sequence=1)
        model.state['flags'][SCOPE] = view
        return model.snapshot(), checkpoint if new_game else None

    def capture(self, session_id):
        snapshot, _ = self._capture(session_id)
        return snapshot

    def confirm(self, snapshot):
        expected, world = self._capture(snapshot['session_id'])
        body = snapshot['state']
        remote = body['flags'].get(SCOPE)
        local = expected['state']['flags'][SCOPE]
        if (snapshot['sequence'] != 1 or body['flags'].keys() != {SCOPE}
                or any(value for key, value in body.items() if key != 'flags')
                or not isinstance(remote, dict) or remote.keys() != local.keys()
                or type(remote['schema']) is not int or type(remote['revision']) is not int
                or remote['native_pause_held'] is not True
                or any(remote[key] != local[key] for key in local if key != 'checkpoint_digest')):
            raise ValueError('checkpoint evidence belongs to a different Steam lobby attempt')
        if remote['checkpoint_digest'] != local['checkpoint_digest']:
            raise ValueError('host and guest native checkpoints differ')
        report = {'scope': SCOPE, 'attempt_id': local['attempt_id'], 'checkpoint_match': True,
                  'native_pause_match': True}
        if world is not None:
            report['new_game_world'] = world
        return report
