"""Publish a short local receipt for native readback of Steam enemy observations."""

from pathlib import Path
import time

from enemy_live import unavailable_view
from load_witness import MAX_AGE
from lobby_sync import write_json


class GuestEnemyFile:
    filename = 're2_coop_guest_enemies.json'

    def __init__(self, data, session_id):
        self.path = Path(data) / self.filename
        self.session_id = session_id
        self.generation = int(time.time() * 1_000_000)
        self.sequence = 0
        self.publish(unavailable_view('starting'))

    def publish(self, view, feed=None):
        now = int(time.time())
        load = None
        if view['available']:
            report = feed.reader.accepted
            if (report is not None and report['available'] and 0 <= now - report['observed_at'] <= MAX_AGE
                    and report['state']['checkpoint'] == feed.checkpoint):
                load = {
                    'request_id': feed.request_id, 'slot_id': feed.reference['slot_id'],
                    'checkpoint': feed.checkpoint, 'observer_run_id': report['run_id'],
                    'observer_sequence': report['sequence'],
                }
            else:
                view = unavailable_view('local_source_unavailable')
        self.sequence += 1
        write_json(self.path, {
            'schema': 1, 'source': 'steam_enemy_live', 'tdb': 70, 'session_id': self.session_id,
            'generation': self.generation, 'sequence': self.sequence, 'received_at': now,
            'view': view, 'load': load,
        })
