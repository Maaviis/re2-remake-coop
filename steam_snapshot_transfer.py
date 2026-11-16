"""Transfer one verified model snapshot over a confirmed RE2 Steam peer link."""

import argparse
import json
from pathlib import Path
import secrets
from struct import Struct
import sys
from tempfile import NamedTemporaryFile
import time

from enemy_witness import EnemyStateFile, compare_enemy_snapshots
from pose_bridge import lock_data_directory
from protocol import v1
from protocol.snapshot_transfer import MAX_SNAPSHOT_BYTES, SnapshotReceiver, snapshot_packets
from save_catalog import SaveCatalog
from steam_pose_bridge import SteamPipe
from sync_model import Replica


WINDOW = 8
TIMEOUT = 30.0
_CONTROL = Struct('!4s16s16sI')
_PULL = b'R2P\x01'
_COMPLETE = 0xffffffff


def transfer(transport, role, session_id, request_id, *, capture=None, verify=None):
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
    replica = Replica()
    packets, snapshot = (), None
    receiver = (SnapshotReceiver(replica, session_id, request_id, timeout=TIMEOUT)
                if role == b'G' else None)

    deadline = time.monotonic() + TIMEOUT
    epoch, next_index = None, 0

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
            if epoch is not None and receiver:
                pull(0)
        elif transport.epoch != epoch:
            raise OSError('RE2 Steam peer changed during snapshot transfer')

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


def _native_capture(args, session_id, request_id):
    reader = EnemyStateFile(args.data)
    catalog = SaveCatalog(args.data / 're2_coop_save_catalog.json', allow_date=args.allow_save_date)

    def capture():
        reference = catalog.select(args.save_slot)
        return reader.snapshot_for_load(args.load_request_id, reference, session_id, comparison_id=request_id)

    return capture


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
    if sys.platform != 'win32' or not args.data.is_dir() or not 0 < args.pid <= 0xffffffff:
        parser.error('expected Windows, an existing REFramework data directory and a valid process ID')
    try:
        with lock_data_directory(args.data):
            pipe = SteamPipe(args.pid)
            if is_host:
                input_snapshot = None if args.native_enemies else _read_snapshot(args.file)
                session_id = input_snapshot['session_id'] if input_snapshot is not None else secrets.token_hex(16)
                request_id = secrets.token_hex(16)
                capture = (_native_capture(args, session_id, request_id) if args.native_enemies
                           else lambda: input_snapshot)
                print(f'--session-id {session_id} --request-id {request_id}', flush=True)
                transfer(pipe, b'H', session_id, request_id, capture=capture)
                print('Guest acknowledged the verified snapshot')
            else:
                report = None
                if args.native_enemies:
                    local_capture = _native_capture(args, args.session_id, args.request_id)

                    def verify(received):
                        nonlocal report
                        report = compare_enemy_snapshots(received, local_capture())
                else:
                    verify = None
                snapshot = transfer(pipe, b'G', args.session_id, args.request_id, verify=verify)
                _write_snapshot(args.file, snapshot)
                if report is None:
                    print(f"Verified snapshot at sequence {snapshot['sequence']}")
                else:
                    print(json.dumps(report, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        print(f'Steam snapshot transfer stopped: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
