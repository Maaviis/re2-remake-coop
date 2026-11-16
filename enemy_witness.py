"""Stage scoped native enemy observations as a diagnostic v1 snapshot."""

import math

from guest_pose import FLOAT32_MAX
from load_witness import GUID, LoadStateFile, _integer
from protocol.snapshot_transfer import MAX_SNAPSHOT_BYTES
from sync_model import Replica


SCOPE = 'registered_and_stored_enemy_contexts'
MAX_ENEMIES = 512
_ZERO_GUID = '00000000-0000-0000-0000-000000000000'
_CHECKPOINT_FIELDS = {'game_guid', 'save_guid', 'scenario', 'location'}
_SUMMARY_FIELDS = {'registered_count', 'stored_count', 'active_count', 'total_kills', 'paused'}


def _fields(value, names):
    if not isinstance(value, dict) or value.keys() != names:
        raise ValueError('unexpected native enemy fields')


def _guid(value):
    if not isinstance(value, str) or value == _ZERO_GUID or not GUID.fullmatch(value):
        raise ValueError('invalid native enemy or checkpoint identity')
    return value


def _members(value, *, signed=(), unsigned=(), flags=(), other=()):
    _fields(value, set(signed) | set(unsigned) | set(flags) | set(other))
    if (any(not _integer(value[key], -(2**31), 2**31 - 1) for key in signed)
            or any(not _integer(value[key], 0, 2**32 - 1) for key in unsigned)
            or any(type(value[key]) is not bool for key in flags)):
        raise ValueError('invalid native enemy field type')


def _present(value):
    if not isinstance(value, dict) or type(value.get('present')) is not bool:
        raise ValueError('native enemy source has no presence flag')
    if value['present'] is False:
        _fields(value, {'present'})
    return value['present']


def _transform(value):
    for key, length in (('position', 3), ('rotation', 4)):
        vector = value[key]
        if (not isinstance(vector, list) or len(vector) != length
                or any(type(number) not in (int, float) or not -FLOAT32_MAX <= number <= FLOAT32_MAX
                       for number in vector)):
            raise ValueError('invalid native enemy transform')
    if math.hypot(*value['rotation']) == 0:
        raise ValueError('invalid native enemy rotation')


def _storage(value):
    if not _present(value):
        raise ValueError('missing native enemy storage row')
    _members(value, signed=('kind_id', 'inherit_id', 'default_hp', 'hp', 'wince_hp', 'map', 'area'),
             unsigned=('flags',), flags=('present', 'eliminated'), other=('id', 'position', 'rotation'))
    _transform(value)
    return _guid(value['id'])


def _registered(value):
    _members(value, signed=('kind_id',), other=('id', 'context', 'stored', 'live'))
    identity = _guid(value['id'])
    context, stored, live = value['context'], value['stored'], value['live']
    have_context, have_stored = _present(context), _present(stored)
    if not (have_context or have_stored):
        raise ValueError('registry enemy has no native context')
    if have_context:
        _members(context, signed=('inherit_id', 'status'), flags=('present', 'eliminated'),
                 other=('position', 'rotation'))
        _transform(context)
    if have_stored and (_storage(stored) != identity or stored['kind_id'] != value['kind_id']):
        raise ValueError('registry enemy does not match its stored context')
    if _present(live):
        _members(live, signed=('inherit_id', 'default_hp', 'hp'), unsigned=('conditions', 'conditions2'),
                 flags=('present', 'active', 'is_live', 'setup', 'loading', 'standby', 'is_dead'))
    return identity


def _enemy_state(value):
    _fields(value, _SUMMARY_FIELDS | {'checkpoint', 'entries', 'stored_entries'})
    checkpoint = value['checkpoint']
    _members(checkpoint, signed=('scenario', 'location'), other=('game_guid', 'save_guid'))
    _guid(checkpoint['game_guid'])
    _guid(checkpoint['save_guid'])
    if type(value['paused']) is not bool or not _integer(value['total_kills'], 0, 2**32 - 1):
        raise ValueError('invalid native enemy summary')
    for count_key, rows_key, validate in (('registered_count', 'entries', _registered),
                                          ('stored_count', 'stored_entries', _storage)):
        count, rows = value[count_key], value[rows_key]
        if not _integer(count, 0, MAX_ENEMIES):
            raise ValueError('invalid native enemy count')
        if count == 0 and rows is None:
            value[rows_key] = rows = []  # REFramework can encode an empty Lua sequence as null.
        if not isinstance(rows, list) or len(rows) != count:
            raise ValueError('native enemy count does not match its rows')
        identities = [validate(row) for row in rows]
        if identities != sorted(set(identities)):
            raise ValueError('duplicate or unordered native enemy GUID')
    active = sum(row['live'].get('active') is True for row in value['entries'])
    if not _integer(value['active_count'], active, active):
        raise ValueError('active enemy count does not match the registry')


class EnemyStateFile(LoadStateFile):
    """Read the native enemy witness during the same guarded load as the core witness."""

    filename = 're2_coop_enemy_state.json'
    scope = SCOPE
    max_bytes = MAX_SNAPSHOT_BYTES * 2
    validate_state = staticmethod(_enemy_state)

    def __init__(self, data):
        super().__init__(data)
        self.load_header = LoadStateFile(data)

    def snapshot_for_load(self, request_id, reference, session_id, *, now=None):
        evidence = self.for_load(request_id, reference, now=now)
        load = self.load_header.for_load(request_id, reference, now=now)
        state = evidence['state']
        checkpoint = state['checkpoint']
        if any(checkpoint[key] != load['state']['checkpoint'][key] for key in _CHECKPOINT_FIELDS):
            raise ValueError('enemy observation belongs to a different native checkpoint')

        replica = Replica(session_id=session_id, sequence=self.accepted['sequence'])
        replica.state['flags']['native_enemy_observation'] = {
            'schema': 1, 'scope': SCOPE, 'tdb': 70, 'observed_at': evidence['observed_at'],
            'scenario': checkpoint['scenario'], 'location': checkpoint['location'],
            **{key: state[key] for key in _SUMMARY_FIELDS},
        }
        for rows, source in ((state['entries'], 'registered'), (state['stored_entries'], 'storage')):
            for row in rows:
                replica.state['enemies'].setdefault(row['id'], {})[source] = row
        return replica.snapshot()
