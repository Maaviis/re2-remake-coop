"""Prepare a Steam campaign copy after the title process has closed."""

import argparse
import os
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


def run_campaign_copy(directory, require_closed, supervise, restore_access):
    with open_save_session(directory, require_closed) as session:
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


def start_setup(data, pipe, game_handle):
    import _winapi

    directory = require_steam_save(pipe)
    game = PACKAGE.parent / 're2.exe'
    steam = directory.parents[4] / 'steam.exe' if len(directory.parents) >= 5 else None
    if not game.is_file() or steam is None or not steam.is_file():
        raise ValueError('Die lokale RE2- oder Steam-Installation wurde nicht gefunden.')
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
                write_json(status, {'schema': 1, 'phase': 'supervising', 'game_pid': args.game_pid})
                run_campaign_copy(args.directory, _require_game_closed,
                                  lambda ready: _supervise_game(args.directory, ready, PACKAGE.parent / 're2.exe',
                                                                args.directory.parents[4] / 'steam.exe'),
                                  lambda: _restore_access(args.directory))
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
