"""Validate and canonicalize native item placement evidence."""

from load_witness import GUID, LoadStateFile, _integer
from sync_model import state_digest


_ZERO_GUID = '00000000-0000-0000-0000-000000000000'
_IDENTITY = {'id', 'map', 'location'}
_STORED = {'enabled', 'colliders'}
_LIVE = {'started', 'interaction_disabled', 'collider_asleep'}
_PAYLOAD = {'item_id', 'count', 'weapon', 'parts', 'bullet', 'extra_item', 'extra_count',
            'extra_weapon', 'extra_parts', 'extra_bullet'}
_GROUPS = ('positions', 'live', 'storage')
_MAX_ROWS = 2048


def _shape(obj, keys):
    return isinstance(obj, dict) and obj.keys() == keys


def _code(value):
    return _integer(value, -(2**31), 2**32 - 1)


def _identity(row, *, zero_allowed=False):
    if (not isinstance(row['id'], str) or not GUID.fullmatch(row['id'])
            or not zero_allowed and row['id'] == _ZERO_GUID
            or not all(_code(row[key]) for key in ('location', 'map'))):
        raise ValueError('invalid native item placement')


def _state_row(row, flags, extra=(), *, zero_allowed=False):
    if (not _shape(row, _IDENTITY | {'payload'} | flags | set(extra))
            or not _shape(row['payload'], _PAYLOAD)
            or not all(_code(value) for value in row['payload'].values())
            or not all(type(row[key]) is bool for key in flags)):
        raise ValueError('invalid native world item record')
    _identity(row, zero_allowed=zero_allowed)


class WorldItemStateFile(LoadStateFile):
    filename = 're2_coop_interrupted_world_items.json'
    scope = 'native_world_item_placements'
    max_bytes = 4 * 1024 * 1024

    @staticmethod
    def validate_state(state):
        if (not _shape(state, {'scenario', 'unbound', 'groups', 'interruption'})
                or not _integer(state['scenario'], 0, 3) or not _integer(state['unbound'], 0, _MAX_ROWS)
                or not _shape(state['interruption'], {'scope', 'load_request_id', 'guard_run_id'})
                or not _shape(state['groups'], set(_GROUPS))):
            raise ValueError('invalid native world item state')
        for name in _GROUPS:
            group = state['groups'][name]
            if not _shape(group, {'count', 'records'}) or not _integer(group['count'], 0, _MAX_ROWS):
                raise ValueError('invalid native world item group')
            if group['count'] == 0 and group['records'] is None:
                group['records'] = []
            if not isinstance(group['records'], list) or len(group['records']) != group['count']:
                raise ValueError('native world item count mismatch')
        groups = state['groups']
        if groups['live']['count'] + state['unbound'] > _MAX_ROWS:
            raise ValueError('native live world item count exceeded')
        positions = set()
        for row in groups['positions']['records']:
            if not _shape(row, _IDENTITY):
                raise ValueError('invalid native item position')
            _identity(row)
            if row['id'] in positions:
                raise ValueError('duplicate native item position')
            positions.add(row['id'])
        for row in groups['live']['records']:
            has_save = isinstance(row, dict) and 'saved' in row
            _state_row(row, _LIVE, ('saved',) if has_save else ())
            if has_save:
                _state_row(row['saved'], _STORED)
                if row['saved']['id'] != row['id']:
                    raise ValueError('world item save record belongs to another placement')
        for row in groups['storage']['records']:
            _state_row(row, _STORED, ('bucket',), zero_allowed=True)
            if not _integer(row['bucket'], 0, 127):
                raise ValueError('invalid native world item location bucket')
        groups['positions']['records'].sort(key=lambda row: row['id'])
        for name in ('live', 'storage'):
            # Multiple records can share a placement GUID, including within one native location.
            groups[name]['records'].sort(key=state_digest)
