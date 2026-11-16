"""Transfer verified observations over a confirmed RE2 Steam peer link."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import secrets
from struct import Struct
import sys
from tempfile import NamedTemporaryFile
import time

from enemy_live import FLAG, EnemyLiveFeed, matching_live_view, unavailable_view, validate_live_view
from enemy_witness import compare_enemy_snapshots
from pose_bridge import lock_data_directory
from protocol import v1
from protocol.snapshot_transfer import MAX_SNAPSHOT_BYTES, SnapshotReceiver, snapshot_packets
from save_catalog import SaveCatalog
from steam_pose_bridge import SteamPipe
from sync_model import Replica


WINDOW = 8
TIMEOUT = 30.0
LIVE_TIMEOUT = 5.0
LIVE_INTERVAL = 0.25
_CONTROL = Struct('!4s16s16sI')
_PULL = b'R2P\x01'
_COMPLETE = 0xffffffff


def transfer(transport, role, session_id, request_id, *, capture=None, verify=None,
             expected_epoch=None, timeout=None):
    """Move one snapshot over a fixed native pipe epoch and return the verified state."""
    if role not in (b'H', b'G') or (role == b'H') != (capture is not None):
        raise ValueError('expected a snapshot source for the host role')
    if role == b'H' and verify is not None:
        raise ValueError('snapshot verification callback requires the guest role')
    if any(not isinstance(token, str) or not v1.REQUEST_ID.fullmatch(token)
           for token in (session_id, request_id)):
        raise ValueError('expected 32-character lowercase hex session and request IDs')
    session = bytes.fromhex(session_id)
    request = bytes.fromhex(request_id)
    timeout = TIMEOUT if timeout is None else timeout
    replica = Replica()
    packets, snapshot = (), None
    receiver = (SnapshotReceiver(replica, session_id, request_id, timeout=timeout)
                if role == b'G' else None)

    deadline = time.monotonic() + timeout
    epoch, next_index, requested = expected_epoch, 0, False

    def pull(index):
        transport.send_payload(_CONTROL.pack(_PULL, session, request, index))

    while time.monotonic() < deadline:
        payload = transport.receive()
        if time.monotonic() >= deadline:
            break
        if transport.role is not None and transport.role != role:
            raise ValueError('snapshot role does not match the RE2 Steam lobby')
        if epoch is None:
            epoch = transport.epoch
        elif transport.epoch != epoch:
            raise OSError('RE2 Steam peer changed during snapshot transfer')
        if epoch is not None and receiver and not requested:
            pull(0)
            requested = True

        if epoch is None or payload is None:
            time.sleep(0.01)
            continue
        if receiver:
            if receiver.matches(payload):
                if receiver.receive(payload):
                    snapshot = replica.snapshot()
                    if verify is not None:
                        verify(snapshot)
                    if time.monotonic() >= deadline:
                        break
                    pull(_COMPLETE)
                    return snapshot
                if receiver.contiguous_chunks == next_index + WINDOW:
                    next_index += WINDOW
                    pull(next_index)
            continue

        if len(payload) != _CONTROL.size:
            continue
        kind, source_session, source_request, index = _CONTROL.unpack(payload)
        if kind != _PULL or source_session != session or source_request != request:
            continue
        if index == _COMPLETE and packets and next_index == len(packets):
            return snapshot
        if index == 0 and not packets:
            snapshot = capture()
            if snapshot['session_id'] != session_id:
                raise ValueError('host snapshot belongs to a different session')
            replica.restore(snapshot)
            snapshot = replica.snapshot()
            packets = snapshot_packets(snapshot, request_id)
            if time.monotonic() >= deadline:
                break
        if index == next_index and index < len(packets):
            window = packets[index:index + WINDOW]
            for packet in window:
                transport.send_payload(packet)
            next_index += len(window)

    raise TimeoutError('no complete snapshot acknowledged on the current Steam peer link')


def follow_enemy_live(transport, role, session_id, request_id, feed, updates, *, emit=None):
    """Exchange paced active-enemy views on the Steam epoch that completed the bootstrap."""
    epoch = transport.epoch
    if epoch is None:
        raise ValueError('live enemy observations require a confirmed snapshot link')
    lane = sha256(b're2-enemy-live-v1' + bytes.fromhex(session_id + request_id)).digest()[:16]
    current, published, source_sequence = None, None, 0
    end_reason = 'stream_interrupted'

    def capture():
        nonlocal current
        feed.poll()
        sample = feed.latest
        keys = ('available', 'reason', 'continuous', 'enemies')
        changed = current is None or any(sample[key] != current[key] for key in keys)
        replica = Replica(session_id=lane.hex(), sequence=sequence)
        replica.state['flags'][FLAG] = sample if changed else None
        if changed:
            current = sample
        return replica.snapshot()

    def verify(snapshot):
        nonlocal current, source_sequence
        state = snapshot['state']
        if (snapshot['sequence'] != sequence or state['flags'].keys() != {FLAG}
                or any(value for key, value in state.items() if key != 'flags')):
            raise ValueError('unexpected Steam live enemy snapshot')
        sample = state['flags'][FLAG]
        if sample is None:
            if current is None:
                raise ValueError('Steam live enemy stream has no initial observation')
            return
        validate_live_view(sample)
        if sample['available']:
            if sample['observer_sequence'] <= source_sequence:
                raise ValueError('Steam live enemy observation sequence rolled back')
            source_sequence = sample['observer_sequence']
        current = sample

    try:
        for sequence in range(1, updates + 1):
            request = sha256(lane + sequence.to_bytes(4, 'big')).hexdigest()[:32]
            options = {'expected_epoch': epoch, 'timeout': LIVE_TIMEOUT}
            if role == b'H':
                transfer(transport, role, lane.hex(), request, capture=capture, **options)
            else:
                if sequence > 1:
                    time.sleep(LIVE_INTERVAL)
                transfer(transport, role, lane.hex(), request, verify=verify, **options)
                feed.poll()
                output = matching_live_view(current, feed.latest)
                if output != published:
                    emit(output)
                    published = output
        end_reason = 'stopped'
    except KeyboardInterrupt:
        end_reason = 'stopped'
        raise
    finally:
        if role == b'G':
            emit(unavailable_view(end_reason))


def _read_snapshot(path):
    with path.open('rb') as stream:
        payload = stream.read(MAX_SNAPSHOT_BYTES + 1)
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise ValueError('snapshot input exceeds the transfer byte limit')
    message = v1.decode(payload)
    if message['type'] != 'snapshot':
        raise ValueError('snapshot input must contain one v1 snapshot message')
    return message['data']


def _write_snapshot(path, snapshot):
    payload = v1.encode({'version': v1.VERSION, 'type': 'snapshot', 'data': snapshot})
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(payload)
            stream.close()
            temporary.replace(path)
        finally:
            stream.close()
            temporary.unlink(missing_ok=True)


def _native_feed(args):
    catalog = SaveCatalog(args.data / 're2_coop_save_catalog.json', allow_date=args.allow_save_date)
    return EnemyLiveFeed(args.data, args.load_request_id, catalog.select(args.save_slot))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True, help='REFramework data directory')
    parser.add_argument('--pid', type=int, required=True, help='RE2 process ID')
    parser.add_argument('--role', choices=('host', 'guest'), required=True)
    parser.add_argument('--file', type=Path, help='host input or guest output v1 snapshot')
    parser.add_argument('--native-enemies', action='store_true',
                        help='host a fresh guarded enemy observation or compare it on the guest')
    parser.add_argument('--load-request-id', help='local guarded native load request ID')
    parser.add_argument('--save-slot', help='native scenario key from the guarded host load')
    parser.add_argument('--allow-save-date', help='approved local save calendar date (YYYY-MM-DD)')
    parser.add_argument('--live-updates', type=int, help='follow native enemies for this many guest pulls (1-120)')
    parser.add_argument('--session-id', help='host snapshot session ID, required on the guest')
    parser.add_argument('--request-id', help='fresh transfer request ID shown by the host')
    args = parser.parse_args()
    is_host = args.role == 'host'
    if (is_host and (args.session_id or args.request_id)
            or not is_host and not (args.session_id and args.request_id)):
        parser.error('supply --session-id and --request-id on the guest only')
    witness_options = (args.load_request_id, args.save_slot, args.allow_save_date)
    if args.native_enemies:
        if not all(witness_options):
            parser.error('--native-enemies requires --load-request-id, --save-slot and --allow-save-date')
        if is_host == (args.file is not None):
            parser.error('with --native-enemies, supply --file on the guest only')
    elif args.file is None or any(witness_options):
        parser.error('supply --file or select --native-enemies with its local load arguments')
    if args.live_updates is not None and (not args.native_enemies or not 1 <= args.live_updates <= 120):
        parser.error('--live-updates requires --native-enemies and 1-120 updates')
    if sys.platform != 'win32' or not args.data.is_dir() or not 0 < args.pid <= 0xffffffff:
        parser.error('expected Windows, an existing REFramework data directory and a valid process ID')
    try:
        with lock_data_directory(args.data):
            pipe = SteamPipe(args.pid)
            feed = None
            if is_host:
                input_snapshot = None if args.native_enemies else _read_snapshot(args.file)
                session_id = input_snapshot['session_id'] if input_snapshot is not None else secrets.token_hex(16)
                request_id = secrets.token_hex(16)
                def capture():
                    nonlocal feed
                    if not args.native_enemies:
                        return input_snapshot
                    feed = _native_feed(args)
                    return feed.bootstrap(session_id, request_id)

                print(f'--session-id {session_id} --request-id {request_id}', flush=True)
                transfer(pipe, b'H', session_id, request_id, capture=capture)
                print('Guest acknowledged the verified snapshot')
            else:
                report = None
                if args.native_enemies:
                    def verify(received):
                        nonlocal report, feed
                        feed = _native_feed(args)
                        local = feed.bootstrap(args.session_id, args.request_id)
                        report = compare_enemy_snapshots(received, local)
                else:
                    verify = None
                snapshot = transfer(pipe, b'G', args.session_id, args.request_id, verify=verify)
                _write_snapshot(args.file, snapshot)
                if report is None:
                    print(f"Verified snapshot at sequence {snapshot['sequence']}")
                else:
                    print(json.dumps(report, sort_keys=True), flush=True)
                session_id, request_id = args.session_id, args.request_id
            if args.live_updates:
                role = b'H' if is_host else b'G'
                follow_enemy_live(pipe, role, session_id, request_id, feed, args.live_updates,
                                  emit=lambda view: print(json.dumps(view, sort_keys=True), flush=True))
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        print(f'Steam snapshot transfer stopped: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
