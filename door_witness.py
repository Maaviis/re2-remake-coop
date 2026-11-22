"""Validate a native scene door observation made during the owned pause."""

from load_witness import LoadStateFile, _integer


def _fields(value, names):
    return isinstance(value, dict) and value.keys() == names


def _validate_row(row):
    fields = {'id', 'map', 'folder_hash', 'name', 'class', 'opened', 'locked', 'locked_by_key', 'saved'}
    if isinstance(row, dict) and row.get('opened') is True:
        fields.add('opened_side')
    if (not _fields(row, fields)
            or any(not _integer(row[key], 0, 0xffffffff) for key in ('map', 'folder_hash'))
            or any(type(row[key]) is not bool for key in ('opened', 'locked', 'locked_by_key'))
            or not isinstance(row['class'], str) or not 0 < len(row['class']) <= 192
            or not isinstance(row['name'], str) or not 0 < len(row['name'].encode('utf-8')) <= 192
            or any(ord(char) < 32 or ord(char) == 127 for char in row['name'])):
        raise ValueError('invalid native door row')
    if row['opened'] and not _integer(row['opened_side'], -(2**31), 2**31 - 1):
        raise ValueError('invalid native door side')
    if row['id'] != '{:08x}:{:08x}:{}'.format(row['map'], row['folder_hash'], row['name']):
        raise ValueError('invalid native door identity')
    saved = row['saved']
    saved_fields = {'loaded', 'present'}
    if isinstance(saved, dict) and saved.get('present') is True:
        saved_fields.add('has_opened')
    if not _fields(saved, saved_fields) or any(type(value) is not bool for value in saved.values()):
        raise ValueError('invalid native saved door state')


class DoorStateFile(LoadStateFile):
    filename = 're2_coop_interrupted_door_state.json'
    scope = 'loaded_scene_door_state'
    max_bytes = 524288

    @staticmethod
    def validate_state(state):
        if (not _fields(state, {'scenario', 'door_count', 'doors', 'interruption'})
                or not _integer(state['scenario'], 0, 3) or not _integer(state['door_count'], 0, 512)
                or not _fields(state['interruption'], {'scope', 'load_request_id', 'guard_run_id'})):
            raise ValueError('invalid native door state')
        if state['door_count'] == 0 and state['doors'] is None:
            state['doors'] = []
        rows = state['doors']
        if not isinstance(rows, list) or len(rows) != state['door_count']:
            raise ValueError('native door count mismatch')
        previous = ''
        for row in rows:
            _validate_row(row)
            if row['id'] <= previous:
                raise ValueError('non-unique or unordered native doors')
            previous = row['id']
