"""Reversible installer and launcher for the RE2 two-account diagnostic test."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent
APP = "re2-coop-test"
FOLDERS = ("autorun", "plugins", "data")
DATE = "2026-11-11"
EXPECTED_SLOT4 = "639300365010000000"


def save_date(value):
    message = 'Das freigegebene Save-Datum muss YYYY-MM-DD sein.'
    if not isinstance(value, str):
        raise ValueError(message)
    try:
        canonical = dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(message) from None
    if canonical != value:
        raise ValueError(message)
    return canonical


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    # REFramework's readers may temporarily deny delete sharing. Reuse the
    # bounded atomic writer instead of aborting on one overlapping read.
    from lobby_sync import write_json
    write_json(path, value)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inside(root, path):
    root, path = root.resolve(), path.resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Unsicherer Zielpfad: " + str(path))
    return path


def powershell(command):
    exe = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return subprocess.check_output([str(exe), "-NoProfile", "-NonInteractive", "-Command", command],
                                   text=True, encoding="utf-8-sig", timeout=15,
                                   creationflags=subprocess.CREATE_NO_WINDOW)


def processes():
    value = powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                       "@(Get-Process -Name re2 -ErrorAction SilentlyContinue | ForEach-Object { "
                       "[pscustomobject]@{pid=$_.Id;exe=$_.Path;started=$_.StartTime.ToUniversalTime().ToString('o')} "
                       "}) | ConvertTo-Json -Compress")
    rows = json.loads(value) if value.strip() else []
    return rows if isinstance(rows, list) else [rows]


def require_closed():
    if processes():
        raise ValueError("RE2 bitte vor Installation oder Rueckbau vollstaendig beenden.")


def steam_root():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
        return Path(winreg.QueryValueEx(key, "SteamPath")[0]).resolve()


def find_game(explicit=None):
    if explicit:
        game = Path(explicit).resolve()
    elif (ROOT.parent / "re2.exe").is_file():
        game = ROOT.parent
    elif (ROOT / "installation.json").is_file():
        game = Path(read(ROOT / "installation.json")["game"]).resolve()
    else:
        steam = steam_root()
        libraries = [steam]
        catalog = steam / "steamapps/libraryfolders.vdf"
        if catalog.is_file():
            libraries += [Path(p.replace("\\\\", "\\")) for p in
                          re.findall(r'"path"\s+"([^"\r\n]+)"', catalog.read_text(encoding="utf-8"))]
        found = set()
        for library in libraries:
            manifest = library / "steamapps/appmanifest_883710.acf"
            if manifest.is_file():
                match = re.search(r'"installdir"\s+"([^"\r\n]+)"', manifest.read_text(encoding="utf-8"))
                if match:
                    found.add((library / "steamapps/common" / match[1]).resolve())
        if len(found) != 1:
            raise ValueError('Spielordner bitte mit --game "D:\\...\\RESIDENT EVIL 2  BIOHAZARD RE2" angeben.')
        game = found.pop()
    if not (game / "re2.exe").is_file():
        raise ValueError("Kein RE2-Spielordner: " + str(game))
    return game


def verify_bundle():
    manifest = read(ROOT / "bundle-manifest.json")
    if (manifest.get('save_protection_schema') != 1
            or 'reframework/plugins/re2_coop_steam_save_guard.dll' not in manifest.get('install_files', ())):
        raise ValueError('Altes Testpaket ohne nativen und vererbten Dateischutz wird nicht gestartet.')
    for relative, expected in manifest["files"].items():
        path = inside(ROOT, ROOT / relative)
        if not path.is_file() or digest(path) != expected:
            raise ValueError("Paketdatei fehlt oder wurde veraendert: " + relative)
    return manifest


def save_inventory():
    userdata = steam_root() / "userdata"
    files = []
    for user in userdata.iterdir():
        folder = user / "883710"
        if user.name.isdecimal() and folder.is_dir():
            for path in sorted(folder.rglob("*")):
                if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError("Unerwartete Verknuepfung im Speicherordner.")
                if path.is_file():
                    files.append({"path": str(path), "relative": str(path.relative_to(userdata)), "sha256": digest(path)})
    return files


def install(game, expected_slot4=None, *, allow_save_date=DATE):
    allow_save_date = save_date(allow_save_date)
    require_closed()
    bundle = verify_bundle()
    if not (game / "dinput8.dll").is_file() or (game / "dinput8.dll").stat().st_size < 1024:
        raise ValueError("Zuerst REFramework fuer RE2 installieren; siehe ZUERST_LESEN.md.")
    app = inside(game, game / APP)
    if app.exists():
        raise ValueError("Testinstallation existiert bereits: " + str(app))
    framework = inside(game, game / "reframework")
    for name in FOLDERS:
        inside(game, framework / name)
    backup = inside(game, game / ("re2-coop-backup-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)))
    state = {"schema": 1, "active": False, "game": str(game), "backup": str(backup),
             "source_commit": bundle["source_commit"], "allow_save_date": allow_save_date,
             "moved": [], "configs": [], "saves": []}
    if expected_slot4:
        state["expected_slot4_timestamp"] = expected_slot4
    backup.mkdir()
    state["saves"] = save_inventory()
    for entry in state["saves"]:
        target = inside(backup, backup / "saves" / entry["relative"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry["path"], target)
        if digest(target) != entry["sha256"]:
            raise ValueError("Speichersicherung konnte nicht bestaetigt werden.")
    # Copy and verify our own payload before replacing any existing mod folder.
    app.mkdir()
    for relative, expected in bundle["files"].items():
        target = inside(app, app / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
        if digest(target) != expected:
            raise ValueError("Kopie konnte nicht bestaetigt werden: " + relative)
    shutil.copy2(ROOT / "bundle-manifest.json", app / "bundle-manifest.json")
    write(app / "install-state.json", state)
    try:
        framework.mkdir(exist_ok=True)
        for name in FOLDERS:
            target = inside(game, framework / name)
            existed = target.exists()
            state["moved"].append({"name": name, "existed": existed})
            write(app / "install-state.json", state)
            if existed:
                target.rename(backup / ("original-" + name))
            target.mkdir()
        for relative in bundle["install_files"]:
            source = ROOT / relative
            target = inside(game, game / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if digest(target) != bundle["files"][relative]:
                raise ValueError("Installationspruefung fehlgeschlagen: " + relative)
        config = game / "re2_fw_config.txt"
        if config.is_file():
            shutil.copy2(config, backup / config.name)
            state["configs"].append(config.name)
            write(app / "install-state.json", state)
            text = config.read_bytes().decode("utf-8-sig")
            text = text.replace("REFrameworkConfig_MenuOpen=true", "REFrameworkConfig_MenuOpen=false")
            text = text.replace("REFrameworkConfig_RememberMenuState=false", "REFrameworkConfig_RememberMenuState=true")
            config.write_bytes(text.encode("utf-8"))
        state["active"] = True
        write(app / "install-state.json", state)
        write(ROOT / "installation.json", {"game": str(game)})
        print("Installiert: " + str(game))
        print("Freigegebenes Save-Datum: " + allow_save_date)
        print("Originalmods und Speichersicherung: " + str(backup))
        print("Host-starten.cmd oder Gast-starten.cmd oeffnen. Speichern ist im Test gesperrt.")
    except BaseException:
        restore(game, state)
        raise


def restore(game, state):
    require_closed()
    backup = inside(game, Path(state["backup"]))
    if not backup.is_dir() or not backup.name.startswith("re2-coop-backup-"):
        raise ValueError("Installationssicherung fehlt.")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    preserved = inside(backup, backup / ("test-files-" + stamp))
    preserved.mkdir()
    for entry in reversed(state["moved"]):
        name = entry["name"]
        if name not in FOLDERS:
            raise ValueError("Ungueltige Installationsdaten.")
        target = inside(game, game / "reframework" / name)
        original = inside(backup, backup / ("original-" + name))
        # A failed move must not displace an original directory.
        if entry["existed"] and not original.exists():
            continue
        if target.exists():
            target.rename(preserved / name)
        if entry["existed"]:
            original.rename(target)
    for name in state["configs"]:
        if name != "re2_fw_config.txt":
            raise ValueError("Ungueltige Konfigurationssicherung.")
        target = inside(game, game / name)
        if target.exists():
            shutil.copy2(target, preserved / name)
        shutil.copy2(backup / name, target)
    state["active"] = False
    write(game / APP / "install-state.json", state)
    print("Originalmods und REFramework-Konfiguration wiederhergestellt. Testdateien sind gesichert.")
    changes = [e["relative"] for e in state["saves"] if not Path(e["path"]).is_file() or digest(Path(e["path"])) != e["sha256"]]
    print("Veraenderte vorhandene Speicherdateien: " + str(len(changes)))
    if changes:
        print("Sicherung nur erhalten; keine Speicherdatei automatisch zurueckkopiert.")


def installation_state(game):
    state = read(game / APP / "install-state.json")
    if state.get("active") is not True or Path(state["game"]).resolve() != game.resolve():
        raise ValueError("Keine aktive Testinstallation fuer diesen Spielordner.")
    return state


def installed(game):
    state = installation_state(game)
    manifest = read(game / APP / "bundle-manifest.json")
    if manifest != verify_bundle():
        raise ValueError('Startpaket passt nicht zur installierten Fassung.')
    for relative in manifest["install_files"]:
        if digest(inside(game, game / relative)) != manifest["files"][relative]:
            raise ValueError("Installierte Datei veraendert; RE2 beenden und Vortex-Neubereitstellung pruefen: " + relative)
    return state


def game_process(game):
    rows = processes()
    if len(rows) != 1 or not rows[0].get("exe") or Path(rows[0]["exe"]).resolve() != (game / "re2.exe").resolve():
        raise ValueError("Eine eindeutig zu dieser Installation gehoerende RE2-Instanz wird benoetigt.")
    return rows[0]


def fresh(path, stamp="at"):
    value = read(path)
    if not 0 <= time.time() - value[stamp] <= 3:
        raise ValueError("Status noch nicht frisch: " + path.name)
    return value


def start(game, role):
    installation = installed(game)
    allow_date = save_date(installation.get('allow_save_date', DATE))
    require_closed()  # Existing games cannot acquire the inherited locks retroactively.
    from pose_bridge import lock_data_directory
    from steam_pose_bridge import SteamPipe, run_bridge
    from save_catalog import SaveCatalog
    from save_file_guard import SaveFileLocks
    from save_protection import read_save_protection
    from readonly_save_control import read_active_guard
    data = game / "reframework/data"
    with lock_data_directory(data):
        current = save_inventory()
        expected = {entry['path']: entry for entry in installation['saves']}
        if not current or {entry['path'] for entry in current} != set(expected):
            raise ValueError('Speicherinventar seit Installation geaendert; erst Rueckbau und neue Sicherung.')
        for entry in current:
            saved = expected[entry['path']]
            backup = inside(Path(installation['backup']), Path(installation['backup']) / 'saves' / saved['relative'])
            if digest(backup) != saved['sha256'] or (Path(entry['path']).suffix == '.bin' and entry['sha256'] != saved['sha256']):
                raise ValueError('Original-Save oder Sicherung geaendert; keine Testfreigabe.')
        with SaveFileLocks([entry['path'] for entry in current]) as locks:
            if save_inventory() != current:
                raise ValueError('Dateien waehrend Schutzaufbau geaendert; RE2 bleibt geschlossen.')
            run_id = secrets.token_hex(16)
            token = inside(game, game / 'reframework/autorun/re2_coop/protected_launch_token.lua')
            if token.exists() and not re.fullmatch(r"return '[0-9a-f]{32}'\r?\n", token.read_text(encoding='ascii')):
                raise ValueError('Unerwartete generierte Laufkennung; nichts ueberschrieben.')
            token.write_text("return '" + run_id + "'\n", encoding='ascii')
            # Preserve a previous command rather than let a new Lua VM replay it.
            policy = inside(game, data / 're2_coop_save_policy.json')
            if policy.exists():
                policy.rename(inside(game, data / ('re2_coop_previous_policy_' + run_id + '.json')))
            environment = {**os.environ, 'SteamAppId': '883710', 'SteamGameId': '883710',
                           'RE2_COOP_SAVE_GUARD_RUN_ID': run_id}
            child = locks.spawn(game / 're2.exe', cwd=game, env=environment)
            stop, ready = threading.Event(), threading.Event()
            errors = []
            session = {'id': run_id, 'role': role, 'game_pid': child.pid, 'active': True, 'at': int(time.time())}
            receipt = {'schema': 1, 'source': 'inherited_save_locks', 'active': True,
                       'at': int(time.time()), 'app_id': 883710, 'build_id': 11636119,
                       'game_pid': child.pid, 'run_id': run_id, 'locked_files': locks.locked_count}
            pipe, worker = None, None

            def monitor():
                try:
                    while not stop.is_set():
                        if child.poll() is not None:
                            stop.set()
                            return
                        if ready.is_set():
                            try:
                                native = fresh(data / 're2_coop_native_save_guard.json')
                                if (native.get('game_pid') == child.pid and native.get('run_id') == run_id
                                        and native.get('active') is not True):
                                    errors.append('Nativer Speicherschutz ausgefallen; eigene Testinstanz beendet.')
                                    child.terminate()  # Original handle belongs to the process we created.
                                    stop.set()
                                    return
                            except (OSError, ValueError, KeyError):
                                pass  # A stale report blocks loading, without treating lost focus as corruption.
                        receipt['at'] = int(time.time())
                        write(data / 're2_coop_protected_launch.json', receipt)
                        try:
                            command = fresh(data / 're2_coop_test_stop.json')
                            if command.get('id') == run_id:
                                stop.set()
                                return
                        except (OSError, ValueError, KeyError):
                            pass
                        stop.wait(0.5)
                except Exception as error:
                    errors.append(str(error))
                    stop.set()

            try:
                process = game_process(game)
                if process['pid'] != child.pid:
                    raise ValueError('Direkter Spielprozess wurde ersetzt; kein ungeschuetztes Steam-Weiterreichen.')
                session['started'] = process['started']
                write(data / 're2_coop_test_session.json', session)
                worker = threading.Thread(target=monitor, daemon=True)
                worker.start()
                pipe = SteamPipe(child.pid)
                print('RE2 Coop Test: ' + role.upper() + '. Warte auf beide Schutzschichten ...', flush=True)
                for _ in range(90):
                    if stop.is_set():
                        raise ValueError(errors[0] if errors else 'Eigene Testinstanz beendet.')
                    try:
                        binding = read_save_protection(data)
                        guard = read_active_guard(data, protected=True)
                        if (binding == {'game_pid': child.pid, 'run_id': run_id}
                                and guard['protection_active'] is True and pipe.lobby_status() != 'unavailable'):
                            ready.set()
                            break
                    except (OSError, ValueError, KeyError):
                        pass
                    stop.wait(1)
                else:
                    raise ValueError('Steam-Plugin oder beide Schutzschichten nicht bereit; Test abgebrochen.')
                print('Im Hauptmenue: Multiplayer. F9 oeffnet/schliesst die Lobby.', flush=True)
                print('Host: private Lobby erstellen, Mitspieler ueber Steam einladen.', flush=True)
                print('Gast: Steam-Einladung oeffnen, dann in Multiplayer annehmen.', flush=True)
                print('Laden: Spielstand-laden.cmd; nur freigegebene alte Saves.', flush=True)
                print('Verbindungs-/Posentest; keine gemeinsam spielbare Kampagne.', flush=True)
                run_bridge(data, pipe, b'H' if role == 'host' else b'G', 'leon', 'claire', stop=stop,
                           lobby_enabled=True, save_catalog=SaveCatalog(data / 're2_coop_save_catalog.json', allow_date=allow_date))
                if errors:
                    raise ValueError(errors[0])
            except KeyboardInterrupt:
                pass
            finally:
                stop.set()
                if worker is not None:
                    worker.join(timeout=3)
                if not ready.is_set() and child.poll() is None:
                    child.terminate()
                    child.wait(timeout=20)
                if pipe is not None and child.poll() is None:
                    try:
                        revision = pipe.membership_revision()
                        if revision is not None:
                            pipe.leave_lobby(revision)
                    except (OSError, ValueError):
                        pass
                receipt.update(active=False, at=int(time.time()))
                write(data / 're2_coop_protected_launch.json', receipt)
                session.update(active=False, at=int(time.time()))
                write(data / 're2_coop_test_session.json', session)
                print('Bridge beendet. Dateisperren bleiben bis zum Schliessen dieser RE2-Instanz bestehen.', flush=True)


def load(game, slot):
    installation = installed(game)
    allow_date = save_date(installation.get('allow_save_date', DATE))
    game_process(game)
    from readonly_save_control import arm, wait_for_result, read_active_guard
    from save_catalog import SaveCatalog
    data = game / "reframework/data"
    for _ in range(90):
        try:
            guard = read_active_guard(data, protected=True)
            if guard.get("denied_loads") != 0 or guard.get("allowed_load_calls") != 0:
                raise ValueError("Zum erneuten Laden zuerst RE2 und die Bridge neu starten.")
            ready = (guard.get("in_title") is True and guard.get("busy") is False
                     and guard.get("load_menu_busy") is False and
                     any(guard.get(k) is True for k in ("title_open", "main_menu_busy", "story_menu_busy")))
            if ready:
                break
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(1)
    else:
        raise ValueError("RE2-Hauptmenue noch nicht ladebereit. Ladefenster schliessen und erneut versuchen.")
    reference = SaveCatalog(data / "re2_coop_save_catalog.json", allow_date=allow_date).select(slot)
    # A local deployment can additionally pin its previously approved native timestamp.
    expected = installation.get("expected_slot4_timestamp")
    if expected and (slot != "scenario:4" or reference["timestamp"] != expected):
        raise ValueError("Slot 4 stimmt nicht mit dem freigegebenen alten Spielstand ueberein.")
    # The native loader closes stock menus; first release our own input capture.
    from lobby_sync import write_json
    write_json(data / "re2_coop_lobby_view.json", {"schema": 1, "id": secrets.token_hex(16), "at": int(time.time()), "visible": False})
    request = arm(data, slot, allow_date, load=True, require_receipt=True)
    write(data / "re2_coop_test_load.json", {"request_id": request, "slot": slot, "date": allow_date})
    print("Lade ausschliesslich " + slot + " vom " + allow_date + ". Anfrage: " + request, flush=True)
    wait_for_result(data, request, load=True, timeout=90)
    print("Kampagne geladen. Speichern bleibt gesperrt.")


def status(game):
    installed(game)
    process = game_process(game)
    from steam_pose_bridge import SteamPipe
    data = game / "reframework/data"
    pipe = SteamPipe(process["pid"])
    report = {"source_commit": read(game / APP / "bundle-manifest.json")["source_commit"],
              "game_pid": process["pid"], "steam_lobby": pipe.lobby_status()}
    from save_protection import read_save_protection
    try:
        binding = read_save_protection(data)
        report['save_protection'] = {'active': binding['game_pid'] == process['pid'], 'game_pid': binding['game_pid']}
    except (OSError, ValueError):
        report['save_protection'] = {'active': False}
    for name, stamp in (("save_guard", "at"), ("lobby", "written_at"), ("observer", "observed_at")):
        try:
            value = fresh(data / ("re2_coop_" + name + ".json"), stamp)
            keys = ("active", "hooks", "protection_active", "protection_error", "allowed_load_calls", "denied_loads", "writes", "load_phase") if name == "save_guard" else (
                ("role", "connected", "steam_lobby", "error", "game_pid") if name == "lobby" else ("available", "tdb", "sequence"))
            report[name] = {"fresh": True, **{k: value.get(k) for k in keys}}
        except (OSError, ValueError, KeyError):
            report[name] = {"fresh": False}
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall", "host", "guest", "status", "load", "stop"))
    parser.add_argument("--game")
    parser.add_argument("--slot", default="scenario:4", help="Native scenario save from the installed date filter")
    parser.add_argument("--allow-save-date", type=save_date, metavar="YYYY-MM-DD",
                        help="Installation-only local save date; default 2026-11-11")
    parser.add_argument("--expected-slot4-timestamp", help="Optional exact local installation binding")
    args = parser.parse_args()
    if args.allow_save_date is not None and args.action != 'install':
        parser.error('--allow-save-date ist nur bei install erlaubt; zum Aendern zuerst zurueckbauen.')
    if args.action in ("install", "host", "guest", "load") and (ROOT / "TESTING_BLOCKED.txt").is_file():
        raise ValueError("Testpaket gesperrt: unvollstaendiger Speicherschutz am Kontrollpunkt. Erst gepruefte neue Fassung verwenden.")
    game = find_game(args.game)
    if args.action == "install":
        install(game, args.expected_slot4_timestamp, allow_save_date=args.allow_save_date or DATE)
    elif args.action == "uninstall":
        state = installation_state(game)
        restore(game, state)
    elif args.action in ("host", "guest"):
        start(game, args.action)
    elif args.action == "load":
        load(game, args.slot)
    elif args.action == "status":
        status(game)
    elif args.action == "stop":
        installed(game)
        data = game / "reframework/data"
        session = read(data / "re2_coop_test_session.json")
        if session.get("active") is not True:
            raise ValueError("Keine aktive Test-Bridge.")
        write(data / "re2_coop_test_stop.json", {"id": session["id"], "at": int(time.time())})
        print("Test-Bridge wird beendet und verlaesst ihre Steam-Lobby. Danach RE2 normal schliessen.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TimeoutError, subprocess.SubprocessError) as exc:
        print("Test nicht bereit: " + str(exc), file=sys.stderr)
        sys.exit(1)
