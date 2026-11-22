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

from campaign_hits import CHALLENGE_BYTES, MAX_ATTACHMENT, CampaignHitWindow
from enemy_live import FLAG, POLL_INTERVAL, EnemyLiveFeed, matching_live_view, unavailable_view, validate_live_view
from enemy_witness import compare_enemy_snapshots
from guest_enemy_file import GuestEnemyFile
from interrupted_checkpoint import COMPONENTS as INTERRUPTED_COMPONENTS, InterruptedCheckpoint
from pose_bridge import lock_data_directory
from prepared_checkpoint import PreparedCheckpoint
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
_RESUME_FRAME = Struct('!4s16s16s16s')
_RESUME_OFFER = b'R2O' + bytes((v1.CAMPAIGN_RESUME_VERSION,))
_RESUME_ACCEPT = b'R2A' + bytes((v1.CAMPAIGN_RESUME_VERSION,))
_RESUME_COMMIT = b'R2R' + bytes((v1.CAMPAIGN_RESUME_VERSION,))
_RELEASE_HEARTBEAT = b'R2D' + bytes((v1.CAMPAIGN_RESUME_VERSION,))
_INTERRUPTED_RESULT = Struct('!4s16s16sB')
_INTERRUPTED_COMPARE = b'R2J\x01'
_COMPLETE = 0xffffffff
_MAX_PULL_ATTACHMENT = MAX_ATTACHMENT + CHALLENGE_BYTES
_HIT_CHALLENGE = 'campaign_hit_challenge'


def _transfer_ids(session_id, request_id):
    if any(not isinstance(token, str) or not v1.REQUEST_ID.fullmatch(token)
           for token in (session_id, request_id)):
        raise ValueError('expected 32-character lowercase hex session and request IDs')
    return bytes.fromhex(session_id), bytes.fromhex(request_id)


def transfer(transport, role, session_id, request_id, *, capture=None, verify=None,
             expected_epoch=None, timeout=None, on_idle=None, stop=None, accept_request=None, first_pull=b''):
    """Move one snapshot over a fixed native pipe epoch and return the verified state."""
    if role not in (b'H', b'G') or (role == b'H') != (capture is not None):
        raise ValueError('expected a snapshot source for the host role')
    if role == b'H' and verify is not None:
        raise ValueError('snapshot verification callback requires the guest role')
    if accept_request is not None and (role != b'H' or request_id is not None):
        raise ValueError('dynamic snapshot requests require a host without a fixed request ID')
    if first_pull and (role != b'G' or not isinstance(first_pull, bytes) or len(first_pull) > _MAX_PULL_ATTACHMENT):
        raise ValueError('invalid first snapshot pull attachment')
    session, request = _transfer_ids(session_id, '0' * 32 if accept_request else request_id)
    timeout = TIMEOUT if timeout is None else timeout
    replica = Replica()
    packets, snapshot = (), None
    receiver = (SnapshotReceiver(replica, session_id, request_id, timeout=timeout)
                if role == b'G' else None)

    deadline = time.monotonic() + timeout
    epoch, next_index, requested = expected_epoch, 0, False

    def pull(index):
        attachment = first_pull if index == 0 else b''
        transport.send_payload(_CONTROL.pack(_PULL, session, request, index) + attachment)

    while time.monotonic() < deadline:
        if stop is not None and stop.is_set():
            raise ValueError('snapshot exchange was cancelled')
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
            if epoch is not None and on_idle is not None:
                on_idle()
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

        if not _CONTROL.size <= len(payload) <= _CONTROL.size + _MAX_PULL_ATTACHMENT:
            continue
        kind, source_session, source_request, index = _CONTROL.unpack_from(payload)
        attachment = payload[_CONTROL.size:]
        if attachment and (accept_request is None or index != 0):
            continue
        if kind != _PULL or source_session != session:
            continue
        if accept_request is not None and index == 0 and source_request != request:
            if not accept_request(source_request, attachment):
                continue
            request, request_id = source_request, source_request.hex()
            next_index, packets = 0, ()
            deadline = time.monotonic() + timeout
        if source_request != request:
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


def follow_enemy_live(transport, role, session_id, request_id, feed, updates, *, emit=None, publish=None,
                      death_evidence=False, campaign=False, stop=None, expected_epoch=None, hits=None,
                      on_exchange=None):
    """Exchange paced active-enemy views on a fixed Steam peer epoch."""
    epoch = transport.epoch
    if epoch is None or (expected_epoch is not None and epoch != expected_epoch):
        raise ValueError('live enemy observations require a confirmed snapshot link')
    profile = b're2-campaign-enemies-v3' if campaign else (b're2-enemy-live-v2' if death_evidence else b're2-enemy-live-v1')
    lane = sha256(profile + bytes.fromhex(session_id + request_id)).digest()[:16]
    current, published, last_available = None, None, None
    sequence, highest_request = 0, 0
    incoming_attachment = b''
    hit_window = CampaignHitWindow() if hits is not None and role == b'H' else None
    challenge = b''
    fields = {FLAG, _HIT_CHALLENGE} if campaign else {FLAG}
    end_reason = 'stream_interrupted'
    next_poll = 0.0

    def poll_while_waiting():
        nonlocal next_poll
        now = time.monotonic()
        if now >= next_poll:
            feed.poll()
            next_poll = now + POLL_INTERVAL

    def campaign_request(number):
        counter = number.to_bytes(4, 'big')
        return counter + sha256(lane + counter).digest()[:12]

    def accept_request(request, attachment):
        nonlocal sequence, highest_request, incoming_attachment
        number = int.from_bytes(request[:4], 'big')
        if number <= highest_request or request != campaign_request(number):
            return False
        incoming_attachment = attachment
        sequence = highest_request = number
        return True

    def capture():
        nonlocal current, incoming_attachment
        if death_evidence:
            poll_while_waiting()
        else:
            feed.poll()
        sample = feed.latest
        if hit_window is not None:
            payload = hit_window.accept(incoming_attachment, feed.campaign_visit)
            hits.accept(payload, feed.checkpoint, sample.get('campaign_area'), feed.campaign_visit)
        incoming_attachment = b''
        keys = ('available', 'reason', 'continuous', 'enemies', 'death_observations', 'campaign_area')
        changed = current is None or any(sample.get(key) != current.get(key) for key in keys)
        replica = Replica(session_id=lane.hex(), sequence=sequence)
        replica.state['flags'][FLAG] = sample if campaign or changed else None
        if campaign:
            replica.state['flags'][_HIT_CHALLENGE] = hit_window.next() if hit_window is not None else None
        if changed:
            current = sample
        return replica.snapshot()

    def verify(snapshot):
        nonlocal current, last_available, challenge
        state = snapshot['state']
        if (snapshot['sequence'] != sequence or state['flags'].keys() != fields
                or any(value for key, value in state.items() if key != 'flags')):
            raise ValueError('unexpected Steam live enemy snapshot')
        sample = state['flags'][FLAG]
        if sample is None:
            if campaign or current is None:
                raise ValueError('Steam live enemy stream has no complete observation')
            return
        validate_live_view(sample)
        if campaign:
            token = state['flags'][_HIT_CHALLENGE]
            challenge = b''
            if token is not None:
                if not sample['available'] or not isinstance(token, str) or len(token) != 2 * CHALLENGE_BYTES:
                    raise ValueError('invalid campaign hit window')
                challenge = bytes.fromhex(token)
                if challenge.hex() != token:
                    raise ValueError('invalid campaign hit window')
        if sample['available']:
            if ('death_observations' in sample) != death_evidence:
                raise ValueError('unexpected Steam death observation profile')
            if ('campaign_area' in sample) != campaign:
                raise ValueError('unexpected Steam enemy campaign area profile')
            if last_available is not None:
                old_sequence = last_available['observer_sequence']
                new_sequence = sample['observer_sequence']
                if new_sequence < old_sequence or (new_sequence == old_sequence
                        and (not campaign or sample != last_available or current is not last_available)):
                    raise ValueError('Steam live enemy observation sequence rolled back or diverged')
            last_available = sample
        current = sample

    def deliver(output, local_feed=None):
        nonlocal published
        if publish is not None:
            if local_feed is None:
                publish(output)
            else:
                publish(output, local_feed)
        if emit is not None and output != published:
            emit(output)
            published = output

    try:
        for attempt in range(1, (0xffffffff if updates is None else updates) + 1):
            if stop is not None and stop.is_set():
                break
            options = {'expected_epoch': epoch, 'timeout': LIVE_TIMEOUT, 'stop': stop}
            if campaign and role == b'H':
                request = None
                options['accept_request'] = accept_request
            else:
                sequence = attempt
                counter = sequence.to_bytes(4, 'big')
                request = campaign_request(sequence).hex() if campaign else sha256(lane + counter).hexdigest()[:32]
            try:
                if role == b'H':
                    transfer(transport, role, lane.hex(), request, capture=capture,
                             on_idle=poll_while_waiting if death_evidence else None, **options)
                else:
                    if attempt > 1:
                        time.sleep(LIVE_INTERVAL)
                    attachment = hits.outgoing() if challenge and hits is not None else b''
                    transfer(transport, role, lane.hex(), request, verify=verify,
                             first_pull=challenge + attachment if attachment else b'', **options)
            except OSError:
                if not campaign or transport.epoch != epoch:
                    raise
                # A new guest request supersedes an incomplete transfer on this peer epoch.
                if role == b'G':
                    challenge = b''
                    deliver(unavailable_view('stream_interrupted'))
                else:
                    time.sleep(LIVE_INTERVAL)
                continue
            if on_exchange is not None:
                on_exchange()
            if role == b'G':
                feed.poll()
                deliver(matching_live_view(current, feed.latest), feed)
        end_reason = 'stopped'
    except KeyboardInterrupt:
        end_reason = 'stopped'
        raise
    finally:
        if role == b'G':
            deliver(unavailable_view(end_reason))


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
    return EnemyLiveFeed(args.data, args.load_request_id, catalog.select(args.save_slot),
                         death_evidence=args.death_evidence and args.role == 'host')


def confirm_prepared_checkpoint(transport, role, witness, session_id, request_id, *, resume=None, stop=None):
    session, request = _transfer_ids(session_id, request_id)
    # Reserve separate request IDs for the two-phase checkpoint exchange.
    phase_ids = sha256(b're2-prepared-checkpoint-v2' + session + request).hexdigest()
    comparison_request, confirmation_request = phase_ids[:32], phase_ids[32:]
    deadline = time.monotonic() + TIMEOUT
    if role == b'H':
        snapshot = transfer(transport, role, session_id, comparison_request,
                            capture=lambda: witness.capture(session_id), stop=stop)
    else:
        snapshot = transfer(transport, role, session_id, comparison_request, verify=witness.confirm, stop=stop)

    epoch = transport.epoch
    report = None

    def verify_confirmation(confirmation):
        nonlocal report
        if confirmation != snapshot:
            raise ValueError('final checkpoint confirmation differs from the original snapshot')
        report = witness.confirm(confirmation)

    def capture_confirmation():
        verify_confirmation(snapshot)
        return snapshot

    # Complete a second transfer on the same peer epoch. Its pull follows the
    # guest's first acknowledgment, and the guest verifies again before acknowledging it.
    callbacks = {'capture': capture_confirmation} if role == b'H' else {'verify': verify_confirmation}
    try:
        transfer(transport, role, session_id, confirmation_request, expected_epoch=epoch,
                 timeout=deadline - time.monotonic(), stop=stop, **callbacks)
    except TimeoutError as exc:
        raise TimeoutError('no final checkpoint confirmation on the current Steam peer link') from exc
    if resume is not None:
        if report['attempt_id'] != request_id:
            raise ValueError('resume requires the exact prepared lobby attempt')
        # The guest pulls this only after verifying the checkpoint twice. The
        # host sends it only after receiving the guest's final checkpoint ACK.
        resume_request = sha256(b're2-prepared-campaign-resume-v1' + session + request).hexdigest()[:32]
        def verify_resume(confirmation):
            resume()
            verify_confirmation(confirmation)

        def capture_resume():
            verify_resume(snapshot)
            return snapshot

        callbacks = {'capture': capture_resume} if role == b'H' else {'verify': verify_resume}
        transfer(transport, role, session_id, resume_request, expected_epoch=epoch,
                 timeout=deadline - time.monotonic(), stop=stop, **callbacks)

        def window_open():
            return time.monotonic() < deadline and (stop is None or not stop.is_set())

        def check_release():
            if not window_open():
                raise TimeoutError('campaign resume window closed')
            verify_resume(snapshot)
            if not window_open():
                raise TimeoutError('campaign resume window closed')

        def receive_release(expected, error, challenge=None):
            while window_open():
                payload = transport.receive()
                if transport.role != role or transport.epoch != epoch:
                    raise OSError('RE2 Steam peer changed before campaign resume')
                if payload is not None and len(payload) == _RESUME_FRAME.size:
                    kind, received_session, received_attempt, received_challenge = _RESUME_FRAME.unpack(payload)
                    if ((kind, received_session, received_attempt) == (expected, session, request)
                            and (challenge is None or received_challenge == challenge) and window_open()):
                        return received_challenge
                time.sleep(0.01)
            raise TimeoutError(error)

        if role == b'H':
            check_release()
            challenge = secrets.token_bytes(16)
            transport.send_payload(_RESUME_FRAME.pack(_RESUME_OFFER, session, request, challenge))
            receive_release(_RESUME_ACCEPT, 'guest did not accept the campaign resume on the current Steam peer link',
                            challenge)
            check_release()
            transport.send_payload(_RESUME_FRAME.pack(_RESUME_COMMIT, session, request, challenge))
            if not window_open():
                raise TimeoutError('campaign resume window closed')
        else:
            challenge = receive_release(_RESUME_OFFER, 'host did not offer the campaign resume on the current Steam peer link')
            check_release()
            transport.send_payload(_RESUME_FRAME.pack(_RESUME_ACCEPT, session, request, challenge))
            receive_release(_RESUME_COMMIT, 'host did not commit the campaign resume on the current Steam peer link',
                            challenge)
            check_release()
        return {**report, 'resume_authorized': True, 'release_id': challenge.hex()}
    return report


class CampaignReleaseLink:
    """Exchange evidence of the native pause release while this attempt is live."""

    def __init__(self, transport, role, session_id, attempt_id, release_id):
        session, attempt = _transfer_ids(session_id, attempt_id)
        if not isinstance(release_id, str) or not v1.REQUEST_ID.fullmatch(release_id):
            raise ValueError('invalid campaign release ID')
        self.transport = transport
        self.role = role
        self.epoch = transport.epoch
        self.prefix = _RESUME_FRAME.pack(_RELEASE_HEARTBEAT, session, attempt, bytes.fromhex(release_id))
        self.next_send = 0.0
        self.sent = self.received = 0

    def poll(self, local_released, now):
        payload = self.transport.receive()
        if self.transport.role != self.role or self.transport.epoch != self.epoch:
            raise OSError('RE2 Steam peer changed after campaign resume')
        if not local_released:
            return False
        if now >= self.next_send:
            self.sent += 1
            self.transport.send_payload(self.prefix + self.sent.to_bytes(8, 'big'))
            self.next_send = now + 1.0
        if (payload is None or len(payload) != len(self.prefix) + 8
                or not payload.startswith(self.prefix)):
            return False
        sequence = int.from_bytes(payload[-8:], 'big')
        if sequence <= self.received:
            return False
        self.received = sequence
        return True


def compare_interrupted_checkpoint(transport, role, witness, session_id, request_id):
    """Compare the currently interrupted campaign and return the result to both peers."""
    session, request = _transfer_ids(session_id, request_id)
    deadline = time.monotonic() + TIMEOUT
    if role == b'H':
        original = transfer(transport, role, session_id, request_id, capture=lambda: witness.capture(session_id))
        epoch = transport.epoch
        while time.monotonic() < deadline:
            payload = transport.receive()
            if transport.role != role or transport.epoch != epoch:
                raise OSError('RE2 Steam peer changed during interrupted checkpoint comparison')
            if payload is not None and len(payload) == _INTERRUPTED_RESULT.size:
                received_kind, received_session, received_request, mask = _INTERRUPTED_RESULT.unpack(payload)
                if ((received_kind, received_session, received_request) == (_INTERRUPTED_COMPARE, session, request)
                        and mask < 2**len(INTERRUPTED_COMPONENTS)):
                    if witness.capture(session_id) != original:
                        raise ValueError('local interrupted checkpoint changed during comparison')
                    return {key: bool(mask & (1 << index)) for index, key in enumerate(INTERRUPTED_COMPONENTS)}
            time.sleep(0.02)
        raise TimeoutError('no interrupted checkpoint result from the current Steam peer')

    checked = local = None

    def verify(snapshot):
        nonlocal checked, local
        local = witness.capture(session_id)
        checked = witness.compare(snapshot, local)

    transfer(transport, role, session_id, request_id, verify=verify)
    if witness.capture(session_id) != local:
        raise ValueError('local interrupted checkpoint changed during comparison')
    mask = sum(1 << index for index, key in enumerate(INTERRUPTED_COMPONENTS) if checked[key])
    transport.send_payload(_INTERRUPTED_RESULT.pack(_INTERRUPTED_COMPARE, session, request, mask))
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True, help='REFramework data directory')
    parser.add_argument('--pid', type=int, required=True, help='RE2 process ID')
    parser.add_argument('--role', choices=('host', 'guest'), required=True)
    parser.add_argument('--file', type=Path, help='host input or guest output v1 snapshot')
    native = parser.add_mutually_exclusive_group()
    native.add_argument('--native-enemies', action='store_true',
                        help='host a fresh guarded enemy observation or compare it on the guest')
    native.add_argument('--prepared-checkpoint', action='store_true',
                        help='compare the native checkpoint for the current guarded Steam lobby attempt')
    native.add_argument('--interrupted-checkpoint', action='store_true',
                        help='compare the guarded campaign after both peers reconnect in the owned pause')
    parser.add_argument('--load-request-id', help='local guarded native load request ID')
    parser.add_argument('--save-slot', help='native scenario key from the guarded host load')
    parser.add_argument('--allow-save-date', help='approved local save calendar date (YYYY-MM-DD)')
    parser.add_argument('--live-updates', type=int, help='follow native enemies for this many guest pulls (1-120)')
    parser.add_argument('--death-evidence', action='store_true', help='include confirmed native death observations')
    parser.add_argument('--snapshot-pipe', action='store_true', help='use the dedicated Steam snapshot endpoint')
    parser.add_argument('--export-live-enemies', action='store_true', help='publish a local REFramework guest receipt')
    parser.add_argument('--session-id', help='host snapshot session ID, required on the guest')
    parser.add_argument('--request-id', help='fresh transfer request ID shown by the host')
    args = parser.parse_args()
    is_host = args.role == 'host'
    if (is_host and (args.session_id or args.request_id)
            or not is_host and not (args.session_id and args.request_id)):
        parser.error('supply --session-id and --request-id on the guest only')
    witness_options = (args.load_request_id, args.save_slot, args.allow_save_date)
    if args.prepared_checkpoint or args.interrupted_checkpoint:
        if args.file is not None or any(witness_options):
            parser.error('checkpoint modes use only the guarded native state')
    elif args.native_enemies:
        if not all(witness_options):
            parser.error('--native-enemies requires --load-request-id, --save-slot and --allow-save-date')
        if is_host == (args.file is not None):
            parser.error('with --native-enemies, supply --file on the guest only')
    elif args.file is None or any(witness_options):
        parser.error('supply --file or select a native observation mode')
    if args.live_updates is not None and (not args.native_enemies or not 1 <= args.live_updates <= 120):
        parser.error('--live-updates requires --native-enemies and 1-120 updates')
    if args.export_live_enemies and (is_host or args.live_updates is None):
        parser.error('--export-live-enemies requires the guest role and --live-updates')
    if args.death_evidence and args.live_updates is None:
        parser.error('--death-evidence requires --live-updates')
    if sys.platform != 'win32' or not args.data.is_dir() or not 0 < args.pid <= 0xffffffff:
        parser.error('expected Windows, an existing REFramework data directory and a valid process ID')
    checkpoint = args.prepared_checkpoint or args.interrupted_checkpoint
    stream = 'snapshot' if args.snapshot_pipe or checkpoint else 'pose'
    try:
        with lock_data_directory(args.data, stream=stream):
            pipe = SteamPipe(args.pid, stream=stream)
            if checkpoint:
                role = b'H' if is_host else b'G'
                session_id, request_id = args.session_id, args.request_id
                if is_host:
                    session_id, request_id = secrets.token_hex(16), secrets.token_hex(16)
                    print(f'--session-id {session_id} --request-id {request_id}', flush=True)
                if args.interrupted_checkpoint:
                    witness = InterruptedCheckpoint(args.data, args.pid, role.decode('ascii'))
                    report = compare_interrupted_checkpoint(pipe, role, witness, session_id, request_id)
                else:
                    witness = PreparedCheckpoint(args.data, args.pid, role.decode('ascii'))
                    report = confirm_prepared_checkpoint(pipe, role, witness, session_id, request_id)
                print(json.dumps(report, sort_keys=True), flush=True)
                return 0
            output = GuestEnemyFile(args.data, args.session_id) if args.export_live_enemies else None
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
                                  emit=lambda view: print(json.dumps(view, sort_keys=True), flush=True),
                                  publish=output.publish if output is not None else None,
                                  death_evidence=args.death_evidence)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        print(f'Steam snapshot transfer stopped: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
