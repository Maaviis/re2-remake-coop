"""Compare the native state of a campaign held after interruption."""

import re
import time

from door_witness import DoorStateFile
from enemy_witness import EnemyStateFile
from load_witness import LoadStateFile, TOKEN, _integer
from readonly_save_control import read_active_guard, read_connected_lobby
from save_catalog import validate_reference
from sync_model import Replica, state_digest
from world_item_witness import WorldItemStateFile


SCOPE = 'interrupted_campaign_checkpoint'
COMPONENTS = ('area', 'inventory', 'load_header', 'enemy_live', 'enemy_storage', 'doors', 'world_items')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_ZERO_GUID = '00000000-0000-0000-0000-000000000000'


class InterruptedEnemyStateFile(EnemyStateFile):
    filename = 're2_coop_interrupted_enemy_state.json'


class InterruptedCheckpoint:
    def __init__(self, data, game_pid, role):
        self.data = data
        self.game_pid = game_pid
        self.role = role
        self.reader = LoadStateFile(data)
        self.enemies = InterruptedEnemyStateFile(data)
        self.doors = DoorStateFile(data)
        self.items = WorldItemStateFile(data)

    def _binding(self):
        guard = read_active_guard(self.data, protected=True)
        link, _ = read_connected_lobby(self.data)
        now = time.time()
        hold = guard.get('load_hold')
        interrupted = hold.get('interruption') if isinstance(hold, dict) else None
        request_id = guard.get('load_request_id', '')
        # The active write hooks count rejected attempts during the campaign.
        blocked_writes = guard.get('writes')
        if (not isinstance(interrupted, dict) or not isinstance(request_id, str) or not TOKEN.fullmatch(request_id)
                or guard.get('policy_id') != request_id or guard.get('load_phase') != 'scene_loaded'
                or guard.get('load_error') != '' or guard.get('in_title') is not False
                or not _integer(guard.get('load_started_at'), 1)
                or type(guard.get('denied_loads')) is not int or guard['denied_loads'] != 0
                or type(guard.get('allowed_load_calls')) is not int or guard['allowed_load_calls'] != 1
                or (blocked_writes is not None and (not isinstance(blocked_writes, dict)
                    or any(not _integer(count, 1) for count in blocked_writes.values())))
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
        return link, tokens, reference, {
            'scope': interrupted, 'load_request_id': request_id, 'guard_run_id': guard['guard_run_id']}

    def capture(self, session_id):
        binding = self._binding()
        _, tokens, reference, interruption = binding
        scope = interruption['scope']
        sample = self.reader.read()
        if not sample['available'] or sample['observed_at'] <= scope['at']:
            raise ValueError('a native inventory observation after the confirmed pause is required')
        state = sample['state']
        checkpoint = state['checkpoint']
        enemy_sample = self.enemies.read()
        if not enemy_sample['available'] or enemy_sample['observed_at'] <= scope['at']:
            raise ValueError('a native enemy observation after the confirmed pause is required')
        enemies = enemy_sample['state']
        if (enemies.get('interruption') != interruption
                or any(checkpoint.get(key) != value for key, value in enemies['checkpoint'].items())):
            raise ValueError('native enemies belong to a different interruption or load')
        door_sample = self.doors.read()
        if not door_sample['available'] or door_sample['observed_at'] <= scope['at']:
            raise ValueError('a native door observation after the confirmed pause is required')
        doors = door_sample['state']
        if doors['interruption'] != interruption or doors['scenario'] != scope['area']['scenario']:
            raise ValueError('native doors belong to a different interruption or load')
        item_sample = self.items.read()
        if not item_sample['available'] or item_sample['observed_at'] <= scope['at']:
            raise ValueError('a native world item observation after the confirmed pause is required')
        items = item_sample['state']
        if items['interruption'] != interruption or items['scenario'] != scope['area']['scenario']:
            raise ValueError('native world items belong to a different interruption or load')
        if (checkpoint['scenario'] != reference['scenario']
                or any(checkpoint[key] == _ZERO_GUID for key in ('game_guid', 'save_guid'))
                or self._binding() != binding):
            raise ValueError('native interruption changed while reading the checkpoint')
        components = {
            'area': state_digest(scope['area']),
            'inventory': state_digest(state['inventory']),
            'load_header': state_digest(checkpoint),
            'enemy_live': state_digest([{key: row[key] for key in ('id', 'kind_id', 'context', 'live')}
                                        for row in enemies['entries']]),
            'enemy_storage': state_digest({
                'registered': [row['stored'] for row in enemies['entries'] if row['stored']['present']],
                'storage': enemies['stored_entries'], 'total_kills': enemies['total_kills'],
            }),
            'doors': state_digest(doors['doors']),
            'world_items': state_digest({'groups': items['groups'], 'unbound': items['unbound']}),
        }
        model = Replica(session_id=session_id, sequence=1)
        model.state['flags'][SCOPE] = {'schema': 4, **tokens, **components}
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
