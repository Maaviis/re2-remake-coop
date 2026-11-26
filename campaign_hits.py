"""Carry recent, positive guest hit evidence through the protected campaign link."""

import json
from pathlib import Path
import secrets
import time

from load_witness import MAX_AGE, _integer, _read_json, GUID
from lobby_sync import write_json
from observer import valid_campaign_area
from protocol.v1 import _unique_object


MAX_HITS = 8
MAX_ATTACHMENT = 1536
CHALLENGE_BYTES = 12
CHALLENGE_LIFETIME = 2.0
_FIELDS = {'sequence', 'id', 'kind_id', 'inherit_id', 'default_hp', 'damage'}


def _valid_batch(area, hits):
    if not valid_campaign_area(area) or not isinstance(hits, list) or not 0 < len(hits) <= MAX_HITS:
        return False
    previous = 0
    for hit in hits:
        if (not isinstance(hit, dict) or hit.keys() != _FIELDS or not _integer(hit['sequence'], previous + 1)
                or not isinstance(hit['id'], str) or not GUID.fullmatch(hit['id'])
                or hit['id'] == '00000000-0000-0000-0000-000000000000'
                or not _integer(hit['kind_id'], -(2**31), 2**31 - 1)
                or not _integer(hit['inherit_id'], -(2**31), 2**31 - 1)
                or not _integer(hit['default_hp'], 2, 2**31 - 1)
                or not _integer(hit['damage'], 1, hit['default_hp'] - 1)):
            return False
        previous = hit['sequence']
    return True


def _fresh(timestamp, now):
    return _integer(timestamp, 1, now) and now - timestamp <= MAX_AGE


class CampaignHitWindow:
    """A host-clock lease bounds Steam queue delay without comparing peer wall clocks."""

    def __init__(self):
        self.challenges = {}
        self.visit = None

    def accept(self, attachment, visit):
        now = time.monotonic()
        if visit != self.visit:
            self.challenges.clear()
            self.visit = visit
        while self.challenges and next(iter(self.challenges.values())) < now:
            del self.challenges[next(iter(self.challenges))]
        if self.challenges.pop(attachment[:CHALLENGE_BYTES], None) is not None:
            return attachment[CHALLENGE_BYTES:]
        return b''

    def next(self):
        if self.visit is None:
            return None
        if len(self.challenges) >= MAX_HITS:
            del self.challenges[next(iter(self.challenges))]
        nonce = secrets.token_bytes(CHALLENGE_BYTES)
        self.challenges[nonce] = time.monotonic() + CHALLENGE_LIFETIME
        return nonce.hex()


class CampaignHitFiles:
    def __init__(self, data, request_id, attempt_id):
        self.source = Path(data) / 're2_coop_campaign_guest_hits.json'
        self.target = Path(data) / 're2_coop_campaign_incoming_hits.json'
        self.request_id = request_id
        self.attempt_id = attempt_id
        self.sequence = 0
        self.visit = None
        self.pending = []

    def outgoing(self):
        now = int(time.time())
        try:
            source = _read_json(self.source, max_bytes=4096)
            if (type(source['schema']) is not int or source['schema'] != 1
                    or source['request_id'] != self.request_id or source['attempt_id'] != self.attempt_id
                    or not _fresh(source['at'], now) or not isinstance(source['hits'], list)
                    or len(source['hits']) > MAX_HITS):
                return b''
            hits = [{key: hit[key] for key in _FIELDS} for hit in source['hits'] if _fresh(hit['at'], now)]
            if _valid_batch(source['area'], hits):
                payload = json.dumps({'area': source['area'], 'hits': hits}, separators=(',', ':')).encode()
                if len(payload) <= MAX_ATTACHMENT:
                    return payload
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            pass
        return b''

    def accept(self, payload, checkpoint, local_area, visit):
        if self.visit is not None and visit != self.visit:
            self.withdraw()
        if not payload:
            return True
        if len(payload) > MAX_ATTACHMENT:
            return False
        try:
            batch = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object)
        except (ValueError, RecursionError):
            return False
        if (not isinstance(batch, dict) or batch.keys() != {'area', 'hits'}
                or not _valid_batch(batch['area'], batch['hits'])):
            return False
        area, hits = batch['area'], batch['hits']
        now = int(time.time())
        fresh = [{**hit, 'at': now} for hit in hits if hit['sequence'] > self.sequence]
        if not fresh:
            return True
        if checkpoint is None or visit is None or area != local_area:
            self.sequence = fresh[-1]['sequence']
            return True
        previous = self.pending if self.visit == visit else []
        pending = ([hit for hit in previous if _fresh(hit['at'], now)] + fresh)[-MAX_HITS:]
        write_json(self.target, {'schema': 1, 'request_id': self.request_id, 'attempt_id': self.attempt_id,
                                 'at': now, 'area': area, 'checkpoint': checkpoint, 'host_visit': visit, 'hits': pending})
        self.sequence, self.visit, self.pending = fresh[-1]['sequence'], visit, pending
        return True

    def withdraw(self):
        self.pending.clear()
        self.visit = None
        write_json(self.target, {'schema': 1, 'request_id': self.request_id, 'attempt_id': self.attempt_id,
                                 'at': int(time.time()), 'hits': []})
