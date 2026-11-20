"""Validate fresh local receipts from the inherited-lock launcher and native barrier."""
import json
from pathlib import Path
import re
import time


def read_save_protection(data, *, now=None):
    now = time.time() if now is None else now
    data = Path(data)
    native = json.loads((data / 're2_coop_native_save_guard.json').read_text(encoding='utf-8'))
    launch = json.loads((data / 're2_coop_protected_launch.json').read_text(encoding='utf-8'))
    for value, source in ((native, 'steam_storage_guard'), (launch, 'inherited_save_locks')):
        if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
                or value.get('source') != source or value.get('active') is not True
                or type(value.get('at')) is not int or not 0 <= now - value['at'] <= 3
                or type(value.get('game_pid')) is not int or value['game_pid'] <= 0
                or not isinstance(value.get('run_id'), str)
                or not re.fullmatch('[0-9a-f]{32}', value['run_id'])
                or type(value.get('app_id')) is not int or value['app_id'] != 883710
                or type(value.get('build_id')) is not int or value['build_id'] != 11636119):
            raise ValueError('protected_launch_required: invalid or expired protection receipt')
    if (native.get('reason') != 'ok' or native.get('interface') != '014'
            or type(native.get('guarded_methods')) is not int or native['guarded_methods'] != 10
            or type(launch.get('locked_files')) is not int or launch['locked_files'] <= 0
            or native['game_pid'] != launch['game_pid'] or native['run_id'] != launch['run_id']):
        raise ValueError('protected_launch_required: protection binding mismatch')
    return {'game_pid': native['game_pid'], 'run_id': native['run_id']}
