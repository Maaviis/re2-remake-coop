"""Read only the owned native menu-pause proof for one admitted load."""
import re
import time


def held_pause(guard, request_id):
    hold = guard.get('load_hold')
    run = guard.get('guard_run_id')
    if (not isinstance(request_id, str) or not re.fullmatch('[0-9a-f]{32}', request_id)
            or not isinstance(run, str) or not 0 < len(run) <= 128
            or not isinstance(hold, dict) or type(hold.get('schema')) is not int or hold['schema'] != 1
            or hold.get('scope') != 'prepared_load_native_pause' or hold.get('available') is not True
            or hold.get('phase') != 'held' or hold.get('native_phase') != 'held' or hold.get('reason') != ''
            or type(hold.get('observed_at')) is not int or not 0 <= time.time() - hold['observed_at'] <= 3
            or hold.get('load_request_id') != request_id or hold.get('pause_id') != request_id
            or hold.get('guard_run_id') != run):
        raise ValueError('a fresh owned native pause for this prepared load is required')
    return hold['load_request_id'], hold['pause_id'], hold['guard_run_id']
