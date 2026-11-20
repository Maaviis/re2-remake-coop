"""Bounded framing for a complete authoritative v1 snapshot."""

from hashlib import sha256
from struct import Struct
import time

from protocol import v1
from sync_model import state_digest


MAX_PACKET_BYTES = 4096
MAX_SNAPSHOT_BYTES = 1024 * 1024
TRANSFER_TIMEOUT = 5
_MAGIC = b'R2S\x01'
_HEADER = Struct('!4s16s16sQII32s')
_CHUNK_BYTES = MAX_PACKET_BYTES - _HEADER.size


def _token(value):
    if not isinstance(value, str) or not v1.REQUEST_ID.fullmatch(value):
        raise v1.ProtocolError('expected a 32-character lowercase hex identifier')
    return bytes.fromhex(value)


def snapshot_packets(snapshot, request_id):
    """Encode a host snapshot for the request ID supplied by its guest."""
    request = _token(request_id)
    payload = v1.encode({'version': v1.VERSION, 'type': 'snapshot', 'data': snapshot})
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise v1.ProtocolError('snapshot exceeds the transfer byte limit')
    session = _token(snapshot['session_id'])
    digest = sha256(payload).digest()
    return tuple(
        _HEADER.pack(_MAGIC, session, request, snapshot['sequence'], len(payload), index, digest)
        + payload[offset:offset + _CHUNK_BYTES]
        for index, offset in enumerate(range(0, len(payload), _CHUNK_BYTES))
    )


class SnapshotReceiver:
    """Stage one requested snapshot from the caller's authenticated host."""

    def __init__(self, replica, session_id, request_id, *, clock=time.monotonic, timeout=TRANSFER_TIMEOUT):
        self._replica = replica
        self._session = _token(session_id)
        self._request = _token(request_id)
        self._clock = clock
        self._deadline = clock() + timeout
        self._metadata = None
        self._chunks = {}
        self._closed = False

    def matches(self, packet):
        """Identify frames for this request on a multiplexed transport."""
        return packet.startswith(_MAGIC + self._session + self._request)

    @property
    def contiguous_chunks(self):
        """Count the consecutive staged fragments from index zero."""
        return next(index for index in range(len(self._chunks) + 1) if index not in self._chunks)

    def close(self):
        """Cancel when the connection or membership that owns the request ends."""
        self._closed = True
        self._chunks.clear()

    def expire(self):
        """Release buffered data when polling a transport with no new packets."""
        if self._closed or self._clock() < self._deadline:
            return False
        self.close()
        return True

    def receive(self, packet):
        """Return True once a complete snapshot has been restored to the replica."""
        if self.expire():
            raise v1.ProtocolError('snapshot transfer expired')
        if self._closed:
            return False
        if not isinstance(packet, bytes) or not _HEADER.size < len(packet) <= MAX_PACKET_BYTES:
            raise v1.ProtocolError('invalid snapshot packet size')
        magic, session, request, sequence, size, index, digest = _HEADER.unpack_from(packet)
        if magic != _MAGIC or session != self._session or request != self._request:
            raise v1.ProtocolError('snapshot packet belongs to a different format, session or request')
        offset = index * _CHUNK_BYTES
        chunk = packet[_HEADER.size:]
        if (not 0 < size <= MAX_SNAPSHOT_BYTES or sequence > v1.MAX_SAFE_INTEGER
                or offset >= size or len(chunk) != min(_CHUNK_BYTES, size - offset)):
            raise v1.ProtocolError('invalid snapshot chunk bounds')

        metadata = (sequence, size, digest)
        if self._metadata is None:
            self._metadata = metadata
        if metadata != self._metadata or (index in self._chunks and self._chunks[index] != chunk):
            self.close()
            raise v1.ProtocolError('conflicting snapshot packets')
        self._chunks[index] = chunk
        count = (size + _CHUNK_BYTES - 1) // _CHUNK_BYTES
        if len(self._chunks) < count:
            return False

        payload = b''.join(self._chunks[index] for index in range(count))
        self.close()
        if sha256(payload).digest() != digest:
            raise v1.ProtocolError('snapshot transfer digest mismatch')
        message = v1.decode(payload)
        if message['type'] != 'snapshot':
            raise v1.ProtocolError('expected an authoritative snapshot')
        snapshot = message['data']
        if snapshot['session_id'] != session.hex() or snapshot['sequence'] != sequence:
            raise v1.ProtocolError('snapshot does not match its packet headers')
        if (self._replica.session_id == snapshot['session_id']
                and self._replica.sequence == sequence
                and state_digest(self._replica.state) != snapshot['digest']):
            raise v1.ProtocolError('snapshot changes the current authoritative sequence')
        try:
            self._replica.restore(snapshot)
        except (ValueError, RecursionError) as exc:
            raise v1.ProtocolError(str(exc)) from exc
        return True
