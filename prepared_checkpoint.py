"""Compare fresh native checkpoints for the same admitted Steam lobby load."""


from load_witness import LoadStateFile
from readonly_save_control import read_active_guard, read_connected_lobby
from save_catalog import IDENTITY_FIELDS, validate_reference
from sync_model import Replica, state_digest
from prepared_load_pause import held_pause


SCOPE = 'prepared_load_checkpoint'
_ATTEMPT_FIELDS = ('revision', 'attempt_id', 'save_digest')
_LOAD_TRANSITION_REASONS = {'selection_changed', 'local_source_unavailable',
                            'guest_source_unavailable', 'guest_ack_expired'}


class PreparedCheckpoint:
    def __init__(self, data, game_pid, role):
        self.data = data
        self.game_pid = game_pid
        self.role = role
        self.reader = LoadStateFile(data)

    def _read_binding(self, guard):
        link, lobby = read_connected_lobby(self.data)
        if link['game_pid'] != self.game_pid or link['role'] != self.role:
            raise ValueError('checkpoint comparison requires the current Steam role and game process')
        admitted = guard.get('prepared_load')
        if not isinstance(admitted, dict) or set(admitted) != {'scope', 'reference'}:
            raise ValueError('no native load admitted by the prepared Steam lobby')
        check = lobby.get('load_check')
        run_id = guard.get('guard_run_id')
        if (not check or check['phase'] == 'checking' or not isinstance(run_id, str) or not 0 < len(run_id) <= 128
                or (check['phase'] == 'failed' and check['reason'] not in _LOAD_TRANSITION_REASONS)):
            raise ValueError('the prepared load is no longer current')
        shared = {'session_id': link['session_id'], **{field: check[field] for field in _ATTEMPT_FIELDS}}
        scope = {**link, **shared, 'guard_run_id': run_id}
        reference = admitted['reference']
        validate_reference(reference)
        selected = lobby.get('save_ref', {})
        if (admitted['scope'] != scope or lobby['save_slot'] != f"scenario:{reference['slot_id']}"
                or (selected.get('available') is True
                    and any(reference[field] != selected[field] for field in IDENTITY_FIELDS))):
            raise ValueError('native load belongs to a different Steam lobby attempt or save')
        return scope, reference, shared

    def capture(self, session_id):
        guard = read_active_guard(self.data)
        binding = self._read_binding(guard)
        scope, reference, shared = binding
        request_id = state_digest(scope)[:32]
        pause = held_pause(guard, request_id)
        evidence = self.reader.for_load(request_id, reference)
        latest = read_active_guard(self.data)
        if (self._read_binding(latest) != binding or held_pause(latest, request_id) != pause
                or latest.get('load_request_id') != request_id
                or latest.get('policy_id') != request_id or latest.get('load_phase') != 'scene_loaded'
                or latest.get('load_error') != '' or type(latest.get('denied_loads')) is not int
                or latest['denied_loads'] != 0 or latest.get('writes') not in (None, {})):
            raise ValueError('native load binding changed while reading the checkpoint')
        view = {'schema': 2, **shared, 'native_pause_held': True,
                'checkpoint_digest': state_digest(evidence['state']['checkpoint'])}
        model = Replica(session_id=session_id, sequence=1)
        model.state['flags'][SCOPE] = view
        return model.snapshot()

    def confirm(self, snapshot):
        expected = self.capture(snapshot['session_id'])
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
        return {'scope': SCOPE, 'attempt_id': local['attempt_id'], 'checkpoint_match': True,
                'native_pause_match': True}
