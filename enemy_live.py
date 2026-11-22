"""Publish guarded active-enemy observations over the read-only v1 loopback host."""

import argparse
from pathlib import Path
import sys
from threading import Thread
import time

from enemy_witness import MAX_ENEMIES, EnemyStateFile, _fields, _guid, _members
from load_witness import MAX_AGE, LoadBindingChanged, _integer
from observer import valid_campaign_area
from protocol import v1
from save_catalog import SaveCatalog
from wire import Server


FLAG = 'native_enemy_live'
SCOPE = 'active_enemy_controller_observations'
POLL_INTERVAL = 0.05
LIVE_FIELDS = ('inherit_id', 'hp', 'default_hp', 'is_live', 'is_dead')
DEATH_FIELDS = ('kind_id', 'inherit_id', 'hp', 'is_dead')


def unavailable_view(reason):
    return {'schema': 1, 'scope': SCOPE, 'available': False, 'reason': reason,
            'continuous': False, 'observer_sequence': None, 'observed_at': None, 'enemies': {}}


def validate_live_view(value):
    if not isinstance(value, dict):
        raise ValueError('invalid active enemy observation')
    _fields(value, unavailable_view('stopped').keys() | (value.keys() & {'death_observations', 'campaign_area'}))
    if (not _integer(value['schema'], 1, 1) or value['scope'] != SCOPE
            or type(value['available']) is not bool or type(value['continuous']) is not bool
            or not isinstance(value['enemies'], dict) or len(value['enemies']) > MAX_ENEMIES):
        raise ValueError('invalid active enemy observation')
    if not value['available']:
        if (value['reason'] not in ('source_unavailable', 'checkpoint_changed', 'stopped')
                or value != unavailable_view(value['reason'])):
            raise ValueError('unavailable active enemy observation contains live data')
        return
    if (value['reason'] != 'ok' or not _integer(value['observer_sequence'], 1)
            or not _integer(value['observed_at'], 1)):
        raise ValueError('invalid active enemy observation source')
    if 'campaign_area' in value and not valid_campaign_area(value['campaign_area']):
        raise ValueError('invalid active enemy campaign area')
    for identity, enemy in value['enemies'].items():
        _guid(identity)
        _members(enemy, signed=('kind_id', 'inherit_id', 'hp', 'default_hp'), flags=('is_live', 'is_dead'))
    if 'death_observations' in value:
        deaths = value['death_observations']
        if not isinstance(deaths, dict) or len(deaths) > MAX_ENEMIES:
            raise ValueError('invalid native death observations')
        for identity, death in deaths.items():
            _guid(identity)
            _members(death, signed=('kind_id', 'inherit_id', 'hp'), flags=('active', 'is_dead'),
                     other=('observer_sequence', 'observed_at'))
            active = value['enemies'].get(identity)
            if (not death['is_dead']
                    or not _integer(death['observer_sequence'], 1, value['observer_sequence'])
                    or not _integer(death['observed_at'], 1, value['observed_at'])
                    or (active is not None and (not death['active']
                        or any(death[key] != active[key] for key in DEATH_FIELDS)))):
                raise ValueError('invalid native death observation')


def matching_live_view(host, local):
    """Keep host observations whose active identity is also present locally."""
    if not host['available']:
        return host
    if not local['available']:
        return unavailable_view('local_source_unavailable')
    if host.get('campaign_area') != local.get('campaign_area'):
        return unavailable_view('campaign_area_mismatch')
    matching = {}
    for identity, host_enemy in host['enemies'].items():
        local_enemy = local['enemies'].get(identity)
        if local_enemy is not None and all(host_enemy[key] == local_enemy[key] for key in ('kind_id', 'inherit_id')):
            matching[identity] = host_enemy
    return {**host, 'enemies': matching}


class EnemyLiveFeed:
    def __init__(self, data, request_id, reference, *, death_evidence=False, campaign=False):
        self.reader = EnemyStateFile(data, campaign=campaign)
        self.request_id = request_id
        self.reference = reference
        self.checkpoint = None
        self.observer_sequence = 0
        self.latest = None
        self.death_evidence = death_evidence
        self.dead_evidence = {}
        self.campaign = campaign

    def bootstrap(self, session_id, request_id):
        if self.latest is not None and self.latest['reason'] == 'checkpoint_changed':
            raise ValueError('native load binding changed; a new observation session is required')
        snapshot = self.reader.snapshot_for_load(
            self.request_id, self.reference, session_id, comparison_id=request_id,
            continuing=self.checkpoint is not None)
        self.checkpoint = self.reader.accepted['state']['checkpoint']
        return snapshot

    def unavailable(self, reason):
        if self.latest is not None and not self.latest['available'] and self.latest['reason'] == reason:
            return None
        self.latest = unavailable_view(reason)
        self.dead_evidence.clear()
        return self.latest

    def _death_observations(self, rows, sequence, observed_at):
        current = {}
        for identity, row in rows.items():
            live = row['live']
            if not live.get('is_dead'):
                continue
            values = {'kind_id': row['kind_id'], **{key: live[key] for key in DEATH_FIELDS[1:]},
                      'active': live['active']}
            prior = self.dead_evidence.get(identity)
            if prior and prior[1] <= observed_at and all(prior[0][key] == value for key, value in values.items()):
                record = prior[0]
            else:
                record = {**values, 'observer_sequence': sequence, 'observed_at': observed_at}
            current[identity] = (record, observed_at)

        # Fresh, explicit readings take priority over the bounded historical set.
        for identity, (record, last_seen) in sorted(self.dead_evidence.items(), key=lambda item: -item[1][1]):
            if len(current) == MAX_ENEMIES:
                break
            row = rows.get(identity)
            if (identity not in current and 0 <= observed_at - last_seen <= MAX_AGE
                    and (row is None or (row['kind_id'] == record['kind_id'] and not row['live']['present']))):
                current[identity] = (record, last_seen)
        self.dead_evidence = current
        return {identity: record for identity, (record, _) in current.items()}

    def poll(self, *, now=None):
        if self.latest is not None and self.latest['reason'] == 'checkpoint_changed':
            return None  # The next checkpoint needs a new guarded observation session.
        try:
            evidence = self.reader.for_load(self.request_id, self.reference, now=now,
                                            continuing=self.checkpoint is not None)
        except LoadBindingChanged:
            return self.unavailable('checkpoint_changed')
        except (OSError, ValueError, RecursionError):
            return self.unavailable('source_unavailable')
        checkpoint = evidence['state']['checkpoint']
        if self.checkpoint is None:
            self.checkpoint = checkpoint
        if checkpoint != self.checkpoint:
            return self.unavailable('checkpoint_changed')
        area = evidence['state'].get('campaign_area')
        if self.campaign and (not valid_campaign_area(area) or area['scenario'] != checkpoint['scenario']):
            return self.unavailable('source_unavailable')

        sequence = evidence['observer_sequence']
        if sequence <= self.observer_sequence:
            # A rewritten or temporarily unreadable file cannot renew an old sample.
            return None
        rows = {row['id']: row for row in evidence['state']['entries']}
        view = {'enemies': {
            identity: {'kind_id': row['kind_id'], **{key: row['live'][key] for key in LIVE_FIELDS}}
            for identity, row in rows.items() if row['live'].get('active') is True
        }}
        if self.campaign:
            view['campaign_area'] = area
        if self.death_evidence:
            view['death_observations'] = self._death_observations(rows, sequence, evidence['observed_at'])
        continuous = (self.latest is not None and self.latest['available']
                      and sequence == self.observer_sequence + 1)
        self.observer_sequence = sequence
        if continuous and all(self.latest[key] == value for key, value in view.items()):
            return None
        self.latest = {'schema': 1, 'scope': SCOPE, 'available': True, 'reason': 'ok',
                       'continuous': continuous, 'observer_sequence': sequence,
                       'observed_at': evidence['observed_at'], **view}
        return self.latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True, help='REFramework data directory')
    parser.add_argument('--load-request-id', required=True, help='guarded native load request ID')
    parser.add_argument('--save-slot', required=True, help='native scenario key from the guarded load')
    parser.add_argument('--allow-save-date', required=True, help='approved native save calendar date (YYYY-MM-DD)')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--seconds', type=float, default=30.0)
    parser.add_argument('--death-evidence', action='store_true', help='retain confirmed native death observations')
    args = parser.parse_args()
    if (not args.data.is_dir() or not v1.REQUEST_ID.fullmatch(args.load_request_id)
            or not 0 <= args.port <= 65535 or not 0 < args.seconds <= 120):
        parser.error('expected an existing data directory, a native load ID, a port and up to 120 seconds')
    try:
        catalog = SaveCatalog(args.data / 're2_coop_save_catalog.json', allow_date=args.allow_save_date)
        source = EnemyLiveFeed(args.data, args.load_request_id, catalog.select(args.save_slot),
                               death_evidence=args.death_evidence)
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
