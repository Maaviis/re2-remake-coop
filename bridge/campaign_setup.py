"""Prepare a Steam campaign copy after the title process has closed."""

import argparse
import os
import secrets
from pathlib import Path
import subprocess
import sys
import time

from campaign_save_copy import check_managed_save, open_save_session
from lobby_sync import write_json
from load_witness import _read_json
from pose_bridge import lock_data_directory
from save_protection import storage_guard_active, storage_guard_recovery_pending


CLOUD_OFF = ('cloud-app-disabled', 'cloud-account-disabled')
STATUS = 're2_coop_campaign_setup.json'
PACKAGE = Path(__file__).resolve().parent


def require_steam_save(pipe, expected=None):
    directory = pipe.save_directory()
    if directory is None:
        raise ValueError('Steam konnte den aktiven RE2-Spielstandordner nicht bestimmen.')
    if expected is not None and expected != directory:
        raise ValueError('Das aktive Steam-Konto hat sich geaendert.')
    if pipe.cloud_status() not in CLOUD_OFF:
        raise ValueError('Steam Cloud fuer RE2 deaktivieren und danach erneut vorbereiten.')
    return directory


class CampaignSetup:
    def __init__(self, data, pipe, game_exit):
        self.data = data
        self.pipe = pipe
        self.game_exit = game_exit
        self.worker = None
        self.startup_failure = _recent_failure(data)
        self.worker_failure = None
        self.live_guard = None

    def enable_new(self, revision):
        from campaign_start import prepare_runtime_campaign

        if self.pipe.membership_revision() != revision or self.pipe.lobby_status() not in ('owned', 'joined'):
            raise ValueError('Die Steam-Lobby hat sich geändert. Bitte erneut vorbereiten.')
        directory = require_steam_save(self.pipe)
        _steam_for_save(directory)
        self._ensure_live_guard(directory)
        try:
            existing = self.pipe.current_campaign(revision)
        except OSError as exc:
            raise ValueError('Die aktive Kampagnenbindung war über die Lobby-Bridge nicht abrufbar.') from exc
        if existing is not None:
            from readonly_save_control import read_active_guard

            guard = read_active_guard(self.data, protected=True, runtime_directory=directory)
            if (guard['protection']['game_pid'] != self.pipe.game_pid or guard.get('busy') is not False
                    or guard.get('in_title') is not True or guard.get('campaign_mount_ready') != existing
                    or guard['protection'].get('campaign_namespace') != existing):
                raise ValueError('Die bestehende Kampagne ist noch aktiv. Im Titelmenü die Lobby verlassen und neu öffnen.')
        token = existing or secrets.token_hex(16)
        try:
            return prepare_runtime_campaign(self.data, self.pipe, None, self.game_exit,
                                            namespace=token, revision=revision, already_bound=existing is not None)
        except (ValueError, OSError) as exc:
            if not existing:
                try:
                    self.pipe.revoke_new_game(token)
                except (ValueError, OSError) as revoke_error:
                    raise ValueError(f'{exc} Auch der Widerruf ist unbestätigt. Lobby verlassen.') from revoke_error
            raise

    def _ensure_live_guard(self, directory):
        """Use the existing PID-bound ACL helper; keep it until the game exits."""
        if not storage_guard_active(directory):
            if self.live_guard is None or self.live_guard.poll() is not None:
                command, env = _guard_command(directory)
                self.live_guard = subprocess.Popen(
                    [*command, '-GameExecutable', str(PACKAGE.parent / 're2.exe'),
                     '-GameProcessId', str(self.pipe.game_pid)], env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 15
            while not storage_guard_active(directory):
                if self.live_guard.poll() is not None or self.game_exit.is_set() or time.monotonic() >= deadline:
                    raise ValueError('Einzelspieler-Dateien konnten nicht gesperrt werden. Offene Speicherzugriffe prüfen.')
                time.sleep(0.1)

    def exchange_checkpoint(self, scope, nonce, stop):
        """Secure the fresh Steam title before serving or receiving its selected archive."""
        from checkpoint_transfer_binding import ArchiveTransferBinding
        from readonly_save_control import read_active_guard, read_connected_lobby
        from save_protection import active_save_identity
        from steam_pose_bridge import SteamPipe

        pipe = SteamPipe(self.pipe.game_pid, stream='snapshot')
        directory = require_steam_save(pipe)
        _steam_for_save(directory)
        identity = active_save_identity(pipe, directory)
        role = scope['role']
        expected = {'game_pid': pipe.game_pid, 'role': role, 'membership': scope['membership'],
                    'session_id': scope['session_id']}
        selection = {k: scope['choice'][k] for k in ('namespace', 'digest')}

        def confirm():
            if stop.is_set() or self.game_exit.is_set():
                raise ValueError('Checkpoint-Übertragung abgebrochen.')
            current, lobby = read_connected_lobby(self.data)
            if (current != expected or lobby['revision'] != scope['revision']
                    or lobby['settings'].get('coop_checkpoint') != scope['choice']
                    or lobby['save_slot'] is not None or 'new_game' in lobby or 'save_ref' in lobby
                    or pipe.membership_revision() != scope['membership']['revision']
                    or pipe.lobby_status() != ('owned' if role == 'H' else 'joined')
                    or require_steam_save(pipe, directory) != directory or active_save_identity(pipe, directory) != identity):
                raise ValueError('Die Steam-Lobby oder Archivwahl hat sich geändert.')

        confirm()
        self._ensure_live_guard(directory)
        confirm()
        # A normal Steam launch publishes its Lua guard only after the native lock starts.
        pipe.protect_campaign()
        deadline = time.monotonic() + 8
        while True:
            confirm()
            try:
                guard = read_active_guard(self.data, protected=True, runtime_directory=directory)
            except (OSError, ValueError):
                guard = {}
            if guard.get('runtime_protection') is True and guard['protection']['game_pid'] == pipe.game_pid:
                break
            if time.monotonic() >= deadline:
                raise ValueError('RE2 hat den nativen Spielstandschutz nicht bestätigt.')
            stop.wait(.1)
        if (any(type(guard.get(k)) is not int or guard[k] != 0 for k in ('allowed_load_calls', 'denied_loads'))
                or guard.get('writes') not in (None, {})):
            raise ValueError('Dieser Spiellauf hat bereits einen Lade- oder Schreibversuch. RE2 neu starten und erneut verbinden.')
        if (guard.get('in_title') is not True
                or any(guard.get(k) is not False for k in ('has_player', 'busy', 'loading_flow'))):
            raise ValueError('Checkpoint-Übertragung benötigt das geschützte Titelmenü.')
        binding = ArchiveTransferBinding(self.data, pipe, directory, selection, role.encode())
        if binding.scope != expected or binding.revision != scope['revision'] or binding.choice != scope['choice']:
            raise ValueError('Archivtransfer gehört nicht mehr zur ausgehandelten Auswahl.')
        return binding.exchange(nonce, stop=stop)

    def enable_checkpoint(self, selection, revision, *, cleanup=None):
        """Mount and import one selected archive without generating another workspace.

        This internal Continue preparation returns no load or release permission.
        The caller must first receive the immutable archive on the guest.
        """
        from checkpoint_workspace import CheckpointWorkspace, selected_archive
        from readonly_save_control import read_active_guard, read_connected_lobby
        from save_protection import active_save_identity

        selection = dict(selection)
        directory = require_steam_save(self.pipe)
        _steam_for_save(directory)
        identity = active_save_identity(self.pipe, directory)
        archive, manifest, choice = selected_archive(directory, selection)
        scope, lobby = read_connected_lobby(self.data)
        lobby_revision = lobby['revision']

        def confirm(*, protected=False):
            current_scope, current = read_connected_lobby(self.data)
            guard = read_active_guard(self.data, protected=protected, runtime_directory=directory)
            if self.game_exit.is_set():
                raise ValueError('checkpoint_setup_cancelled')
            if (current_scope != scope or scope['game_pid'] != self.pipe.game_pid
                    or type(revision) is not int or scope['membership']['revision'] != revision
                    or self.pipe.membership_revision() != revision
                    or self.pipe.lobby_status() != ('owned' if scope['role'] == 'H' else 'joined')):
                raise ValueError('checkpoint_setup_lobby_changed')
            if (current['revision'] != lobby_revision or current['settings'].get('coop_checkpoint') != choice
                    or current['save_slot'] is not None or 'new_game' in current or 'save_ref' in current):
                raise ValueError('checkpoint_setup_selection_changed')
            require_steam_save(self.pipe, directory)
            if active_save_identity(self.pipe, directory) != identity:
                raise ValueError('checkpoint_setup_profile_changed')
            if (guard.get('in_title') is not True
                    or guard.get('has_player') is not False or guard.get('loading_flow') is not False
                    or guard.get('busy') is not False
                    or not any(guard.get(key) is True for key in ('title_open', 'main_menu_busy', 'story_menu_busy'))):
                raise ValueError('checkpoint_setup_title_not_ready')
            if any(type(guard.get(key)) is not int or guard[key] != 0
                   for key in ('allowed_load_calls', 'denied_loads')):
                raise ValueError('checkpoint_setup_load_already_attempted')
            if guard.get('writes') not in (None, {}):
                raise ValueError('checkpoint_setup_blocked_write')
            return guard

        confirm()
        self._ensure_live_guard(directory)
        guard = confirm()
        existing = self.pipe.current_campaign(revision)
        if existing is not None:
            guard = confirm(protected=True)
            if (guard.get('runtime_protection') is not True or guard['protection'].get('campaign_namespace') != existing
                    or guard.get('campaign_mount_ready') != existing):
                raise ValueError('The existing checkpoint workspace is not bound to this protected title')
        elif (guard.get('protection') or {}).get('campaign_namespace') is not None:
            raise ValueError('The native checkpoint workspace binding is inconsistent')
        token = existing or selection['namespace']
        try:
            if existing is None:
                self.pipe.prepare_new_game(revision, token)
            deadline = time.monotonic() + 8
            while True:
                guard = confirm()
                if ((guard.get('protection') or {}).get('campaign_namespace') == token
                        and guard.get('campaign_mount_ready') == token):
                    break
                if time.monotonic() >= deadline:
                    raise ValueError('RE2 hat den Checkpoint-Arbeitsordner nicht bestaetigt.')
                self.game_exit.wait(.1)
            guard = confirm(protected=True)
            if (guard.get('runtime_protection') is not True or not storage_guard_active(directory)
                    or self.pipe.current_campaign(revision) != token
                    or guard['protection'].get('campaign_namespace') != token or guard.get('campaign_mount_ready') != token
                    or archive.verified(selection['digest']) != manifest):
                raise ValueError('Checkpoint workspace or archive changed during preparation')
            receipt = CheckpointWorkspace(self.data, self.pipe, directory, selection, self.game_exit).prepare()
            if existing is None and cleanup is not None:
                cleanup.callback(self.pipe.revoke_new_game, token)
            return receipt
        except (ValueError, OSError) as exc:
            if existing is None:
                try:
                    self.pipe.revoke_new_game(token)
                except (ValueError, OSError) as revoke_error:
                    raise ValueError(f'{exc} Auch der Widerruf ist unbestätigt. Lobby verlassen.') from revoke_error
            raise

    def enable(self):
        from campaign_start import prepare_runtime_campaign

        directory = require_steam_save(self.pipe)
        profile = PACKAGE / 'campaign-profile.json'
        if storage_guard_active(directory):
            return prepare_runtime_campaign(self.data, self.pipe, profile if profile.is_file() else None,
                                            self.game_exit)
        if self.worker is not None and self.worker.poll() is None:
            raise ValueError('RE2 schliessen, damit Steam das Spiel neu starten kann.')
        self.worker = start_setup(self.data, self.pipe, self.game_exit._handle)
        self.worker_failure = None
        return None

    def status(self):
        if self.worker is not None:
            if self.worker.poll() is None:
                return 'closing', None
            if self.worker_failure is None:
                self.worker_failure = _recent_failure(self.data, helper_pid=self.worker.pid) or ('failed', None)
            return self.worker_failure
        return self.startup_failure or (None, None)


def _recent_failure(data, *, helper_pid=None):
    try:
        record = _read_json(data / STATUS, max_bytes=2048)
    except (OSError, ValueError):
        return None
    if (not isinstance(record, dict) or record.get('schema') != 1 or record.get('phase') != 'failed'
            or type(record.get('at')) is not int or not 0 <= time.time() - record['at'] <= 300
            or helper_pid is not None and record.get('helper_pid') != helper_pid):
        return None
    detail = record.get('error')
    return 'failed', detail if isinstance(detail, str) and 0 < len(detail) <= 160 and detail.isprintable() else None


def run_campaign_copy(directory, require_closed, supervise, restore_access, *, steam_userdata=None):
    with open_save_session(directory, require_closed, steam_userdata=steam_userdata) as session:
        if storage_guard_recovery_pending(directory):
            require_closed()
            check_managed_save(directory, required=True)
            restore_access()
        session.restore()
        try:
            ready = session.install()
            supervise(ready)
        finally:
            session.restore()


def _registered_steam_root():
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
        value, kind = winreg.QueryValueEx(key, 'SteamPath')
    if kind != winreg.REG_SZ or not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError('Die registrierte Steam-Installation ist ungueltig.')
    return Path(value)


def steam_save_from_local(local):
    if not local.is_absolute() or local.name.lower() != 'local' or local.parent.name != '883710':
        return None
    directory = local.parent / 'remote' / 'win64_save'
    if sys.platform != 'win32' or len(directory.parents) < 4:
        return directory
    userdata = directory.parents[3]
    if userdata.name.lower() != 'userdata' or not userdata.is_junction():
        return directory
    # Resolve only Steam's registered root. Keep all descendants visible to the
    # copy supervisor's reparse-point checks and use one path for its guard keys.
    try:
        if userdata != _registered_steam_root() / 'userdata':
            return None
        target = userdata.resolve(strict=True)
        if target.is_dir():
            return target / directory.relative_to(userdata)
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def _steam_for_save(directory):
    if not directory.is_absolute() or len(directory.parents) < 5:
        raise ValueError('Der aktive Steam-Spielstandordner ist ungueltig.')
    userdata = directory.parents[3]
    standard = userdata.parent / 'steam.exe'
    if userdata.name == 'userdata' and standard.is_file() and userdata.resolve(strict=True) == userdata:
        return standard, userdata
    # Steam may report the physical target of its registered userdata junction.
    # Keep that canonical path for the journal and the Windows storage guard.
    try:
        root = _registered_steam_root()
        if (root / 'userdata').resolve(strict=True) == userdata and (root / 'steam.exe').is_file():
            return root / 'steam.exe', userdata
    except OSError:
        pass
    raise ValueError('Der aktive Spielstandordner gehoert nicht zur lokalen Steam-Installation.')


def start_setup(data, pipe, game_handle):
    import _winapi

    directory = require_steam_save(pipe)
    game = PACKAGE.parent / 're2.exe'
    if not game.is_file():
        raise ValueError('Die lokale RE2-Installation wurde nicht gefunden.')
    _steam_for_save(directory)
    current = _winapi.GetCurrentProcess()
    inherited = _winapi.DuplicateHandle(current, game_handle, current, 0, True, _winapi.DUPLICATE_SAME_ACCESS)
    try:
        startup = subprocess.STARTUPINFO(lpAttributeList={'handle_list': [int(inherited)]})
        args = [sys.executable, '-B', str(Path(__file__).resolve()), '--data', str(data),
                '--directory', str(directory), '--game-pid', str(pipe.game_pid), '--game-handle', str(inherited)]
        return subprocess.Popen(args, startupinfo=startup, close_fds=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    finally:
        _winapi.CloseHandle(inherited)


def _wait_for_title_exit(pipe, directory, handle):
    import _winapi

    require_steam_save(pipe, directory)
    last_proof = time.monotonic()
    deadline = last_proof + 120
    while True:
        result = _winapi.WaitForSingleObject(handle, 500)
        now = time.monotonic()
        if result == _winapi.WAIT_OBJECT_0:
            if now - last_proof <= 4:
                return
            raise ValueError('Steam Cloud konnte vor dem Neustart nicht bestaetigt werden.')
        if result != _winapi.WAIT_TIMEOUT or now >= deadline:
            raise ValueError('RE2 wurde fuer den vorbereiteten Neustart nicht rechtzeitig geschlossen.')
        current = pipe.save_directory()
        cloud = pipe.cloud_status()
        if current is not None and current != directory:
            raise ValueError('Das aktive Steam-Konto hat sich geaendert.')
        if cloud == 'cloud-enabled':
            raise ValueError('Steam Cloud wurde waehrend der Vorbereitung aktiviert.')
        if current == directory and cloud in CLOUD_OFF:
            last_proof = now


def _powershell():
    exe = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    env = {**os.environ, 'PSModulePath': str(exe.parent / 'Modules')}
    return [str(exe), '-NoProfile', '-NonInteractive'], env


def _require_game_closed():
    command, env = _powershell()
    result = subprocess.run([*command, '-Command',
                             "if ([Diagnostics.Process]::GetProcessesByName('re2').Length) { exit 2 }"],
                            env=env, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    if result.returncode != 0:
        raise ValueError('RE2 muss vor dem Wechsel des Spielstandordners geschlossen sein.')


def _restore_access(directory):
    command, env = _guard_command(directory)
    subprocess.run([*command, '-Restore'],
                   env=env, creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=20)


def _guard_command(directory):
    command, env = _powershell()
    script = PACKAGE / 'scripts/protect_re2_test_saves.ps1'
    # Windows clients can restrict unsigned scripts by default. Apply this
    # launch option only to our bundled script in this child PowerShell.
    return [*command, '-ExecutionPolicy', 'Bypass', '-File', str(script), '-SaveDirectory', str(directory)], env


def _supervise_game(directory, ready, game, steam):
    command, env = _guard_command(directory)
    with subprocess.Popen([*command, '-GameExecutable', str(game), '-ReadyFile', str(ready),
                           '-LaunchTimeoutSeconds', '90', '-PreserveOnLaunchTimeout'],
                          env=env, creationflags=subprocess.CREATE_NO_WINDOW) as guard:
        deadline = time.monotonic() + 25
        while guard.poll() is None and time.monotonic() < deadline:
            if ready.is_file() and storage_guard_active(directory):
                _require_game_closed()
                if _steam_for_save(directory)[0] != steam:
                    raise ValueError('Die Steam-Installation hat sich waehrend der Vorbereitung geaendert.')
                if guard.poll() is not None or not storage_guard_active(directory):
                    raise ValueError('Der Schreibschutz wurde vor dem Steam-Start beendet.')
                subprocess.Popen([str(steam), '-applaunch', '883710'],
                                 cwd=steam.parent, creationflags=subprocess.CREATE_NO_WINDOW)
                if guard.wait() != 0:
                    raise ValueError('Der geschuetzte Steam-Neustart konnte nicht abgeschlossen werden.')
                return
            time.sleep(0.1)
        raise ValueError('Der Schreibschutz fuer die Spielstandkopie konnte nicht gestartet werden.')


def main():
    import _winapi
    from steam_pose_bridge import SteamPipe

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--game-pid', type=int, required=True)
    parser.add_argument('--game-handle', type=int, required=True)
    args = parser.parse_args()
    status = args.data / STATUS
    try:
        with lock_data_directory(args.data, stream='campaign_setup'):
            try:
                write_json(status, {'schema': 1, 'phase': 'closing', 'game_pid': args.game_pid})
                pipe = SteamPipe(args.game_pid)
                _wait_for_title_exit(pipe, args.directory, args.game_handle)
                steam, userdata = _steam_for_save(args.directory)
                write_json(status, {'schema': 1, 'phase': 'supervising', 'game_pid': args.game_pid})
                run_campaign_copy(args.directory, _require_game_closed,
                                  lambda ready: _supervise_game(args.directory, ready, PACKAGE.parent / 're2.exe', steam),
                                  lambda: _restore_access(args.directory), steam_userdata=userdata)
                write_json(status, {'schema': 1, 'phase': 'restored', 'game_pid': args.game_pid})
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                detail = str(exc) if isinstance(exc, ValueError) else 'Schreibschutz oder Steam-Neustart fehlgeschlagen.'
                write_json(status, {'schema': 1, 'phase': 'failed', 'game_pid': args.game_pid, 'helper_pid': os.getpid(),
                                    'at': int(time.time()), 'error': detail})
                return 1
    finally:
        _winapi.CloseHandle(args.game_handle)
    return 0


if __name__ == '__main__':
    sys.exit(main())
