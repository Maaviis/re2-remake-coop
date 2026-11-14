"""Lobby und gemeinsame Checkpoints; noch ohne RE2- oder Steam-Anbindung."""

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sync_model import Host


@dataclass
class Lobby:
    host_id: str
    save_slot: str | None = None
    settings: dict = field(default_factory=dict)
    guest_id: str | None = None
    connected: bool = False
    ready: dict = field(default_factory=dict)
    started: bool = False
    revision: int = 0

    def __post_init__(self):
        self.ready = {self.host_id: False}

    def select_save(self, player_id, slot):
        self._require_waiting()
        self._require_host(player_id)
        if not slot:
            raise ValueError("save slot required")
        if slot != self.save_slot:
            self.save_slot = slot
            self._configuration_changed()

    def configure(self, player_id, **settings):
        self._require_waiting()
        self._require_host(player_id)
        if any(self.settings.get(key) != value for key, value in settings.items()):
            self.settings.update(settings)
            self._configuration_changed()

    def join(self, guest_id):
        self._require_waiting()
        if not guest_id or guest_id == self.host_id or self.guest_id:
            raise ValueError("invalid or occupied guest slot")
        self.guest_id = guest_id
        self.connected = True
        self.ready[guest_id] = False

    def disconnect(self):
        self.connected = False
        self._reset_ready()

    def reconnect(self, guest_id):
        if guest_id != self.guest_id:
            raise ValueError("guest identity mismatch")
        self.connected = True
        self._reset_ready()

    def set_ready(self, player_id, value, revision):
        self._require_waiting()
        if player_id not in self.ready:
            raise ValueError("unknown player")
        if player_id == self.guest_id and not self.connected:
            raise ValueError("guest is disconnected")
        if type(value) is not bool or type(revision) is not int or revision != self.revision:
            raise ValueError("readiness requires the current configuration revision")
        self.ready[player_id] = value

    def start(self):
        self._require_waiting()
        if not self.save_slot or not self.connected or len(self.ready) != 2 or not all(self.ready.values()):
            raise ValueError("lobby is not ready")
        self.started = True

    def _reset_ready(self):
        self.ready = {player: False for player in self.ready}

    def _configuration_changed(self):
        self.revision += 1
        self._reset_ready()

    def _require_host(self, player_id):
        if player_id != self.host_id:
            raise ValueError("only the host may change lobby configuration")

    def _require_waiting(self):
        if self.started:
            raise ValueError("session already started")


def save_checkpoint(path, host: Host, lobby: Lobby):
    """Write one complete shared checkpoint with atomic replacement."""
    if not lobby.started or not lobby.save_slot:
        raise ValueError("active session and save slot required")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"format": 1, "save_slot": lobby.save_slot,
               "settings": lobby.settings, "snapshot": host.snapshot()}
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    temp_name = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp_name.open("w", encoding="utf-8") as stream:
            stream.write(data)
        os.replace(temp_name, path)
    finally:
        if temp_name.exists():
            os.unlink(temp_name)


def load_checkpoint(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("format") != 1:
        raise ValueError("unsupported checkpoint format")
    host = Host(session_id=payload["snapshot"]["session_id"])
    host.restore(payload["snapshot"])
    return host, payload["save_slot"], payload["settings"]

