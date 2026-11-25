"""Keep immutable generations of RE2's native slot-0 autosave outside Steam remote."""

from hashlib import file_digest
import json
import os
from pathlib import Path
import re
import secrets
from tempfile import TemporaryDirectory
import time

from campaign_save_copy import _copy_files, _directory_id, _entry, _file_signature
from load_preflight import MAX_SAVE_BYTES
from load_witness import _read_json
from lobby_sync import write_json
from save_catalog import saved_time
from sync_model import state_digest


FILES = ('data000.bin', 'data021Slot.bin', 'data00-1.bin')
TOKEN = re.compile(r'[0-9a-f]{32}')
DIGEST = re.compile(r'[0-9a-f]{64}')


def _token(value):
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None


def _signatures(directory, *, missing_ok=False):
    _directory_id(directory)
    signatures = {}
    for name in FILES:
        if _entry(directory / (name + '.stmp'), directory=False, missing_ok=True) is not None:
            raise ValueError('Steam schreibt noch in den Koop-Ordner.')
        info = _entry(directory / name, directory=False, missing_ok=missing_ok)
        if info is not None:
            if not 0 < info.st_size <= MAX_SAVE_BYTES:
                raise ValueError('Ungültige Größe einer nativen Checkpoint-Datei.')
            signatures[name] = _file_signature(info)
    return signatures


def _hashes(directory, signatures):
    values = {}
    for name, expected in signatures.items():
        with (directory / name).open('rb') as stream:
            if _file_signature(os.fstat(stream.fileno())) != expected:
                raise ValueError('Checkpoint-Datei vor der Prüfung ersetzt.')
            values[name] = file_digest(stream, 'sha256').hexdigest()
            if _file_signature(os.fstat(stream.fileno())) != expected:
                raise ValueError('Checkpoint-Datei während der Prüfung geändert.')
    return values


def _validate(manifest):
    if (not isinstance(manifest, dict)
            or set(manifest) != {'schema', 'build', 'namespace', 'attempt', 'release', 'slot', 'scenario',
                                 'difficulty', 'timestamp', 'files'}
            or type(manifest['schema']) is not int or manifest['schema'] != 1
            or type(manifest['build']) is not int or manifest['build'] != 11636119
            or any(not _token(manifest[k]) for k in ('namespace', 'attempt', 'release'))
            or type(manifest['slot']) is not int or manifest['slot'] != 0
            or type(manifest['scenario']) is not int or manifest['scenario'] not in (0, 1)
            or type(manifest['difficulty']) is not int or manifest['difficulty'] not in (0, 1, 2)
            or not isinstance(manifest['files'], dict) or set(manifest['files']) != set(FILES)
            or any(not isinstance(h, str) or not DIGEST.fullmatch(h) for h in manifest['files'].values())):
        raise ValueError('Ungültiges Koop-Checkpoint-Manifest.')
    saved_time(manifest['timestamp'])


class HostArchive:
    @staticmethod
    def _account_root(solo):
        solo = Path(solo)
        if (not solo.is_absolute() or solo.name != 'win64_save'
                or solo.parent.name != 'remote' or solo.parent.parent.name != '883710'
                or not solo.parent.parent.parent.name.isascii() or not solo.parent.parent.parent.name.isdigit()
                or solo != solo.resolve(strict=True)):
            raise ValueError('Ungültiger geschützter Koop-Speicherpfad.')
        return solo.parent.parent / 're2-coop-checkpoints'

    def __init__(self, solo, namespace):
        if not _token(namespace):
            raise ValueError('Ungültige Kennung des Koop-Speicherordners.')
        self.root = self._account_root(solo) / namespace
        self.namespace = namespace
        self.source = Path(solo).parent / ('coop-save-' + namespace)

    @classmethod
    def recoverable(cls, solo):
        """Find complete generations for this Steam account after RE2 has restarted."""
        root = cls._account_root(solo)
        if _entry(root, directory=True, missing_ok=True) is None:
            return []
        choices = []
        for folder in root.iterdir():
            if not _token(folder.name):
                continue
            try:
                _directory_id(folder)
                generations = list(folder.iterdir())
            except (OSError, ValueError):
                continue
            archive = cls(solo, folder.name)
            for generation in generations:
                if not DIGEST.fullmatch(generation.name):
                    continue
                try:
                    record = archive.verified(generation.name)
                except (OSError, ValueError):
                    continue
                choices.append({'digest': generation.name, 'namespace': folder.name,
                                **{k: record[k] for k in ('timestamp', 'scenario', 'difficulty', 'slot')}})
        return sorted(choices, key=lambda c: (-int(c['timestamp']), c['digest']))

    def before_save(self):
        return _directory_id(self.source), _signatures(self.source, missing_ok=True)

    def verified(self, digest):
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError('Ungültige Checkpoint-Kennung.')
        directory = self.root / digest
        for parent in (self.root.parent, self.root, directory):
            _directory_id(parent)
        _entry(directory / 'manifest.json', directory=False)
        manifest = _read_json(directory / 'manifest.json', max_bytes=4096)
        _validate(manifest)
        if (manifest['namespace'] != self.namespace or state_digest(manifest) != digest
                or {p.name for p in directory.iterdir()} != {'manifest.json', *FILES}):
            raise ValueError('Checkpoint-Manifest und Generation stimmen nicht überein.')
        signatures = _signatures(directory)
        if _hashes(directory, signatures) != manifest['files'] or signatures != _signatures(directory):
            raise ValueError('Archivierte RE2-Dateien stimmen nicht mit dem Manifest überein.')
        return manifest

    def publish(self, before, receipt, confirm):
        """Publish only after native completion, stable file identities and a final live confirmation."""
        source_id, old = before
        if _directory_id(self.source) != source_id:
            raise ValueError('Der Koop-Ordner wurde beim Speichern ersetzt.')
        signatures = _signatures(self.source)
        if any(old.get(name) == signatures[name] for name in FILES[:2]):
            raise ValueError('RE2 hat Autosave und Slotindex noch nicht gemeinsam erneuert.')
        for parent in (self.root.parent, self.root):
            parent.mkdir(exist_ok=True)
            _directory_id(parent)
        with TemporaryDirectory(prefix='.pending-', dir=self.root) as staging:
            directory = Path(staging)
            generation = directory / 'generation'
            generation.mkdir()
            _copy_files(self.source, generation, signatures)
            files = _hashes(generation, _signatures(generation))
            manifest = {**receipt, 'schema': 1, 'build': 11636119, 'namespace': self.namespace, 'files': files}
            _validate(manifest)
            digest = state_digest(manifest)
            with (generation / 'manifest.json').open('x', encoding='utf-8') as stream:
                json.dump(manifest, stream)
                stream.flush()
                os.fsync(stream.fileno())
            confirm()
            if _directory_id(self.source) != source_id or _signatures(self.source) != signatures:
                raise ValueError('RE2 hat den Checkpoint während der Archivierung geändert.')
            target = self.root / digest
            try:
                generation.rename(target)
            except OSError:
                if not target.is_dir():
                    raise
                self.verified(digest)
            return digest


def publish_local_catalog(data, pipe, solo):
    choices = HostArchive.recoverable(solo)
    if pipe.save_directory() != solo:
        raise ValueError('Das Steam-Profil hat sich beim Lesen des Archivs geändert.')
    for item in choices:
        item['saved_at'] = saved_time(item['timestamp']).isoformat(sep=' ', timespec='seconds')
    write_json(data / 're2_coop_host_archive.json',
               {'schema': 1, 'game_pid': pipe.game_pid, 'choices': choices})


def discover_after_launch(data, pipe, game_exit):
    """The regular Steam bridge can start before Steam has supplied its active user directory."""
    while not game_exit.is_set():
        try:
            solo = pipe.save_directory()
            if solo is not None:
                publish_local_catalog(data, pipe, solo)
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)


def serve_host(data, solo, policy, receipt, stop):
    from readonly_save_control import read_active_guard, read_connected_lobby
    from steam_pose_bridge import SteamPipe

    scope = policy['lobby_load']
    binding = policy['protection']
    archive = HostArchive(solo, binding['campaign_namespace'])
    pipe = SteamPipe(receipt['game_pid'])
    anchor = {k: receipt[k] for k in ('game_pid', 'load_request_id', 'release_id', 'snapshot_epoch')}
    expected_link = {k: scope[k] for k in ('game_pid', 'role', 'session_id', 'membership')}

    def current():
        guard = read_active_guard(data, protected=True, runtime_directory=solo)
        hold = guard.get('load_hold') or {}
        campaign = hold.get('campaign') or {}
        link, _ = read_connected_lobby(data)
        if (stop.is_set() or link != expected_link or link['role'] != 'H'
                or pipe.lobby_status() != 'owned' or pipe.membership_revision() != scope['membership']['revision']
                or pipe.cloud_status() not in ('cloud-app-disabled', 'cloud-account-disabled')
                or guard.get('protection') != binding or guard.get('campaign_mount_ready') != archive.namespace
                or guard.get('guard_run_id') != scope['guard_run_id'] or guard.get('in_title') is not False
                or hold.get('phase') != 'released' or hold.get('native_phase') != 'released'
                or hold.get('load_request_id') != anchor['load_request_id']
                or hold.get('release') != {'id': anchor['release_id'], 'snapshot_epoch': anchor['snapshot_epoch']}
                or any(campaign.get(k) != v for k, v in {
                    'game_pid': anchor['game_pid'], 'role': 'H', 'session_id': scope['session_id'],
                    'revision': scope['membership']['revision'], 'attempt_id': scope['attempt_id'],
                    'protection_run_id': binding['run_id'], 'snapshot_epoch': anchor['snapshot_epoch']}.items())):
            raise ValueError('Die gemeinsame Freigabe oder der Koop-Speicherordner hat gewechselt.')
        return guard

    def status(phase, **fields):
        write_json(data / 're2_coop_checkpoint_status.json',
                   {**anchor, 'at': int(time.time()), 'phase': phase, **fields})

    last = None
    while not stop.wait(0.25):
        try:
            ui = _read_json(data / 're2_coop_checkpoint_button.json', max_bytes=1024)
        except (OSError, ValueError):
            continue
        if (not isinstance(ui, dict) or type(ui.get('at')) is not int or not 0 <= time.time() - ui['at'] <= 4
                or any(ui.get(k) != v for k, v in anchor.items()) or ui['at'] == last):
            continue
        last = ui['at']
        try:
            current()
            before = archive.before_save()
            request = {**anchor, 'id': secrets.token_hex(16), 'at': int(time.time()), 'namespace': archive.namespace}
            status('saving')
            write_json(data / 're2_coop_checkpoint_request.json', request)
            deadline = time.monotonic() + 33
            while not stop.wait(0.25):
                proof = current().get('host_checkpoint') or {}
                if proof.get('id') == request['id']:
                    if proof.get('phase') == 'failed':
                        raise ValueError(str(proof.get('reason', 'native_save_failed')))
                    if proof.get('phase') == 'complete':
                        def confirm():
                            if current().get('host_checkpoint') != proof:
                                raise ValueError('Die native Slotbestätigung hat sich geändert.')
                        fields = {k: proof[k] for k in ('slot', 'scenario', 'difficulty', 'timestamp')}
                        digest = archive.publish(before, {**fields, 'attempt': scope['attempt_id'],
                                                 'release': anchor['release_id']}, confirm)
                        status('saved', digest=digest)
                        break
                if time.monotonic() >= deadline:
                    raise ValueError('Zeitüberschreitung beim nativen Checkpoint.')
        except (KeyError, OSError, ValueError) as exc:
            status('failed', reason=str(exc) if isinstance(exc, ValueError) else 'checkpoint_file_unavailable')
