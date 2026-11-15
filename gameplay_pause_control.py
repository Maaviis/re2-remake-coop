"""Bounded native gameplay-pause probe for an isolated, guarded RE2 test installation."""

import argparse
import json
import math
from pathlib import Path
import re
import secrets
import sys
import time

from inventory_witness import InventoryStateFile
from lobby_sync import write_json
from readonly_save_control import read_active_guard
from save_catalog import SaveCatalog


TOKEN = re.compile(r'[0-9a-f]{32}')
CLOCKS = {'get_SystemElapsedTime', 'get_GameElapsedTime', 'get_ActualPlayingTime',
          'get_ActualRecordTime', 'get_InSceneTime', 'get_PauseSpendingTime'}
PHASES = {'idle', 'requesting', 'held', 'returning', 'released', 'lost', 'failed'}


def _token(value):
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None


def read_status(data, *, now=None):
    now = time.time() if now is None else now
    path = Path(data) / 're2_coop_gameplay_pause.json'
    if path.stat().st_size > 65536:
        raise ValueError('pause status exceeds its byte limit')
    value = json.loads(path.read_text(encoding='utf-8'))
    fields = {'schema', 'source', 'tdb', 'scope', 'run_id', 'sequence', 'observed_at', 'pause_id', 'phase',
              'available', 'reason', 'command_id', 'command_error', 'release_id'}
    if (not isinstance(value, dict) or not fields <= value.keys() or value.keys() - fields - {'clocks'}
            or type(value['schema']) is not int or value['schema'] != 1 or value['source'] != 're2'
            or type(value['tdb']) is not int or value['tdb'] != 70 or value['scope'] != 'native_gameplay_pause'
            or not isinstance(value['run_id'], str) or not 0 < len(value['run_id']) <= 128
            or type(value['sequence']) is not int or not 1 <= value['sequence'] <= 2**53 - 1
            or type(value['observed_at']) is not int or not 0 <= now - value['observed_at'] <= 3
            or not isinstance(value['phase'], str) or value['phase'] not in PHASES
            or type(value['available']) is not bool
            or any(not isinstance(value[key], str) for key in ('reason', 'command_error'))
            or any(value[key] != '' and not _token(value[key]) for key in ('pause_id', 'command_id'))
            or value['release_id'] not in ('', 'deadline') and not _token(value['release_id'])):
        raise ValueError('invalid or stale native pause status')
    if value['available'] and (value['phase'] not in ('idle', 'held', 'released') or value['reason'] != ''):
        raise ValueError('available native pause status is inconsistent')
    clocks = value.get('clocks')
    if (clocks is not None and (not isinstance(clocks, dict) or set(clocks) != CLOCKS
            or any(not isinstance(v, str) or not re.fullmatch(r'0|[1-9][0-9]{0,19}', v)
                   or int(v) >= 2**64 for v in clocks.values()))
            or value['available'] and clocks is None):
        raise ValueError('invalid native pause clocks')
    return value


def submit(data, action, *, load_id=None, allow_date=None, seconds=10, pause_id=None):
    data = Path(data)
    status = read_status(data)
    value = {'schema': 1, 'id': secrets.token_hex(16), 'at': int(time.time()), 'action': action}
    if action == 'pause':
        if not _token(load_id) or allow_date is None or type(seconds) is not int or not 2 <= seconds <= 15:
            raise ValueError('pause requires a native load ID, allowed date and 2..15 seconds')
        if status['available'] is not True or status['phase'] not in ('idle', 'released'):
            raise ValueError('native pause probe is not ready for a new request')
        guard = read_active_guard(data)
        slot = guard.get('load_index')
        if type(slot) is not int or not 0 <= slot <= 20:
            raise ValueError('native loaded slot required')
        reference = SaveCatalog(data / 're2_coop_save_catalog.json', allow_date=allow_date).select(f'scenario:{slot}')
        InventoryStateFile(data).for_load(load_id, reference)
        value.update(load_request_id=load_id, seconds=seconds)
    elif action == 'return':
        if not _token(pause_id) or status['pause_id'] != pause_id or status['phase'] != 'held':
            raise ValueError('return requires the currently owned native pause ID')
        value['pause_id'] = pause_id
    else:
        raise ValueError('unknown native pause action')
    write_json(data / 're2_coop_pause_command.json', value)
    return value['id']


def wait_for_result(data, command_id, *, action, pause_id=None, timeout=5):
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            status = read_status(data)
        except (OSError, ValueError):
            status = None
        if status is not None:
            if status['command_id'] == command_id and status['command_error']:
                raise ValueError(status['command_error'])
            own_id = command_id if action == 'pause' else pause_id
            if status['pause_id'] == own_id:
                if status['phase'] in ('lost', 'failed'):
                    raise ValueError(status['reason'] or 'native pause failed')
                if status['available'] and (action == 'pause' and status['phase'] == 'held'
                        or action == 'return' and status['phase'] == 'released' and status['release_id'] == command_id):
                    return status
        time.sleep(min(.1, remaining))
    raise TimeoutError('native pause result was not confirmed within the wait limit')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('action', choices=('status', 'pause', 'return'))
    parser.add_argument('--load-id')
    parser.add_argument('--allow-save-date')
    parser.add_argument('--seconds', type=int, default=10)
    parser.add_argument('--pause-id')
    parser.add_argument('--wait', type=float)
    args = parser.parse_args()
    if args.wait is not None and (not math.isfinite(args.wait) or not 0 < args.wait <= 30 or args.action == 'status'):
        parser.error('--wait requires a native action and 0 < seconds <= 30')
    try:
        if args.action == 'status':
            value = read_status(args.data)
        else:
            command = submit(args.data, args.action, load_id=args.load_id, allow_date=args.allow_save_date,
                             seconds=args.seconds, pause_id=args.pause_id)
            print(f'Queued {args.action} command {command}', flush=True)
            value = (wait_for_result(args.data, command, action=args.action, pause_id=args.pause_id, timeout=args.wait)
                     if args.wait is not None else {'command_id': command})
        print(json.dumps(value))
    except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        print(f'Native pause unavailable: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
