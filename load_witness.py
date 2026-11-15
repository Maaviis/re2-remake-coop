"""Validate fresh, scoped native load-header and inventory-core evidence."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import time

from save_catalog import SaveCatalog, validate_reference
from sync_model import state_digest


SCOPE = 'load_header_and_inventory_core'
MAX_BYTES = 131072
MAX_AGE = 3
MAX_LOAD_AGE = 120
GUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
TOKEN = re.compile(r'[0-9a-f]{32}')
INTEGER_FIELDS = {'stock_index', 'slot_type', 'item_id', 'weapon_type', 'weapon_parts', 'bullet_id', 'number'}
BOOLEAN_FIELDS = {'has_stock', 'blank', 'force_blank', 'fat_slot', 'dead_slot', 'infinite'}


def _integer(value, low=0, high=2**53 - 1):
    return type(value) is int and low <= value <= high


def _slot(value, *, absent=False):
    if absent and isinstance(value, dict) and set(value) == {'present'} and value['present'] is False:
        return
    if (not isinstance(value, dict) or set(value) != INTEGER_FIELDS | BOOLEAN_FIELDS | {'present'}
            or value['present'] is not True
            or any(not _integer(value[name], -(2**31), 2**32 - 1) for name in INTEGER_FIELDS)
            or any(type(value[name]) is not bool for name in BOOLEAN_FIELDS)):
        raise ValueError('invalid native inventory slot')


def _state(value):
    if not isinstance(value, dict) or set(value) != {'checkpoint', 'inventory'}:
        raise ValueError('invalid native evidence state')
    checkpoint, inventory = value['checkpoint'], value['inventory']
    if (not isinstance(checkpoint, dict) or set(checkpoint) != {
            'scenario', 'survivor', 'difficulty', 'location', 'saved_map', 'game_guid', 'save_guid'}
            or any(not _integer(checkpoint[name], 0, 2**31 - 1)
                   for name in ('scenario', 'survivor', 'difficulty', 'location', 'saved_map'))
            or any(not isinstance(checkpoint[name], str) or not GUID.fullmatch(checkpoint[name])
                   for name in ('game_guid', 'save_guid'))):
        raise ValueError('invalid native load header')
    if (not isinstance(inventory, dict) or set(inventory) != {
            'capacity', 'slot_count', 'slots', 'survivor', 'role', 'equipped'}
            or not _integer(inventory['slot_count'], 0, 64)
            or not _integer(inventory['capacity'], 0, inventory['slot_count'])
            or any(not _integer(inventory[name], 0, 2**31 - 1) for name in ('survivor', 'role'))):
        raise ValueError('invalid native inventory')
    if inventory['slot_count'] == 0 and inventory['slots'] is None:
        inventory['slots'] = []  # REFramework's empty Lua sequence is JSON null.
    if not isinstance(inventory['slots'], list) or len(inventory['slots']) != inventory['slot_count']:
        raise ValueError('native slot count mismatch')
    for slot in inventory['slots']:
        _slot(slot)
    equipped = inventory['equipped']
    if not isinstance(equipped, dict) or set(equipped) != {'main', 'sub', 'personal'}:
        raise ValueError('invalid native equipped slots')
    for slot in equipped.values():
        _slot(slot, absent=True)


def _read_json(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('native evidence exceeds its byte limit')
    return json.loads(path.read_text(encoding='utf-8'))


class LoadStateFile:
    def __init__(self, data):
        self.data = Path(data)
        self.accepted = None
        self.load_request_id = self.load_run_id = None

    def read(self, *, now=None):
        now = time.time() if now is None else now
        value = _read_json(self.data / 're2_coop_load_state.json')
        fields = {'schema', 'source', 'tdb', 'run_id', 'sequence', 'observed_at', 'scope', 'available', 'reason'}
        if (not isinstance(value, dict) or not fields <= value.keys() or value.keys() - fields - {'state'}
                or type(value['schema']) is not int or value['schema'] != 1 or value['source'] != 're2'
                or type(value['tdb']) is not int or value['tdb'] != 70 or value['scope'] != SCOPE
                or not isinstance(value['run_id'], str) or not 0 < len(value['run_id']) <= 128
                or not _integer(value['sequence'], 1) or not _integer(value['observed_at'], 1)
                or not 0 <= now - value['observed_at'] <= MAX_AGE or type(value['available']) is not bool
                or not isinstance(value['reason'], str)):
            raise ValueError('unsupported, malformed or expired native evidence')
        if value['available']:
            if value['reason'] != 'ok':
                raise ValueError('available evidence has an error')
            _state(value.get('state'))
        elif value.get('state') is not None:
            raise ValueError('unavailable evidence contains state')
        previous = self.accepted
        if previous and previous['run_id'] == value['run_id']:
            if (value['sequence'] < previous['sequence']
                    or value['sequence'] == previous['sequence'] and value != previous):
                raise ValueError('native evidence rolled back or changed without a new sequence')
        self.accepted = deepcopy(value)
        return deepcopy(value)

    def for_load(self, request_id, reference, *, now=None):
        now = time.time() if now is None else now
        if not isinstance(request_id, str) or not TOKEN.fullmatch(request_id):
            raise ValueError('native load request ID required')
        validate_reference(reference)
        sample = self.read(now=now)
        guard = _read_json(self.data / 're2_coop_save_guard.json')
        if (not isinstance(guard, dict) or type(guard.get('schema')) is not int or guard['schema'] != 1
                or guard.get('active') is not True or type(guard.get('hooks')) is not int or guard['hooks'] != 26
                or not _integer(guard.get('at'), 1) or not 0 <= now - guard['at'] <= MAX_AGE
                or guard.get('load_request_id') != request_id or guard.get('policy_id') != request_id
                or guard.get('load_phase') != 'scene_loaded' or guard.get('load_error') != ''
                or type(guard.get('denied_loads')) is not int or guard['denied_loads'] != 0
                or not _integer(guard.get('allowed_load_calls'), 1) or guard.get('writes') not in (None, {})
                or type(guard.get('load_index')) is not int or guard['load_index'] != reference['slot_id']
                or type(guard.get('allowed_slot')) is not int or guard['allowed_slot'] != reference['slot_id']
                or not _integer(guard.get('load_started_at'), 1)
                or not 0 <= now - guard['load_started_at'] <= MAX_LOAD_AGE
                or not sample['available'] or sample['observed_at'] <= guard['load_started_at']
                or sample['state']['checkpoint']['scenario'] != reference['scenario']):
            raise ValueError('no fresh scoped evidence for this native load')
        zero_guid = '00000000-0000-0000-0000-000000000000'
        if any(sample['state']['checkpoint'][key] == zero_guid for key in ('game_guid', 'save_guid')):
            raise ValueError('native loaded checkpoint identity is missing')
        if self.load_request_id == request_id and self.load_run_id != sample['run_id']:
            raise ValueError('native observer run changed for the same load')
        self.load_request_id, self.load_run_id = request_id, sample['run_id']
        return {'schema': 1, 'scope': SCOPE, 'load_request_id': request_id, 'observer_run_id': sample['run_id'],
                'observed_at': sample['observed_at'], 'evidence_digest': state_digest(sample['state']),
                'state': deepcopy(sample['state'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--request-id')
    parser.add_argument('--save-slot')
    parser.add_argument('--allow-save-date')
    args = parser.parse_args()
    if args.request_id is not None and (args.save_slot is None or args.allow_save_date is None):
        parser.error('--request-id requires --save-slot and --allow-save-date')
    try:
        reader = LoadStateFile(args.data)
        if args.request_id is not None:
            reference = SaveCatalog(args.data / 're2_coop_save_catalog.json', allow_date=args.allow_save_date).select(args.save_slot)
            evidence = reader.for_load(args.request_id, reference)
            print(json.dumps({key: value for key, value in evidence.items() if key != 'state'}))
        else:
            sample = reader.read()
            print(json.dumps({key: value for key, value in sample.items() if key != 'state'}))
            return 0 if sample['available'] else 1
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        print(f'Native evidence unavailable: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
