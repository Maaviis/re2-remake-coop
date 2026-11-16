"""Publish guarded active-enemy observations over the read-only v1 loopback host."""

import argparse
from pathlib import Path
import sys
from threading import Thread
import time

from enemy_witness import EnemyStateFile
from protocol import v1
from save_catalog import SaveCatalog
from wire import Server


FLAG = 'native_enemy_live'
SCOPE = 'active_enemy_controller_observations'
POLL_INTERVAL = 0.05
LIVE_FIELDS = ('inherit_id', 'hp', 'default_hp', 'is_live', 'is_dead')


class EnemyLiveFeed:
    def __init__(self, data, request_id, reference):
        self.reader = EnemyStateFile(data)
        self.request_id = request_id
        self.reference = reference
        self.checkpoint = None
        self.observer_sequence = 0
        self.latest = None

    def unavailable(self, reason):
        if self.latest is not None and not self.latest['available'] and self.latest['reason'] == reason:
            return None
        self.latest = {'schema': 1, 'scope': SCOPE, 'available': False, 'reason': reason,
                       'continuous': False, 'observer_sequence': None, 'observed_at': None, 'enemies': {}}
        return self.latest

    def poll(self, *, now=None):
        if self.latest is not None and self.latest['reason'] == 'checkpoint_changed':
            return None  # The next checkpoint needs a new guarded observation session.
        try:
            evidence = self.reader.for_load(self.request_id, self.reference, now=now)
        except (OSError, ValueError, RecursionError):
            return self.unavailable('source_unavailable')
        checkpoint = evidence['state']['checkpoint']
        if self.checkpoint is None:
            self.checkpoint = checkpoint
        if checkpoint != self.checkpoint:
            return self.unavailable('checkpoint_changed')

        sequence = evidence['observer_sequence']
        if sequence <= self.observer_sequence:
            # A rewritten or temporarily unreadable file cannot renew an old sample.
            return None
        current = {
            row['id']: {'kind_id': row['kind_id'], **{key: row['live'][key] for key in LIVE_FIELDS}}
            for row in evidence['state']['entries'] if row['live'].get('active') is True
        }
        continuous = (self.latest is not None and self.latest['available']
                      and sequence == self.observer_sequence + 1)
        self.observer_sequence = sequence
        if continuous and current == self.latest['enemies']:
            return None
        self.latest = {'schema': 1, 'scope': SCOPE, 'available': True, 'reason': 'ok',
                       'continuous': continuous, 'observer_sequence': sequence,
                       'observed_at': evidence['observed_at'], 'enemies': current}
        return self.latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True, help='REFramework data directory')
    parser.add_argument('--load-request-id', required=True, help='guarded native load request ID')
    parser.add_argument('--save-slot', required=True, help='native scenario key from the guarded load')
    parser.add_argument('--allow-save-date', required=True, help='approved native save calendar date (YYYY-MM-DD)')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--seconds', type=float, default=30.0)
    args = parser.parse_args()
    if (not args.data.is_dir() or not v1.REQUEST_ID.fullmatch(args.load_request_id)
            or not 0 <= args.port <= 65535 or not 0 < args.seconds <= 120):
        parser.error('expected an existing data directory, a native load ID, a port and up to 120 seconds')
    try:
        catalog = SaveCatalog(args.data / 're2_coop_save_catalog.json', allow_date=args.allow_save_date)
        source = EnemyLiveFeed(args.data, args.load_request_id, catalog.select(args.save_slot))
        with Server(('127.0.0.1', args.port), protocol_version=v1.VERSION, read_only=True) as server:
            server.publish('flag', FLAG, source.poll())
            worker = Thread(target=server.serve_forever, kwargs={'poll_interval': POLL_INTERVAL}, daemon=True)
            worker.start()
            print(server.server_address[1], flush=True)
            deadline = time.monotonic() + args.seconds
            try:
                while time.monotonic() < deadline:
                    if (sample := source.poll()) is not None:
                        server.publish('flag', FLAG, sample)
                    time.sleep(POLL_INTERVAL)
            finally:
                server.publish('flag', FLAG, source.unavailable('stopped'))
                server.shutdown()
                worker.join()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        print(f'Enemy observation stream stopped: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
