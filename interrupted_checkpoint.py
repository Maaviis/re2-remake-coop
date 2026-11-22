"""Compare a paused campaign's location, original load header and live inventory."""

import re
import time

from load_witness import LoadStateFile, TOKEN, _integer
from readonly_save_control import read_active_guard, read_connected_lobby
from save_catalog import validate_reference
from sync_model import Replica, state_digest


SCOPE = 'interrupted_campaign_checkpoint'
COMPONENTS = ('area', 'inventory', 'load_header')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_ZERO_GUID = '00000000-0000-0000-0000-000000000000'


class InterruptedCheckpoint:
    def __init__(self, data, game_pid, role):
        self.data = data
        self.game_pid = game_pid
        self.role = role
        self.reader = LoadStateFile(data)

    def _binding(self):
        guard = read_active_guard(self.data, protected=True)
        link, _ = read_connected_lobby(self.data)
        now = time.time()
        hold = guard.get('load_hold')
        interrupted = hold.get('interruption') if isinstance(hold, dict) else None
        request_id = guard.get('load_request_id', '')
        if (not isinstance(interrupted, dict) or not isinstance(request_id, str) or not TOKEN.fullmatch(request_id)
                or guard.get('policy_id') != request_id or guard.get('load_phase') != 'scene_loaded'
                or guard.get('load_error') != '' or guard.get('in_title') is not False
                or not _integer(guard.get('load_started_at'), 1)
                or type(guard.get('denied_loads')) is not int or guard['denied_loads'] != 0
                or type(guard.get('allowed_load_calls')) is not int or guard['allowed_load_calls'] != 1
                or guard.get('writes') not in (None, {})
                or type(hold.get('schema')) is not int or hold['schema'] != 1
                or hold.get('scope') != 'prepared_load_native_pause'
                or hold.get('phase') != 'interrupted' or hold.get('native_phase') != 'held'
                or hold.get('pause_id') != request_id or hold.get('load_request_id') != request_id
                or not isinstance(guard.get('guard_run_id'), str) or not guard['guard_run_id']
                or hold.get('guard_run_id') != guard['guard_run_id']
                or not _integer(hold.get('observed_at'), 1) or not 0 <= now - hold['observed_at'] <= 3
                or not _integer(interrupted.get('at'), guard['load_started_at'], hold['observed_at'])
                or any(record.get('game_pid') != self.game_pid for record in
                       (guard['protection'], link, interrupted))
                or link['role'] != self.role or interrupted.get('role') != self.role
                or interrupted.get('protection_run_id') != guard['protection']['run_id']):
            raise ValueError('a fresh owned native pause after campaign interruption is required')

        admitted = guard.get('prepared_load')
        started = admitted.get('scope') if isinstance(admitted, dict) else None
        if not isinstance(started, dict):
            raise ValueError('the original protected campaign is missing')
        reference = admitted.get('reference')
        validate_reference(reference)
        area = interrupted.get('area')
        tokens = {'campaign_session_id': interrupted.get('session_id'), 'attempt_id': interrupted.get('attempt_id'),
                  'release_id': interrupted.get('release_id'), 'connected_session_id': link['session_id']}
        if (any(not isinstance(value, str) or not TOKEN.fullmatch(value) for value in tokens.values())
                or started.get('session_id') != tokens['campaign_session_id']
                or started.get('attempt_id') != tokens['attempt_id']
                or started.get('game_pid') != self.game_pid or started.get('role') != self.role
                or started.get('guard_run_id') != guard['guard_run_id']
                or not _integer(guard.get('allowed_slot'), reference['slot_id'], reference['slot_id'])
                or not _integer(guard.get('load_index'), reference['slot_id'], reference['slot_id'])
                or not isinstance(area, dict) or area.keys() != {'scenario', 'map', 'area'}
                or not _integer(area['scenario'], 0, 3) or area['scenario'] != reference['scenario']
                or any(not _integer(area[key], 0, 0xffffffff) for key in ('map', 'area'))):
            raise ValueError('native interruption does not match the original protected campaign')
        return (link, tokens, guard['guard_run_id'], guard['protection']['run_id'],
                request_id, reference, interrupted['at'], area)

    def capture(self, session_id):
        binding = self._binding()
        _, tokens, _, _, _, reference, interrupted_at, area = binding
        sample = self.reader.read()
        if not sample['available'] or sample['observed_at'] <= interrupted_at:
            raise ValueError('a native inventory observation after the confirmed pause is required')
        state = sample['state']
        checkpoint = state['checkpoint']
        if (checkpoint['scenario'] != reference['scenario']
                or any(checkpoint[key] == _ZERO_GUID for key in ('game_guid', 'save_guid'))
                or self._binding() != binding):
            raise ValueError('native interruption changed while reading the checkpoint')
        components = {'area': state_digest(area), 'inventory': state_digest(state['inventory']),
                      'load_header': state_digest(checkpoint)}
        model = Replica(session_id=session_id, sequence=1)
        model.state['flags'][SCOPE] = {'schema': 1, **tokens, **components}
        return model.snapshot()

    @staticmethod
    def compare(snapshot, local_snapshot):
        local = local_snapshot['state']['flags'][SCOPE]
        body = snapshot['state']
        remote = body['flags'].get(SCOPE)
        if (snapshot['sequence'] != 1 or body['flags'].keys() != {SCOPE}
                or any(value for name, value in body.items() if name != 'flags')
                or not isinstance(remote, dict) or remote.keys() != local.keys()
                or type(remote['schema']) is not int
                or any(remote[key] != local[key] for key in local if key not in COMPONENTS)
                or any(not isinstance(remote[key], str) or not _DIGEST.fullmatch(remote[key]) for key in COMPONENTS)):
            raise ValueError('checkpoint evidence belongs to a different interrupted campaign or Steam lobby')
        return {key: remote[key] == local[key] for key in COMPONENTS}
