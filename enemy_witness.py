"""Stage scoped native enemy observations as a diagnostic v1 snapshot."""

import math

from guest_pose import FLOAT32_MAX
from load_witness import GUID, LoadStateFile, _integer
from protocol import v1
from protocol.snapshot_transfer import MAX_SNAPSHOT_BYTES
from sync_model import Replica, state_digest


SCOPE = 'registered_and_stored_enemy_contexts'
MAX_ENEMIES = 512
_ZERO_GUID = '00000000-0000-0000-0000-000000000000'
_CHECKPOINT_FIELDS = {'game_guid', 'save_guid', 'scenario', 'location'}
_SUMMARY_FIELDS = {'registered_count', 'stored_count', 'active_count', 'total_kills', 'paused'}
_REPORT_FLAG = 'native_enemy_observation'
_REPORT_FIELDS = _SUMMARY_FIELDS | {'schema', 'scope', 'tdb', 'observed_at', 'scenario', 'location'}


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


def _registered(value, *, held_pause=False):
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
        flags = ('present', 'active', 'is_live', 'setup', 'loading', 'standby', 'is_dead')
        _members(live, signed=('inherit_id', 'default_hp', 'hp'), unsigned=('conditions', 'conditions2'),
                 flags=flags + (('active_list_member',) if held_pause else ()))
    return identity


def _enemy_rows(value):
    if type(value['paused']) is not bool or not _integer(value['total_kills'], 0, 2**32 - 1):
        raise ValueError('invalid native enemy summary')
    held_pause = 'interruption' in value
    for count_key, rows_key, validate in (('registered_count', 'entries', lambda row: _registered(row, held_pause=held_pause)),
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
    active = sum(row['live'].get('active_list_member' if held_pause else 'active') is True for row in value['entries'])
    if not _integer(value['active_count'], active, active):
        raise ValueError('active enemy count does not match the registry')


def _enemy_state(value):
    campaign_fields = {'campaign_area', 'campaign_visit', 'campaign_death_callbacks', 'interruption'}
    _fields(value, _SUMMARY_FIELDS | {'checkpoint', 'entries', 'stored_entries'}
            | (value.keys() & campaign_fields if isinstance(value, dict) else set()))
    if 'campaign_area' in value:
        from observer import valid_campaign_area

        if not valid_campaign_area(value['campaign_area']):
            raise ValueError('invalid native enemy campaign area')
    if 'campaign_visit' in value and ('campaign_area' not in value
            or not isinstance(value['campaign_visit'], str) or not 0 < len(value['campaign_visit']) <= 128):
        raise ValueError('invalid native enemy area visit')
    if 'campaign_death_callbacks' in value:
        callbacks = value['campaign_death_callbacks']
        if callbacks is None:  # An empty REFramework table can serialize as null.
            value['campaign_death_callbacks'] = callbacks = {}
        if 'campaign_visit' not in value or not isinstance(callbacks, dict) or len(callbacks) > 128:
            raise ValueError('invalid native death callback witness')
        for identity, callback in callbacks.items():
            _guid(identity)
            _fields(callback, {'sequence', 'at'})
            if not _integer(callback['sequence'], 1) or not _integer(callback['at'], 1):
                raise ValueError('invalid native death callback sequence or time')
    if 'interruption' in value:
        _fields(value['interruption'], {'scope', 'load_request_id', 'guard_run_id'})
        if not isinstance(value['interruption']['scope'], dict):
            raise ValueError('invalid interruption enemy binding')
    checkpoint = value['checkpoint']
    _members(checkpoint, signed=('scenario', 'location'), other=('game_guid', 'save_guid'))
    _guid(checkpoint['game_guid'])
    _guid(checkpoint['save_guid'])
    _enemy_rows(value)


class EnemyStateFile(LoadStateFile):
    """Read the native enemy witness during the same guarded load as the core witness."""

    filename = 're2_coop_enemy_state.json'
    scope = SCOPE
    max_bytes = MAX_SNAPSHOT_BYTES * 2
    validate_state = staticmethod(_enemy_state)

    def __init__(self, data, *, campaign=False):
        super().__init__(data, released_campaign=campaign)
        if campaign:
            self.filename = 're2_coop_campaign_enemy_state.json'
        self.load_header = LoadStateFile(data, released_campaign=campaign)

    def for_load(self, request_id, reference, *, now=None, continuing=False):
        evidence = super().for_load(request_id, reference, now=now, continuing=continuing)
        evidence['observer_sequence'] = self.accepted['sequence']
        load = self.load_header.for_load(request_id, reference, now=now, continuing=continuing)
        checkpoint = evidence['state']['checkpoint']
        if any(checkpoint[key] != load['state']['checkpoint'][key] for key in _CHECKPOINT_FIELDS):
            raise ValueError('enemy observation belongs to a different native checkpoint')
        return evidence

    def snapshot_for_load(self, request_id, reference, session_id, *, comparison_id=None, now=None, continuing=False):
        evidence = self.for_load(request_id, reference, now=now, continuing=continuing)
        state = evidence['state']
        checkpoint = state['checkpoint']
        replica = Replica(session_id=session_id, sequence=evidence['observer_sequence'])
        metadata = {
            'schema': 1, 'scope': SCOPE, 'tdb': 70, 'observed_at': evidence['observed_at'],
            'scenario': checkpoint['scenario'], 'location': checkpoint['location'],
            **{key: state[key] for key in _SUMMARY_FIELDS},
        }
        if comparison_id is not None:
            if not isinstance(comparison_id, str) or not v1.REQUEST_ID.fullmatch(comparison_id):
                raise ValueError('invalid peer comparison request ID')
            metadata['checkpoint_proof'] = state_digest({
                'scope': SCOPE, 'request_id': comparison_id, 'checkpoint': checkpoint,
            })
        replica.state['flags'][_REPORT_FLAG] = metadata
        for rows, source in ((state['entries'], 'registered'), (state['stored_entries'], 'storage')):
            for row in rows:
                replica.state['enemies'].setdefault(row['id'], {})[source] = row
        return replica.snapshot()


def _snapshot_observations(snapshot):
    state = snapshot['state']
    if any(value for key, value in state.items() if key not in ('enemies', 'flags')):
        raise ValueError('enemy snapshot includes an unrelated state category')
    _fields(state['flags'], {_REPORT_FLAG})
    metadata = state['flags'][_REPORT_FLAG]
    _fields(metadata, _REPORT_FIELDS | {'checkpoint_proof'})
    if (metadata['scope'] != SCOPE or not _integer(metadata['schema'], 1, 1)
            or not _integer(metadata['tdb'], 70, 70) or not _integer(metadata['observed_at'], 1)
            or any(not _integer(metadata[key], 0, 2**31 - 1) for key in ('scenario', 'location'))
            or not isinstance(metadata['checkpoint_proof'], str)
            or not v1.DIGEST.fullmatch(metadata['checkpoint_proof'])):
        raise ValueError('invalid native peer enemy observation')
    enemies = state['enemies']
    if not isinstance(enemies, dict) or len(enemies) > 2 * MAX_ENEMIES:
        raise ValueError('invalid peer enemy collection')
    rows = {**metadata, 'entries': [], 'stored_entries': []}
    for identity, record in sorted(enemies.items()):
        if not isinstance(record, dict) or not record or record.keys() - {'registered', 'storage'}:
            raise ValueError('invalid peer enemy record')
        for source, row in record.items():
            if not isinstance(row, dict) or row.get('id') != identity:
                raise ValueError('peer enemy GUID does not match its record')
            rows['entries' if source == 'registered' else 'stored_entries'].append(row)
    _enemy_rows(rows)
    return rows


def _source_identities(rows):
    sources = {source: {} for source in ('registry', 'context', 'stored_context', 'live', 'active', 'storage')}
    for entry in rows['entries']:
        identity, kind = entry['id'], entry['kind_id']
        sources['registry'][identity] = (kind,)
        for source, key in (('context', 'context'), ('stored_context', 'stored'), ('live', 'live')):
            if entry[key]['present']:
                sources[source][identity] = (kind, entry[key]['inherit_id'])
        if entry['live'].get('active'):
            sources['active'][identity] = sources['live'][identity]
    for row in rows['stored_entries']:
        sources['storage'][row['id']] = (row['kind_id'], row['inherit_id'])
    return sources


def compare_enemy_snapshots(host_snapshot, guest_snapshot):
    """Compare two already verified v1 snapshots without deciding native application."""
    if host_snapshot['session_id'] != guest_snapshot['session_id']:
        raise ValueError('peer enemy snapshots belong to different transfer sessions')
    host, guest = (_snapshot_observations(snapshot) for snapshot in (host_snapshot, guest_snapshot))
    if any(host[key] != guest[key] for key in ('checkpoint_proof', 'scenario', 'location')):
        raise ValueError('peer enemy snapshots belong to different checkpoints or requests')

    host_sources, guest_sources = _source_identities(host), _source_identities(guest)
    report = {}
    for source, identities in host_sources.items():
        local = guest_sources[source]
        common = identities.keys() & local.keys()
        conflicts = {identity for identity in common if identities[identity] != local[identity]}
        report[source] = {
            'matched': len(common - conflicts),
            'host_only': sorted(identities.keys() - local.keys()),
            'guest_only': sorted(local.keys() - identities.keys()),
            'identity_mismatches': sorted(conflicts),
        }
    common_active = host_sources['active'].keys() & guest_sources['active'].keys()
    live_candidates = sorted(common_active.difference(report['active']['identity_mismatches']))
    return {'schema': 1, 'scope': SCOPE, 'checkpoint_match': True,
            'host_sequence': host_snapshot['sequence'], 'guest_sequence': guest_snapshot['sequence'],
            'sources': report, 'live_candidates': live_candidates}
