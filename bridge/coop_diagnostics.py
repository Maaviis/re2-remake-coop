"""Session-scoped troubleshooting records on the authenticated lobby connection."""
from collections import deque
from datetime import datetime, timezone
from itertools import islice
import json
import re
import time
import unicodedata
from pathlib import Path

from protocol import v1


ENGINE_LINE = re.compile(
    rb"^\[([\d-]+ [\d:.]+)\] \[REFramework\] \[(info|warning|error|critical)\] "
    rb"(?:\[Plugin\] )?RE2_COOP_([A-Z_]{1,32}) (.*)$")
# Only project-owned diagnostic formats may carry native text across the link.
ENGINE_DETAIL = {
    "CUTSCENE": r"(?:(?:peer |menu )?evt_\d{1,8}/\d{1,8}/(?:waiting/|playing/|ended/)?\d{1,8}/(?:none|request|accept|decline)|native skip requested: (?:skipEventPauseUI|skip|requestSkip))",
    "CAMPAIGN_POSE": r"[a-z_]{1,64}",
    "CAMPAIGN_AVATAR": r"[a-z_]{1,64}",
    "GUEST_EQUIPMENT": r"[a-z_]{1,64}",
    "SAVE_GUARD": r"prepare=(?:installing_hooks|hooks_queued|hooks_active|mount_confirmed)",
    "NATIVE_SAVE_GUARD": r"(?:(?:campaign_lost|active=[01] reason)=[a-z_]{1,64}|status export failed)",
    "STEAM_LOBBY": (r"(?:revoke_campaign=[a-z_]{1,64}|requested invite dialog|guest membership ended|"
                    r"Steam user is offline|Steam lobby request failed|Steam join failed response=\d{1,4}|"
                    r"create failed result=\d{1,4}|rejecting incompatible lobby or member list|"
                    r"rejecting unexpected lobby or owner|RE2 Steam context unavailable|"
                    r"joined as guest; verified owner and two members|LeaveLobby called for the probe lobby|"
                    r"created app=883710 local_owner=[01] members=\d limit=2)"),
    "STEAM_PEER": r"(?:ping timed out|round trip verified for current lobby member|reply failed result=\d{1,4})",
    "LOBBY_INPUT": r"(?:true|false):[a-z_]{1,48}",
}


def symbol(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-zA-Z_]{1,64}", value) else "unknown"


def iso(stamp):
    return datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat(timespec="milliseconds")


class SessionDiagnostics:
    def __init__(self, data, pid, role, build):
        self.data, self.pid, self.role = data, pid, role
        self.build = build if isinstance(build, str) and re.fullmatch(r"[0-9a-f]{40}", build) else "unknown"
        self.engine = data.parent.parent / "re2_framework_log.txt"
        self.scope = None
        self.pending = deque(maxlen=256)
        self.flight = None

    def bind(self, scope):
        if not all(isinstance(s, str) and v1.REQUEST_ID.fullmatch(s) for s in scope):
            scope = None
        if self.scope == scope:
            return
        self.close("handshake_changed")
        if not scope:
            return
        self.scope = scope
        self.batch = self.received = self.lost = 0
        self.poll_at = self.send_at = self.receive_at = 0
        self.last_status = self.last_selection = self.last_loss = self.last_release = None
        self.receipt_stamps = {}
        self.opened = time.time()
        self.offset = self.file_id = None
        self.fragment = b""
        self.path = self.data / "re2_coop_logs" / scope[0] / "timeline.jsonl"
        self.note("BRIDGE", f"connected pid={self.pid} build={self.build}")
        for name in ("campaign_binding_loss", "campaign_release_status"):
            path = self.data / f"re2_coop_{name}.json"
            try:
                self.receipt_stamps[name] = path.stat().st_mtime_ns
            except OSError:
                pass
        try:
            stat = self.engine.stat()
            self.offset, self.file_id = stat.st_size, stat.st_ino
        except OSError:
            self.offset = 0

    def note(self, component, detail, stamp=None):
        if self.scope:
            if len(self.pending) == self.pending.maxlen:
                self.lost += 1
            if stamp is None or not 0 <= stamp <= 4102444800000:
                stamp = int(time.time() * 1000)
            self.pending.append([stamp, component, re.sub(r"[^ -~]", " ", detail[:220])])

    def error(self, exc):
        # Dynamic exception text can include an entire local path. A literal error
        # authored at the raise site is safe; otherwise report type, code and site.
        trace = exc.__traceback__
        detail = symbol(type(exc).__name__)
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
        if type(code) is int:
            detail += f" system_code={code}"
        if trace:
            while trace.tb_next:
                trace = trace.tb_next
            site = trace.tb_frame.f_code
            detail += f" {symbol(Path(site.co_filename).stem)}.{symbol(site.co_name)}:{trace.tb_lineno}"
            if (Path(site.co_filename).parent == Path(__file__).parent and str(exc) in site.co_consts
                    and not any(c in str(exc) for c in "\\/\r\n")):
                detail += " " + unicodedata.normalize("NFKD", str(exc)).encode("ascii", "ignore").decode()
        self.note("ERROR", detail[:220])

    def _write(self, role, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size >= 2 * 1024 * 1024:
            self.path.replace(self.path.with_suffix(".previous.jsonl"))
        received = iso(int(time.time() * 1000))
        with self.path.open("a", encoding="utf-8") as output:
            for stamp, component, detail in records:
                print(json.dumps(dict(at=iso(stamp), host_received=received, role=role, join=self.scope[1],
                                      component=component, detail=detail)), file=output)

    def close(self, reason="bridge_stopped"):
        if self.scope and self.role == "H":
            try:
                self._engine_changes()
                self.note("BRIDGE", f"{symbol(reason)} guest_batches_received={self.received}")
                self._write("Host", self.pending)
            except OSError:
                pass
        self.scope = self.flight = None
        self.pending.clear()

    def _engine_changes(self):
        try:
            stat = self.engine.stat()
            if stat.st_ino != self.file_id or stat.st_size < self.offset:
                self.file_id, self.offset, self.fragment = stat.st_ino, 0, b""
            if stat.st_size == self.offset:
                return
            with self.engine.open("rb") as stream:
                stream.seek(self.offset)
                raw = stream.read(65536)
                self.offset += len(raw)
        except OSError:
            return
        lines = (self.fragment + raw).split(b"\n")
        self.fragment = lines.pop()[:2048]
        for line in lines:
            match = ENGINE_LINE.fullmatch(line.rstrip(b"\r"))
            if not match:
                continue
            when, level, component, detail = (v.decode("ascii", "replace") for v in match.groups())
            if component == "GUEST_EQUIPMENT" and "missing_method:app.ropeway." in detail:
                detail = "missing_native_method"
            if not re.fullmatch(ENGINE_DETAIL.get(component, r"(?!)"), detail):
                if level == "info":
                    continue
                # Keep the project source location, never the user's full path or
                # arbitrary exception payload (third-party mods share this file).
                site = re.search(r"(?:[/\\])([a-z_]{1,55}\.lua):(\d{1,6}):", detail)
                category = next((name for name in ("native skip", "camera skip", "unavailable", "cleanup failed")
                                 if detail.startswith(name + ":")), "engine error")
                detail = category + (f" at {site[1]}:{site[2]}" if site else " (details local)")
            try:
                stamp = int(datetime.fromisoformat(when).timestamp() * 1000)
            except (ValueError, OSError, OverflowError):
                continue
            if self.opened - 1 <= stamp / 1000 <= time.time() + 1:
                self.note(component, level + " " + detail, stamp)

    def _receipt(self, name):
        path = self.data / f"re2_coop_{name}.json"
        try:
            stamp = path.stat().st_mtime_ns
            if self.receipt_stamps.get(name) == stamp:
                return {}
            with path.open("rb") as stream:
                payload = stream.read(65537)
            if len(payload) > 65536:
                return {}
            value = json.loads(payload)
            self.receipt_stamps[name] = stamp
        except (OSError, ValueError, RecursionError):
            return {}
        return value if isinstance(value, dict) and value.get("game_pid") == self.pid and value.get("role") == self.role else {}

    def _changes(self, status):
        self._engine_changes()
        if isinstance(status, dict):
            state = (symbol(status.get("steam_lobby")), symbol(status.get("guest_preparation")),
                     status.get("direct_campaign_prepared") is True, status.get("new_game_supported") is True,
                     (status.get("steam_membership") or {}).get("revision"))
            if state != self.last_status:
                self.last_status = state
                self.note("LOBBY", "steam=%s guest_preparation=%s prepared=%s new_game=%s revision=%s" % state)
            lobby = (status.get("lobby") or {}).get("data") or {}
            ready = lobby.get("ready") or {}
            check = lobby.get("load_check") or {}
            selection = (lobby.get("revision"), ready.get(lobby.get("host_id")) is True,
                         ready.get(lobby.get("guest_id")) is True, symbol(check.get("phase")), symbol(check.get("reason")))
            if lobby and selection != self.last_selection:
                self.last_selection = selection
                self.note("LOBBY", "revision=%s host_ready=%s guest_ready=%s load=%s reason=%s" % selection)
        loss = self._receipt("campaign_binding_loss")
        at = loss.get("at")
        if type(at) is int and self.opened <= at + 1 and loss != self.last_loss:
            self.last_loss = loss
            self.note("GUARD", "binding_loss=" + symbol(loss.get("cause")) + " check=" + symbol(loss.get("check")), at * 1000)
        release = self._receipt("campaign_release_status")
        attempt = release.get("attempt_id")
        attempt = attempt if isinstance(attempt, str) and v1.REQUEST_ID.fullmatch(attempt) else "unknown"
        transitions = release.get("transitions")
        if isinstance(transitions, list):
            # The release writer retains a bounded transition history, including short-lived phases.
            recent = []
            for row in transitions:
                if not isinstance(row, dict) or type(row.get("at")) is not int or row["at"] + 1 < self.opened:
                    continue
                reason = row.get("detail")
                if isinstance(reason, str) and "(binding changed: campaign_namespace)" in reason:
                    reason = "campaign_namespace_changed"
                detail = "attempt=" + attempt + " phase=" + symbol(row.get("phase")) + " reason=" + symbol(reason)
                for key in ("heartbeat_sent", "heartbeat_received", "last_peer_ms_ago", "local_pipe_delays"):
                    if type(row.get(key)) is int:
                        detail += f" {key}={row[key]}"
                recent.append((row["at"], detail[:220]))
            marker = (release.get("attempt_id"), recent)
            if marker != self.last_release:
                previous = self.last_release[1] if self.last_release and self.last_release[0] == marker[0] else []
                for stamp, detail in recent:
                    if (stamp, detail) not in previous:
                        self.note("RELEASE", detail, stamp * 1000)
                self.last_release = marker

    def tick(self, transport, scope, status, message, now):
        self.bind(scope)
        if not self.scope:
            return
        session, join = self.scope
        packet = dict(version=1, session_id=session, request_id=join)
        try:
            if message and (message["session_id"], message["request_id"]) == self.scope:
                n = message["batch"]
                if self.role == "H" and message["type"] == "coop_log" and now >= self.receive_at:
                    self.receive_at = now + .25
                    if n == self.received + 1:
                        self._write("Gast", message["records"])
                        self.received = n
                    if n == self.received:
                        transport.send(dict(packet, type="coop_log_ack", batch=n))
                elif self.role == "G" and message["type"] == "coop_log_ack" and self.flight and n == self.batch:
                    self.flight = None
                    self.send_at = 0
            if now < self.poll_at:
                return
            self.poll_at = now + .5
            self._changes(status)
            if self.lost:
                self.note("BRIDGE", f"diagnostic queue overflow: {self.lost + int(len(self.pending) == self.pending.maxlen)} omitted")
                self.lost = 0
            if self.role == "H" and self.pending:
                self._write("Host", self.pending)
                self.pending.clear()
            elif self.role == "G" and now >= self.send_at and (self.flight or self.pending):
                if not self.flight:
                    self.batch += 1
                    self.flight = list(islice(self.pending, 8))
                    for _ in self.flight:
                        self.pending.popleft()
                self.send_at = now + 2
                transport.send(dict(packet, type="coop_log", batch=self.batch, records=self.flight))
        except (OSError, ValueError, OverflowError):
            # A diagnostic failure never withdraws the protected campaign.
            return
