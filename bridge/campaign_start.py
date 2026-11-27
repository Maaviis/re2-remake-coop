"""Start and release the guarded campaign through either local entry point."""

from contextlib import ExitStack
import sys
import threading
import time

from lobby_sync import write_json
from load_witness import _read_json


def prepare_runtime_campaign(data, transport, profile, stop, *, namespace=None, revision=None, already_bound=False):
    from campaign_save_copy import check_managed_save
    from load_preflight import NativeSaveSource
    from readonly_save_control import read_active_guard
    from save_protection import active_save_identity, storage_guard_active

    allow_date = None
    if profile is not None:
        config = _read_json(profile, max_bytes=2048)
        if (not isinstance(config, dict) or set(config) != {'allow_save_date'}
                or not isinstance(config['allow_save_date'], str)):
            raise ValueError('Das lokale Kampagnenprofil braucht ein freigegebenes Spielstanddatum.')
        allow_date = config['allow_save_date']
    directory = transport.save_directory()
    if directory is None or not storage_guard_active(directory):
        raise ValueError('Eine aktive geschuetzte RE2-Spielstandkopie ist erforderlich.')
    if transport.cloud_status() not in ('cloud-app-disabled', 'cloud-account-disabled'):
        raise ValueError('Steam Cloud fuer RE2 muss deaktiviert sein.')
    if namespace is None:
        check_managed_save(directory, required=profile is None)
    identity = active_save_identity(transport, directory)
    if namespace is None:
        transport.protect_campaign()
    elif not already_bound:
        try:
            transport.prepare_new_game(revision, namespace)
        except OSError as exc:
            raise ValueError('RE2 hat den Befehl zur Ordnerfreigabe nicht beantwortet.') from exc
    deadline = time.monotonic() + 8
    while not stop.is_set() and time.monotonic() < deadline:
        try:
            guard = read_active_guard(data, protected=True, runtime_directory=directory)
        except (OSError, ValueError):
            time.sleep(0.1)
            continue
        binding = guard['protection']
        if namespace is not None and (binding.get('campaign_namespace') != namespace or
                                      guard.get('campaign_mount_ready') != namespace):
            time.sleep(0.1)
            continue
        if binding['game_pid'] == transport.game_pid and _native_load_ready(guard):
            if (not storage_guard_active(directory) or active_save_identity(transport, directory) != identity
                    or transport.cloud_status() not in ('cloud-app-disabled', 'cloud-account-disabled')):
                raise ValueError('Spielstandkopie oder Steam Cloud hat sich waehrend der Vorbereitung geaendert.')
            if namespace is None:
                check_managed_save(directory, required=profile is None)
                source = NativeSaveSource(data, directory, allow_date=allow_date, managed=profile is None)
            else:
                if transport.membership_revision() != revision or guard.get('new_game_supported') is not True:
                    raise ValueError('Lobby oder native Startfreigabe hat sich geändert.')
                source = NativeSaveSource(data, directory, allow_date=None, campaign_binding=binding)
            return source, campaign_stage(data, transport.game_pid, directory, allow_date, stop, sync_enemies=True,
                                          new_game_available=profile is None and guard.get('new_game_supported') is True)
        time.sleep(0.1)
    raise ValueError('RE2 hat den geschuetzten Kampagnenstart nicht bestaetigt.')


def campaign_stage(data, game_pid, save_directory, allow_date, stop, *, expected_slot4=None, expected_role=None,
                   sync_enemies=False, new_game_available=False):
    from readonly_save_control import arm, read_active_guard
    from save_catalog import SaveCatalog, saved_time

    worker = None

    def stage(slot):
        nonlocal worker
        if worker is not None and worker.is_alive():
            raise ValueError('Der vorige Kampagnenversuch wird noch abgeschlossen.')
        guard = read_active_guard(data, protected=True)
        if not _native_load_ready(guard):
            raise ValueError('RE2-Hauptmenue noch nicht ladebereit.')
        selected_date = allow_date
        new_game = isinstance(slot, dict)
        reference = None
        if new_game:
            if not stage.supports_new_game:
                raise ValueError('Dieser Starter ist nur für vorhandene Spielstände vorbereitet.')
        else:
            if selected_date is None:
                catalog = SaveCatalog(data / 're2_coop_save_catalog.json')
                selected_date = saved_time(catalog.select(slot)['timestamp']).date().isoformat()
            _check_save_pin(data, slot, selected_date, expected_slot4)
            if sync_enemies:
                reference = SaveCatalog(data / 're2_coop_save_catalog.json', allow_date=selected_date).select(slot)
        request = arm(data, slot, selected_date, load=True, require_receipt=True,
                      prepared_lobby=save_directory, expected_game_pid=game_pid, expected_role=expected_role)
        policy = _read_json(data / 're2_coop_save_policy.json', max_bytes=4096)
        scope = policy.get('lobby_load') if isinstance(policy, dict) else None
        role = scope.get('role') if isinstance(scope, dict) else None
        if (role not in ('H', 'G') or policy.get('id') != request or policy.get('schema') != (4 if new_game else 3)
                or new_game and (policy.get('new_game') != slot or 'reference' in policy)
                or scope.get('game_pid') != game_pid or expected_role is not None and role != expected_role):
            raise ValueError('Die vorbereitete Ladeanforderung wurde ersetzt.')
        if reference is not None and any(reference.get(key) != value for key, value in policy['reference'].items()):
            raise ValueError('Die Spielstandauswahl hat sich vor dem Kampagnenstart geaendert.')
        worker = threading.Thread(target=_confirm_loaded_campaign, daemon=True,
                                  args=(data, game_pid, role.encode('ascii'), policy, save_directory, stop),
                                  kwargs={'enemy_reference': reference} if reference is not None else {})
        worker.start()
        print('Geschuetzter Kampagnenstart vorgemerkt. Anfrage: ' + request, flush=True)
        return request

    stage.supports_new_game = new_game_available is True and sync_enemies and expected_slot4 is None
    return stage


def _native_load_ready(guard):
    if guard.get('denied_loads') != 0 or guard.get('allowed_load_calls') != 0:
        raise ValueError('Zum erneuten Laden zuerst RE2 und die Bridge neu starten.')
    return (guard.get('in_title') is True and guard.get('busy') is False
            and guard.get('load_menu_busy') is False
            and any(guard.get(key) is True for key in ('title_open', 'main_menu_busy', 'story_menu_busy')))


def _confirm_loaded_campaign(data, game_pid, role, policy, save_directory, stop, *, enemy_reference=None):
    from pose_bridge import lock_data_directory
    from prepared_checkpoint import PreparedCheckpoint
    from readonly_save_control import read_active_guard, wait_for_result
    from save_protection import active_save_identity, storage_guard_active
    from steam_pose_bridge import SteamPipe
    from steam_snapshot_transfer import CampaignReleaseLink, confirm_prepared_checkpoint

    request_id = policy['id']
    scope = policy['lobby_load']
    expected_lobby = 'owned' if role == b'H' else 'joined'
    combat_stop = threading.Event()
    combat_worker = None
    transitions = []
    link = None

    def record(phase, detail=''):
        if transitions and (transitions[-1]['phase'], transitions[-1]['detail']) == (phase, detail):
            return
        transition = {'at': int(time.time()), 'phase': phase, 'detail': detail}
        if link is not None:
            transition.update(heartbeat_sent=link.sent, heartbeat_received=link.received,
                              local_pipe_delays=link.local_timeouts)
            if link.last_peer_at is not None:
                transition['last_peer_ms_ago'] = int(1000 * (time.monotonic() - link.last_peer_at))
        transitions.append(transition)
        del transitions[:-16]
        try:
            write_json(data / 're2_coop_campaign_release_status.json', {
                'schema': 1, 'game_pid': game_pid, 'role': role.decode('ascii'),
                'load_request_id': request_id, 'attempt_id': scope['attempt_id'], 'transitions': transitions})
        except OSError:
            pass  # An unavailable diagnostic must never change release or rehold behavior.

    def verify_protection(transport):
        if (stop.is_set() or transport.lobby_status() != expected_lobby
                or transport.membership_revision() != scope['membership']['revision']
                or transport.cloud_status() not in ('cloud-app-disabled', 'cloud-account-disabled')
                or not storage_guard_active(save_directory)):
            raise ValueError('Steam-Lobby oder Schutz fuer den Kampagnenstart nicht mehr aktiv.')
        active_save_identity(transport, save_directory)
        if 'campaign_namespace' in policy.get('protection', {}):
            guard = read_active_guard(data, protected=True, runtime_directory=save_directory)
            if (guard['protection'] != policy['protection']
                    or guard.get('campaign_mount_ready') != policy['protection']['campaign_namespace']):
                raise ValueError('Die Schreibfreigabe für die Koop-Kampagne ist abgelaufen.')
        elif policy.get('schema') == 4:
            from campaign_save_copy import check_managed_save

            check_managed_save(save_directory, required=True)

    def verify_protected_resume():
        nonlocal combat_epoch
        verify_protection(pipe)
        if combat_pipe is not None:
            combat_pipe.receive()
            if (combat_pipe.role != role or combat_pipe.epoch is None
                    or combat_epoch is not None and combat_pipe.epoch != combat_epoch):
                raise OSError('Steam-Kampfkanal fuer den Kampagnenstart nicht mehr aktiv.')
            combat_epoch = combat_pipe.epoch

    def start_combat():
        nonlocal combat_worker
        combat_worker = threading.Thread(
            target=_follow_campaign_enemies, daemon=True,
            args=(combat_pipe, role, combat_epoch, data, request_id, scope, enemy_reference, combat_stop,
                  lambda: verify_protection(combat_pipe)))
        combat_worker.start()
        return combat_worker

    combat_pipe, combat_epoch = None, None
    try:
        record('waiting_for_native_pause')
        wait_for_result(data, request_id, load=True, timeout=90, require_pause=True, stop=stop)
        record('reading_checkpoint')
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
        with ExitStack() as locks:
            locks.enter_context(lock_data_directory(data, stream='snapshot'))
            pipe = SteamPipe(game_pid, stream='snapshot')
            if enemy_reference is not None:
                locks.enter_context(lock_data_directory(data, stream='combat'))
                combat_pipe = SteamPipe(game_pid, stream='combat')
            record('checking_peer_checkpoint')
            report = confirm_prepared_checkpoint(pipe, role, witness, scope['session_id'], scope['attempt_id'],
                                                 resume=verify_protected_resume, stop=stop)
            if (report['attempt_id'] != scope['attempt_id'] or report['checkpoint_match'] is not True
                    or report['native_pause_match'] is not True or report.get('resume_authorized') is not True):
                raise ValueError('Checkpoint-Bestaetigung passt nicht zum Laden.')
            if stop.is_set():
                return
            record('verifying_resume_protection')
            verify_protected_resume()
            release_id = report['release_id']
            link = CampaignReleaseLink(pipe, role, scope['session_id'], scope['attempt_id'], release_id)
            receipt = {'schema': 1, 'game_pid': game_pid, 'load_request_id': request_id,
                       'snapshot_epoch': link.epoch.hex(), 'release_id': release_id}
            write_json(data / 're2_coop_campaign_checkpoint.json', {
                'schema': 1, 'at': int(time.time()), 'game_pid': game_pid, 'load_request_id': request_id, **report})
            resume = {**receipt, 'at': int(time.time()), 'lobby_load': scope}
            if policy.get('schema') == 4:
                resume['new_game_world'] = report['new_game_world']
            write_json(data / 're2_coop_campaign_resume.json', resume)
            record('resume_requested')
            try:
                _watch_campaign_release(data, link, receipt, scope['guard_run_id'], save_directory, stop,
                                        record=record,
                                        start_combat=start_combat if combat_pipe is not None else None)
            finally:
                combat_stop.set()
                if combat_worker is not None:
                    combat_worker.join()
    except (OSError, ValueError, KeyError) as exc:
        if not stop.is_set():
            record('failed', str(exc))
            print('Kampagnenabgleich beendet: ' + str(exc), file=sys.stderr, flush=True)


def _watch_campaign_release(data, link, receipt, guard_run_id, save_directory, stop, *, record, start_combat=None):
    from readonly_save_control import read_active_guard

    deadline = time.monotonic() + 20
    paired = False
    peer_seen = False
    combat = None
    while not stop.is_set():
        try:
            guard = read_active_guard(data, protected=True, runtime_directory=save_directory)
        except (OSError, ValueError) as exc:
            record('guard_unavailable', str(exc))
            guard = {}
        hold = guard.get('load_hold')
        local_released = False
        if (isinstance(hold, dict) and hold.get('load_request_id') == receipt['load_request_id']
                and hold.get('pause_id') == receipt['load_request_id'] and hold.get('guard_run_id') == guard_run_id
                and guard['protection']['game_pid'] == receipt['game_pid']):
            if hold.get('phase') in ('lost', 'resume_failed', 'failed', 'rehold_pending',
                                     'reholding', 'interrupted', 'rehold_failed'):
                record('native_release_interrupted', hold.get('release_loss_reason') or hold.get('reason', ''))
                raise ValueError(hold.get('reason') or 'Native Kampagnenfreigabe unterbrochen.')
            local_released = (hold.get('phase') == 'released' and hold.get('native_phase') == 'released'
                              and hold.get('release') == {'id': receipt['release_id'],
                                                          'snapshot_epoch': receipt['snapshot_epoch']})
            if local_released and isinstance(hold.get('campaign'), dict):
                record('paired')
                if not paired:
                    print('Gemeinsamer Checkpoint und native Freigabe beider Instanzen bestaetigt.', flush=True)
                    paired = True
                    if start_combat is not None:
                        combat = start_combat()
                deadline = time.monotonic() + 4
            elif local_released:
                record('peer_release_received' if peer_seen else 'local_released')
            else:
                record('waiting_for_local_release', str(hold.get('phase')) + '/' + str(hold.get('native_phase')))
        elif guard:
            record('waiting_for_pause_binding')
        if combat is not None and not combat.is_alive() and not stop.is_set():
            raise OSError('Steam-Kampfkanal unterbrochen.')
        now = time.monotonic()
        if now >= deadline:
            raise TimeoutError('Native Bestaetigung zum Fortsetzen fehlt.')
        if link.poll(local_released, now):
            write_json(data / 're2_coop_campaign_peer_release.json', {**receipt, 'at': int(time.time())})
            if not peer_seen:
                peer_seen = True
                record('peer_release_received')
        stop.wait(0.2)


def _follow_campaign_enemies(pipe, role, epoch, data, request_id, scope, reference, stop, verify_protection):
    from campaign_hits import CampaignHitFiles
    from enemy_live import EnemyLiveFeed
    from guest_enemy_file import GuestEnemyFile
    from steam_snapshot_transfer import follow_enemy_live

    deadline = time.monotonic() + 10

    def acknowledge_exchange():
        nonlocal deadline
        deadline = time.monotonic() + 10

    class CampaignStop:
        next_check = 0.0

        def is_set(self):
            if stop.is_set():
                return True
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError('Keine bestaetigte Uebertragung auf dem Steam-Kampfkanal.')
            if now >= self.next_check:
                verify_protection()
                self.next_check = now + 0.5
            return False

    path = data / 're2_coop_campaign_enemy_link.json'

    def status(phase, detail=''):
        write_json(path, {'schema': 1, 'at': int(time.time()), 'phase': phase, 'detail': detail,
                          'attempt_id': scope['attempt_id'], 'role': role.decode('ascii')})

    try:
        verify_protection()
        feed = EnemyLiveFeed(data, request_id, reference, campaign=True, death_evidence=True)
        guest = (GuestEnemyFile(data, scope['session_id'], campaign_attempt=scope['attempt_id'])
                 if role == b'G' else None)
        hits = CampaignHitFiles(data, request_id, scope['attempt_id'])
        if role == b'H':
            hits.withdraw()
        status('following')
        try:
            follow_enemy_live(pipe, role, scope['session_id'], scope['attempt_id'], feed, None,
                              publish=guest.publish if guest else None, campaign=True, death_evidence=True, stop=CampaignStop(),
                              expected_epoch=epoch, hits=hits, on_exchange=acknowledge_exchange)
        finally:
            if role == b'H':
                hits.withdraw()
        status('stopped')
    except (OSError, ValueError, KeyError) as exc:
        if stop.is_set():
            status('stopped')
        else:
            status('interrupted', str(exc))
            print('Kampagnen-Gegnerabgleich beendet: ' + str(exc), file=sys.stderr, flush=True)


def _check_save_pin(data, slot, allow_date, expected):
    from save_catalog import SaveCatalog

    if expected:
        reference = SaveCatalog(data / 're2_coop_save_catalog.json', allow_date=allow_date).select(slot)
        if slot != 'scenario:4' or reference['timestamp'] != expected:
            raise ValueError('Slot 4 stimmt nicht mit dem freigegebenen alten Spielstand ueberein.')
