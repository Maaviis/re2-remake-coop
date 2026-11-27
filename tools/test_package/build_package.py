"""Assemble only project-owned files and a checksum-verified portable Python."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
import argparse

REPO = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=REPO.parent / 'RE2-Coop-Test-Protected')
parser.add_argument('--python-archive', type=Path, default=REPO / 'staging/package-cache/python-3.13.17-embed-amd64.zip')
parser.add_argument('--sdk-root', type=Path, default=REPO / 'staging/sdk')
args = parser.parse_args()
OUT = args.output.resolve()
if subprocess.run(['git', 'diff', 'HEAD', '--quiet'], cwd=REPO).returncode:
    raise SystemExit('Commit tracked source changes before building an identified package')
if OUT.exists():
    raise SystemExit("Output already exists; refuse to overwrite")
OUT.mkdir()
tracked = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True).splitlines()
selected = [p for p in tracked if p.endswith(".md") or p == "LICENSE" or
            p.startswith(("bridge/", "tools/test_package/")) and p.endswith(".py") or
            p.startswith("reframework/") and p.endswith(".lua") or
            p in ("network/steam_lobby_probe/lobby.ps1", "bridge/scripts/protect_re2_test_saves.ps1", "bridge/protocol/v1-examples.json")]
for relative in selected:
    target = OUT / relative.removeprefix("bridge/")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / relative, target)
shutil.copy2(Path(__file__).with_name("test_mod.py"), OUT / "test_mod.py")
shutil.copy2(Path(__file__).with_name("ZUERST_LESEN.md"), OUT / "ZUERST_LESEN.md")
plugin = OUT / "reframework/plugins/re2_coop_steam_lobby_probe.dll"
plugin.parent.mkdir(parents=True)
shutil.copy2(REPO / "staging/native-build/Release" / plugin.name, plugin)
guard_plugin = plugin.with_name('re2_coop_steam_save_guard.dll')
shutil.copy2(REPO / 'staging/save-guard-build/Release' / guard_plugin.name, guard_plugin)
# Install only observational tools, guarded loader, menu, marker and their modules.
# Diagnostics able to alter HP or play experimental animation stay outside autorun.
autorun = OUT / "reframework/autorun"
for name in ("re2_coop_motion_probe.lua", "re2_coop_motion_playback.lua", "re2_coop_remote_motion.lua"):
    (autorun / name).unlink()
for name in ("re2_coop_readonly_save_probe.lua", "re2_coop_load_state_observer.lua",
             "re2_coop_enemy_state_observer.lua", "re2_coop_guest_enemy_probe.lua"):
    shutil.copy2(OUT / "reframework/diagnostics" / name, autorun / name)
archive = args.python_archive
if hashlib.sha256(archive.read_bytes()).hexdigest() != "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38":
    raise SystemExit("Python archive checksum mismatch")
with zipfile.ZipFile(archive) as bundle:
    bundle.extractall(OUT / "runtime")
# Keep the embedded interpreter isolated from user site-packages; expose our source root.
(OUT / "runtime/python313._pth").write_text("python313.zip\n.\n..\n", encoding="ascii")
commands = {"Installieren": "install", "Entfernen": "uninstall", "Host-starten": "host",
            "Gast-starten": "guest", "Teststatus": "status", "Spielstand-laden": "load", "Test-beenden": "stop"}
for name, action in commands.items():
    text = '@echo off\r\nchcp 65001 >nul\r\n"%~dp0runtime\\python.exe" -B "%~dp0test_mod.py" ' + action + ' %*\r\nset "TEST_EXIT=%ERRORLEVEL%"\r\necho.\r\npause\r\nexit /b %TEST_EXIT%\r\n'
    (OUT / (name + ".cmd")).write_bytes(text.encode("utf-8"))
vendor = OUT / "third-party"
vendor.mkdir()
sdk = args.sdk_root
shutil.copy2(sdk / "reframework/LICENSE", vendor / "REFramework-LICENSE.txt")
shutil.copy2(sdk / "source-sdk-2013/LICENSE", vendor / "Valve-Source-SDK-LICENSE.txt")
files = {p.relative_to(OUT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(OUT.rglob("*")) if p.is_file()}
install_files = [p for p in files if p.startswith("reframework/autorun/") or p in (
    "reframework/plugins/re2_coop_steam_lobby_probe.dll", "reframework/plugins/re2_coop_steam_save_guard.dll")]
manifest = {"schema": 1, "save_protection_schema": 1, "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
            "tested_game_build": "11636119", "tested_reframework": "d1461375", "files": files, "install_files": install_files}
(OUT / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps({"output": str(OUT), "files": len(files), "install_files": len(install_files)}, indent=2))
