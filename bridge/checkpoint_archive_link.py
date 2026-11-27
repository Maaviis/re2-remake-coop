"""Negotiate a single protected archive exchange on a live Steam pose link."""
from copy import deepcopy
import secrets
from threading import Event

from sync_model import state_digest


class CheckpointArchiveLink:
    def __init__(self, role, build, exchange, pool):
        self.role, self.build = role, build
        self.exchange, self.pool = exchange, pool
        self.stop = self.work = None
        self._retiring = set()
        self.clear()

    @property
    def busy(self):
        return (self.work is not None and not self.work.done()
                or any(not job.done() for job in self._retiring))

    def clear(self):
        if self.stop is not None:
            self.stop.set()
        if self.work is not None:
            self.work.cancel()
            self._retiring.add(self.work)
        self._retiring = {job for job in self._retiring if not job.done()}
        self.scope = self.stop = self.work = None
        self.local_nonce = self.peer_nonce = None
        self.counter = self.peer_counter = 0
        self.selection_digest = self.error = None
        self.transferred = self.local_prepared = self.remote_prepared = False
        self.peer_seen = float('-inf')
        self.next_send = 0.

    def bind(self, link, epoch, membership, lobby):
        data = lobby['data'] if lobby else {}
        choice = data.get('settings', {}).get('coop_checkpoint')
        scope = None
        if (self.exchange and self.build and link[1] and epoch and membership and choice
                and data.get('connected') and lobby['session_id'] == link[0]):
            scope = {'session_id': link[0], 'request_id': link[1], 'epoch': epoch,
                     'role': self.role.decode(), 'membership': membership,
                     'revision': data['revision'], 'choice': choice}
        if self.scope != scope:
            self.clear()
            if scope:
                self.scope = deepcopy(scope)
                self.selection_digest = state_digest(choice)
                self.local_nonce = secrets.token_hex(16)

    def peer_prepared(self, now):
        return self.transferred and self.remote_prepared and now - self.peer_seen < 5

    def fail(self, reason):
        if self.error is not None:
            return
        self.next_send = 0.
        if self.stop is not None:
            self.stop.set()
        self.error = reason
        self.transferred = self.local_prepared = self.remote_prepared = False

    def tick(self, send, message, now):
        if self.scope is None:
            return
        shared = {'session_id': self.scope['session_id'], 'request_id': self.scope['request_id'],
                  'revision': self.scope['revision'], 'selection_digest': self.selection_digest}
        if (message and message['role'] != self.role.decode()
                and all(message[k] == v for k, v in shared.items())):
            if message['package_commit'] != self.build:
                self.fail('Beide Spieler benötigen dasselbe Koop-Paket.')
            elif self.peer_nonce is not None and message['nonce'] != self.peer_nonce:
                self.peer_nonce = message['nonce']
                self.fail('Die Archivverbindung hat sich geändert. Spielstand erneut wählen.')
            elif message['echo'] in (None, self.local_nonce) and message['counter'] > self.peer_counter:
                if self.peer_nonce is None:
                    self.peer_nonce = message['nonce']
                    self.next_send = 0.
                self.peer_counter = message['counter']
                if message['echo'] == self.local_nonce:
                    self.peer_seen = now
                    self.remote_prepared = message['state'] == 'prepared'
                    if message['state'] == 'failed':
                        if not self.error:
                            self.fail('Der Archivtransfer wurde auf der Gegenseite abgebrochen.')
                    elif self.work is None and not self.error:
                        self.stop = Event()
                        nonce = self.local_nonce if self.role == b'H' else self.peer_nonce
                        self.work = self.pool.submit(self.exchange, self.scope, nonce, self.stop)
        if self.work is not None and not self.transferred and not self.error:
            if now - self.peer_seen >= 5:
                self.fail('Die Gegenstelle hat den Archivtransfer nicht mehr bestätigt.')
            elif self.work.done():
                try:
                    result = self.work.result()
                    if result != {k: self.scope['choice'][k] for k in ('namespace', 'digest')}:
                        raise ValueError('Der Archivbeleg gehört zu einer anderen Auswahl.')
                except (OSError, ValueError) as exc:
                    self.fail(str(exc))
                else:
                    self.transferred = True
        if now >= self.next_send:
            self.counter += 1
            state = ('failed' if self.error else 'prepared' if self.transferred and self.local_prepared
                     else 'exchange')
            send({'version': 1, 'type': 'checkpoint_archive', **shared, 'archive_version': 1,
                  'package_commit': self.build, 'role': self.role.decode(), 'nonce': self.local_nonce,
                  'echo': self.peer_nonce, 'counter': self.counter, 'state': state})
            self.next_send = now + 1
