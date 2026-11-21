"""Start and release the guarded campaign through either local entry point."""

import sys
import threading
import time

from lobby_sync import write_json
from load_witness import _read_json


def prepare_runtime_campaign(data, transport, profile, stop):
    from load_preflight import NativeSaveSource
    from readonly_save_control import read_active_guard
    from save_protection import active_save_identity, storage_guard_active

    config = _read_json(profile, max_bytes=2048)
    if not isinstance(config, dict) or set(config) != {'allow_save_date'} or not isinstance(config['allow_save_date'], str):
        raise ValueError('Das lokale Kampagnenprofil braucht ein freigegebenes Spielstanddatum.')
    allow_date = config['allow_save_date']
    directory = transport.save_directory()
    if directory is None or not storage_guard_active(directory):
        raise ValueError('Eine aktive geschuetzte RE2-Spielstandkopie ist erforderlich.')
    if transport.cloud_status() not in ('cloud-app-disabled', 'cloud-account-disabled'):
        raise ValueError('Steam Cloud fuer RE2 muss deaktiviert sein.')
    identity = active_save_identity(transport, directory)
    source = NativeSaveSource(data, directory, allow_date=allow_date)
    transport.protect_campaign()
    deadline = time.monotonic() + 8
    while not stop.is_set() and time.monotonic() < deadline:
        try:
            guard = read_active_guard(data, protected=True, runtime_directory=directory)
        except (OSError, ValueError):
            time.sleep(0.1)
            continue
        if guard['protection']['game_pid'] == transport.game_pid and _native_load_ready(guard):
            if (not storage_guard_active(directory) or active_save_identity(transport, directory) != identity
                    or transport.cloud_status() not in ('cloud-app-disabled', 'cloud-account-disabled')):
                raise ValueError('Spielstandkopie oder Steam Cloud hat sich waehrend der Vorbereitung geaendert.')
            return source, campaign_stage(data, transport.game_pid, directory, allow_date, stop)
        time.sleep(0.1)
    raise ValueError('RE2 hat den geschuetzten Kampagnenstart nicht bestaetigt.')


def campaign_stage(data, game_pid, save_directory, allow_date, stop, *, expected_slot4=None, expected_role=None):
    from readonly_save_control import arm, read_active_guard

    worker = None

    def stage(slot):
        nonlocal worker
        if worker is not None and worker.is_alive():
            raise ValueError('Der vorige Kampagnenversuch wird noch abgeschlossen.')
        guard = read_active_guard(data, protected=True)
        if not _native_load_ready(guard):
            raise ValueError('RE2-Hauptmenue noch nicht ladebereit.')
        _check_save_pin(data, slot, allow_date, expected_slot4)
        request = arm(data, slot, allow_date, load=True, require_receipt=True,
                      prepared_lobby=save_directory, expected_game_pid=game_pid, expected_role=expected_role)
        policy = _read_json(data / 're2_coop_save_policy.json', max_bytes=4096)
        scope = policy.get('lobby_load') if isinstance(policy, dict) else None
        role = scope.get('role') if isinstance(scope, dict) else None
        if (role not in ('H', 'G') or policy.get('id') != request or policy.get('schema') != 3
                or scope.get('game_pid') != game_pid or expected_role is not None and role != expected_role):
            raise ValueError('Die vorbereitete Ladeanforderung wurde ersetzt.')
        worker = threading.Thread(target=_confirm_loaded_campaign, daemon=True,
                                  args=(data, game_pid, role.encode('ascii'), policy, save_directory, stop))
        worker.start()
        print('Geschuetzter Kampagnenstart vorgemerkt. Anfrage: ' + request, flush=True)
        return request

    return stage


def _native_load_ready(guard):
    if guard.get('denied_loads') != 0 or guard.get('allowed_load_calls') != 0:
        raise ValueError('Zum erneuten Laden zuerst RE2 und die Bridge neu starten.')
    return (guard.get('in_title') is True and guard.get('busy') is False
            and guard.get('load_menu_busy') is False
            and any(guard.get(key) is True for key in ('title_open', 'main_menu_busy', 'story_menu_busy')))


def _confirm_loaded_campaign(data, game_pid, role, policy, save_directory, stop):
    from pose_bridge import lock_data_directory
    from prepared_checkpoint import PreparedCheckpoint
    from readonly_save_control import read_active_guard, wait_for_result
    from save_protection import active_save_identity, storage_guard_active
    from steam_pose_bridge import SteamPipe
    from steam_snapshot_transfer import confirm_prepared_checkpoint

    request_id = policy['id']
    scope = policy['lobby_load']
    expected_lobby = 'owned' if role == b'H' else 'joined'

    def verify_protected_resume():
        if (stop.is_set() or pipe.lobby_status() != expected_lobby
                or pipe.membership_revision() != scope['membership']['revision']
                or pipe.cloud_status() not in ('cloud-app-disabled', 'cloud-account-disabled')
                or not storage_guard_active(save_directory)):
            raise ValueError('Steam-Lobby oder Schutz fuer den Kampagnenstart nicht mehr aktiv.')
        active_save_identity(pipe, save_directory)

    try:
        wait_for_result(data, request_id, load=True, timeout=90, require_pause=True, stop=stop)
        witness = PreparedCheckpoint(data, game_pid, role.decode('ascii'))
        deadline = time.monotonic() + 10
        # The native pause and the independent checkpoint reader publish on
        # different updates. Do not spend the first peer request on that gap.
        while not stop.is_set():
            try:
                witness.capture(scope['session_id'])
                break
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        if stop.is_set():
            return
        with lock_data_directory(data, stream='snapshot'):
            pipe = SteamPipe(game_pid, stream='snapshot')
            report = confirm_prepared_checkpoint(pipe, role, witness, scope['session_id'], scope['attempt_id'],
                                                 resume=verify_protected_resume, stop=stop)
        if (report['attempt_id'] != scope['attempt_id'] or report['checkpoint_match'] is not True
                or report['native_pause_match'] is not True or report.get('resume_authorized') is not True):
            raise ValueError('Checkpoint-Bestaetigung passt nicht zum Laden.')
        if stop.is_set():
            return
        verify_protected_resume()
        write_json(data / 're2_coop_campaign_resume.json', {'schema': 1, 'at': int(time.time()),
              'load_request_id': request_id, 'lobby_load': scope, 'snapshot_epoch': pipe.epoch.hex()})
        write_json(data / 're2_coop_campaign_checkpoint.json', {'schema': 1, 'at': int(time.time()),
              'game_pid': game_pid, 'load_request_id': request_id, **report})
        deadline = time.monotonic() + 10
        while not stop.is_set():
            try:
                guard = read_active_guard(data, protected=True)
            except (OSError, ValueError):
                guard = {}
            hold = guard.get('load_hold')
            if (isinstance(hold, dict) and hold.get('load_request_id') == request_id
                    and hold.get('pause_id') == request_id and hold.get('guard_run_id') == scope['guard_run_id']
                    and guard['protection']['game_pid'] == game_pid):
                if hold.get('phase') == 'released' and hold.get('native_phase') == 'released':
                    print('Gemeinsamer Checkpoint bestaetigt. Lokale native Pause aufgehoben.', flush=True)
                    return
                if hold.get('phase') in ('lost', 'resume_failed', 'failed'):
                    raise ValueError(hold.get('reason') or 'Lokale Pause konnte nicht aufgehoben werden.')
            if time.monotonic() >= deadline:
                raise TimeoutError('Native Bestaetigung zum Fortsetzen fehlt.')
            time.sleep(0.2)
    except (OSError, ValueError, KeyError) as exc:
        if not stop.is_set():
            print('Gemeinsamer Checkpoint abgebrochen: ' + str(exc), file=sys.stderr, flush=True)


def _check_save_pin(data, slot, allow_date, expected):
    from save_catalog import SaveCatalog

    if expected:
        reference = SaveCatalog(data / 're2_coop_save_catalog.json', allow_date=allow_date).select(slot)
        if slot != 'scenario:4' or reference['timestamp'] != expected:
            raise ValueError('Slot 4 stimmt nicht mit dem freigegebenen alten Spielstand ueberein.')
