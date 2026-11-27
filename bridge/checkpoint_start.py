"""Keep checkpoint preparation and staging off the Steam lobby publication loop."""
from copy import deepcopy
from contextlib import ExitStack
from threading import Condition, Event, Thread
import time

from campaign_setup import CampaignSetup, require_steam_save
from campaign_start import campaign_stage
from checkpoint_workspace import CheckpointReadiness
from load_preflight import NativeSaveSource, TOKEN, validate_checkpoint
from readonly_save_control import read_active_guard, read_connected_lobby


class _ScopeStop:
    def __init__(self, game_exit):
        self.game_exit = game_exit
        self.cancelled = Event()

    def is_set(self):
        return self.cancelled.is_set() or self.game_exit is not None and self.game_exit.is_set()

    def wait(self, timeout):
        return self.is_set() or self.cancelled.wait(timeout) or self.is_set()


class _PreparedSource(NativeSaveSource):
    def __init__(self, owner, directory, binding):
        super().__init__(owner.data, directory, allow_date=None, campaign_binding=binding)
        self.owner = owner

    def resolve_checkpoint(self, selection):
        # Full hashes and native checks are renewed by the worker. The lobby
        # pump must stay available to publish its own short-lived evidence.
        if selection != self.owner.selection or not self.owner.ready:
            raise ValueError('Checkpoint-Bereitschaft ist abgelaufen.')
        return selection['digest']


class CheckpointStartController:
    def __init__(self, data, game_pid, role, stop, selection, membership_revision, *, pipe_factory=None):
        from steam_pose_bridge import SteamPipe
        validate_checkpoint(selection, metadata=True)
        if role not in (b'H', b'G'):
            raise ValueError('Checkpoint preparation requires a Steam role')
        self.data, self.game_pid, self.role = data, game_pid, role.decode('ascii')
        self.selection = deepcopy(selection)
        self.revision = membership_revision
        self.pipe_factory = pipe_factory or SteamPipe
        self.stop = _ScopeStop(stop)
        self.source = self.error = self.request_id = None
        self._attempt = self._lease = None
        self._condition = Condition()
        self._release = self._quiescent = False
        self._worker = Thread(target=self._run, daemon=True)

    def start(self):
        self._worker.start()

    @property
    def finished(self):
        return not self._worker.is_alive()

    @property
    def ready(self):
        lease = self._lease
        if lease is None or self.stop.is_set() or self.error is not None:
            return False
        last_wall, last_mono, deadline, stamp = lease
        wall = time.time()
        return last_wall <= wall < stamp + 3 and last_mono <= time.monotonic() < deadline

    def stage(self, attempt_id):
        with self._condition:
            if (not isinstance(attempt_id, str) or not TOKEN.fullmatch(attempt_id) or not self.ready
                    or self._attempt not in (None, attempt_id)):
                raise ValueError('Checkpoint-Versuch ist nicht mehr bereit.')
            self._attempt = attempt_id
            self._condition.notify()

    def staged(self, stage_id, *, releasing=False):
        """Called only with the current native acknowledgment from read_staged_load."""
        with self._condition:
            if not self.ready or self.request_id is None or self.request_id != stage_id:
                return False
            if releasing:
                self._release = True
                self._condition.notify()
                return self._quiescent
            return True

    def cancel(self):
        self.stop.cancelled.set()
        with self._condition:
            self._condition.notify()

    def close(self):
        self.cancel()
        if self._worker.ident is not None:
            self._worker.join()

    def _run(self):
        cleanup = ExitStack()
        stage = proof = None
        try:
            pipe = self.pipe_factory(self.game_pid)
            scope, lobby = read_connected_lobby(self.data)
            if (scope['role'] != self.role or scope['game_pid'] != self.game_pid
                    or scope['membership']['revision'] != self.revision
                    or lobby['settings'].get('coop_checkpoint') != self.selection or self.stop.is_set()):
                raise ValueError('Checkpoint-Auswahl oder Steam-Verbindung hat gewechselt.')
            directory = require_steam_save(pipe)
            setup = CampaignSetup(self.data, pipe, self.stop)
            compact = {key: self.selection[key] for key in ('namespace', 'digest')}
            receipt = setup.enable_checkpoint(compact, self.revision, cleanup=cleanup)
            proof = CheckpointReadiness(self.data, pipe, directory, receipt, self.stop)
            if proof.workspace.scope != scope or proof.workspace.expected_choice != self.selection:
                raise ValueError('Checkpoint-Vorbereitung gehört zu einer anderen Auswahl.')
            self.source = _PreparedSource(self, directory, receipt['protection'])
            stage = campaign_stage(self.data, self.game_pid, directory, None, self.stop,
                                   expected_role=self.role, sync_enemies=True, checkpoint_available=True)
            def renew():
                guard = read_active_guard(self.data, protected=True, runtime_directory=directory)
                if guard.get('checkpoint_supported') is not True:
                    raise ValueError('Die native Checkpoint-Unterstützung ist nicht aktiv.')
                proof.refresh()
                self._lease = (proof.last_wall, proof.last_mono, proof.deadline, proof.record['at'])

            while not self.stop.is_set():
                renew()
                with self._condition:
                    if self._release:
                        # Both native receipts have arrived. No more title-only
                        # validation may race the resulting authorized load.
                        self._quiescent = True
                        break
                    attempt = self._attempt
                    if attempt is None or self.request_id is not None:
                        self._condition.wait(.35)
                        if self._release:
                            self._quiescent = True
                            break
                        attempt = self._attempt
                if attempt is not None and self.request_id is None and not self.stop.is_set():
                    self.request_id = stage(checkpoint=compact, expected_attempt=attempt,
                                            expected_preparation=receipt['request_id'], renew_preparation=renew)
            while self._quiescent and not self.stop.wait(.25):
                pass  # The release and combat worker remains bound to this scope.
        except Exception as exc:
            if not self.stop.is_set():
                self.error = str(exc)
        finally:
            self.stop.cancelled.set()
            # Withdraw the title receipt before waiting on any campaign worker.
            # A late common permit must not consume abandoned local preparation.
            if proof is not None:
                try:
                    proof.cancel()
                except (OSError, ValueError) as exc:
                    detail = f'Checkpoint-Vorbereitungsbeleg konnte nicht widerrufen werden: {exc}'
                    self.error = f'{self.error} {detail}' if self.error else detail
            try:
                if stage is not None:
                    stage.wait()
            finally:
                try:
                    cleanup.close()
                except (OSError, ValueError) as exc:
                    detail = f'Checkpoint-Ordner konnte nicht widerrufen werden: {exc}'
                    self.error = f'{self.error} {detail}' if self.error else detail
