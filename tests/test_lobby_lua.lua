local now, clock, frame = 100, 0, nil
local clicked, input_slot, command, view
local native_choice
local open_from_main_menu
local resume_count, release_held = 0, false
local f9_down, escape_down = false, false
local nav_keys = {}
local popup_owner, widget_id, text_editing
local draw_allowed, framework_menu = true, false
local mouse_point, draw_layers
local display = {x = 1920, y = 1080}
local backdrop
local capture_wanted
local texts, button_labels, windows, styles, font_depth = {}, {}, 0, 0, 0
local disabled = {}
local hovered, last_item, tooltip, tooltip_open
local log_lines = {}
local current = {schema = 1, role = "H", connected = false, written_at = now,
    lobby = {session_id = "host-session", sequence = 1,
        data = {host_id = "leon", guest_id = "claire", save_slot = "slot-1", settings = {},
            revision = 3, connected = false, ready = {leon = false, claire = false}}}}
local function is_disabled()
    for _, value in ipairs(disabled) do if value then return true end end
    return false
end
os.time = function() return now end
os.clock = function() return clock end
reframework = {get_game_name = function() return "re2" end,
    is_key_down = function(_, key) return key == 0x78 and f9_down or key == 0x1B and escape_down or nav_keys[key] end,
    is_drawing_ui = function() return framework_menu end}
package.loaded['re2_coop.lobby_input'] = {new = function()
    return {installed = true, frame = function(self, wanted)
                self.wanted, self.captured, capture_wanted = wanted, wanted or release_held, wanted
            end,
            can_draw = function(self) return self.wanted and draw_allowed end}
end}
package.loaded['re2_coop.main_menu'] = {install = function(open)
    open_from_main_menu = open
    return function() resume_count = resume_count + 1 end
end}
re = {on_frame = function(fn) frame = fn end}
log = {info = function(value) log_lines[#log_lines + 1] = value end}
fs = {glob = function() return {"present"} end}
json = {
    load_file = function(path) return path == "re2_coop_lobby.json" and current or view end,
    dump_file = function(path, value)
        assert(path == "re2_coop_lobby_command.json")
        command = value
        return true
    end,
}
imgui = {
    load_font = function(_, size) return size end,
    get_display_size = function() return display end,
    get_background_draw_list = function()
        return {add_rect_filled = function(_, origin, extent, color)
            assert(origin[1] == 0 and origin[2] == 0 and color >> 24 == 255)
            backdrop = extent
        end}
    end,
    get_mouse = function() return mouse_point end,
    get_foreground_draw_list = function()
        assert(windows == 0, "cursor belongs above the menu and its popups")
        return {
            add_triangle_filled = function(_, tip) assert(tip[1] == mouse_point.x and tip[2] == mouse_point.y)
                draw_layers = draw_layers + 1 end,
            add_triangle = function() draw_layers = draw_layers + 1 end,
        }
    end,
    set_next_window_pos = function() end, set_next_window_size = function() end,
    push_style_color = function(_, color)
        assert(math.type(color) == "integer" and color >= -0x80000000 and color <= 0x7fffffff,
               "native style binding accepts a signed int32")
        styles = styles + 1
    end,
    pop_style_color = function(count) styles = styles - count end,
    begin_window = function() windows = windows + 1 end,
    end_window = function() windows = windows - 1 end,
    push_font = function(font) assert(font); font_depth = font_depth + 1 end,
    pop_font = function() font_depth = font_depth - 1 end,
    set_cursor_pos = function() end, set_next_item_width = function() end,
    is_item_hovered = function(flags) return flags == 1 << 10 and hovered ~= nil and hovered == last_item end,
    begin_tooltip = function() tooltip_open = true end, end_tooltip = function() tooltip_open = false end,
    text_colored = function(value) texts[value] = true end,
    text = function(value)
        assert(type(value) == "string")
        if tooltip_open then tooltip = value else texts[value] = true end
    end,
    begin_disabled = function(value) disabled[#disabled + 1] = not not value end,
    end_disabled = function() table.remove(disabled) end,
    input_text = function(_, value)
        return input_slot ~= nil and not is_disabled(), not is_disabled() and input_slot or value
    end,
    combo = function(label, value)
        if label == "##coop-save" and native_choice and not is_disabled() then return true, native_choice end
        return false, value
    end,
    push_id = function(id) assert(not widget_id); widget_id = id end,
    pop_id = function() assert(widget_id); widget_id = nil end,
    is_popup_open = function(id) assert(id == "##ComboPopup"); return widget_id == popup_owner end,
    is_item_active = function() return text_editing end,
    button = function(label) last_item = label; button_labels[label] = true; return clicked == label end,
}
dofile("reframework/autorun/re2_coop_lobby.lua")
local function draw(button)
    clicked, command, texts, button_labels = button, nil, {}, {}
    draw_layers, backdrop, tooltip, last_item = 0, nil, nil, nil
    clock = clock + 0.1
    frame()
    assert(windows == 0 and styles == 0 and font_depth == 0 and #disabled == 0, "unbalanced UI stack")
end
current.written_at = 90
draw("Spieler über Steam einladen")
assert(command == nil and next(texts) == nil and not capture_wanted,
    "a previous run's expired file must not open a modal at startup")
now = 101; current.written_at = now
view = {id = "initial-show", visible = true}
draw("Bereit")
assert(command == nil, "cannot become ready without a peer")
assert(texts["Warten auf einen Spieler"])
assert(button_labels["Spiel starten"] and command == nil,
    "the host must always see a disabled game-start button before a peer joins")
assert(log_lines[#log_lines]:find("start_button_visible=true", 1, true)
    and log_lines[#log_lines]:find("start_button=Spiel starten", 1, true)
    and log_lines[#log_lines]:find("start_enabled=false", 1, true),
    "the menu log must expose the visible but disabled host start button")
draw("Spieler über Steam einladen")
assert(command.action == "invite" and command.value == true)
assert(command.session_id == "host-session" and command.revision == 3)
now = 103; current.written_at = now
input_slot = "slot-2"
draw("Auswahl übernehmen")
assert(command.action == "configure" and command.value.save_slot == "slot-2")
assert(current.lobby.data.save_slot == "slot-1", "UI must not invent host acceptance")
input_slot = nil
now = 110
draw("Spieler über Steam einladen")
assert(command == nil and texts["Verbindung unterbrochen"], "stale bridge must disable commands")
now = 111; current.written_at = now; current.role = "G"
current.connected = true; current.lobby.data.connected = true
current.lobby.data.revision = 4
draw("Spieler über Steam einladen")
assert(command == nil, "guest cannot invite")
draw("Auswahl übernehmen")
assert(command == nil, "guest cannot configure")
hovered = "Auswahl übernehmen"
draw()
assert(tooltip == "Der Host wählt den Spielstand.")
hovered = nil
draw("Bereit")
assert(command.action == "ready" and command.value == true and command.revision == 4)
assert(button_labels["Warten auf Host"], "the guest must see that the host controls campaign start")
now = 115; current = {schema = 1, role = "forged", written_at = now}
draw("Bereit")
assert(command == nil and capture_wanted and button_labels["Zurück"],
    "losing the bridge report must keep an open lobby modal and allow Back")
assert(texts["Kein aktueller Bridge-Status. Verbindung wird geprüft."])
display = {x = 0, y = 0}
draw("Zurück")
assert(not backdrop and not button_labels["Zurück"], "do not submit widgets on a minimized surface")
display = {x = 1280, y = 720}
now = 116
current = {schema = 1, role = "H", connected = true, written_at = now,
    lobby = {session_id = "native-session", sequence = 1,
        data = {host_id = "leon", guest_id = "claire", save_slot = "scenario:4", settings = {},
            revision = 1, connected = true, ready = {leon = false, claire = false},
            save_ref = {available = true, scenario = 1, label = "Native test save", difficulty_label = "Test difficulty"}}},
    catalog = {available = true, entries = {{key = "scenario:4", saved_at = "2026-11-11 23:28:21",
        reference = {label = "Native test save"}}}}}
native_choice = 2
draw("Auswahl übernehmen")
assert(backdrop and backdrop[1] == 1280 and backdrop[2] == 720,
    "on restoration the modal must cover the native menu at the new resolution")
assert(command.action == "configure" and command.value.save_slot == "scenario:4")
assert(next(command.value.settings) == nil, "native save configuration must not invent campaign or difficulty")
assert(texts["Claire (1. Durchlauf)"] and texts["Test difficulty"])
now = 119; current.written_at = now; current.lobby.data.revision = 2
current.lobby.data.save_ref = {available = false}
current.catalog = {available = false, entries = {}}
draw("Bereit")
assert(command == nil, "unavailable native save must prevent readiness")
now = 120; current.written_at = now
f9_down = true
draw("Spieler über Steam einladen")
assert(command == nil, "F9 must hide the menu")
draw("Spieler über Steam einladen")
assert(command == nil, "holding F9 must not reopen it every frame")
f9_down = false; draw(nil)
f9_down = true; draw("Spieler über Steam einladen")
assert(command and command.action == "invite", "a new F9 press must reopen the menu")
f9_down = false
now = 124; current.written_at = now; current.role = "G"
current.lobby.data.save_ref = {available = true, scenario = 1, label = "Native test save", difficulty_label = "Test difficulty"}
current.local_save_matches = false
draw("Bereit")
assert(command == nil and texts["Passender lokaler Spielstand erforderlich."], "guest needs a matching local reference")
now = 125; current.written_at = now; current.local_save_matches = true
draw("Bereit")
assert(command.action == "ready" and command.value == true)
now = 128; current.written_at = now; current.role = "H"; current.steam_lobby = "idle"
current.connected = false; current.lobby.data.connected = false
draw("Spieler über Steam einladen")
assert(command == nil and texts["Keine Steam-Lobby geöffnet"])
draw("Private Steam-Lobby erstellen")
assert(command and command.action == "create" and command.value == true)
assert(command.session_id == "native-session" and command.revision == 2)
now = 130; current.written_at = now; current.steam_lobby = "creating"
draw("Private Steam-Lobby erstellen")
assert(command == nil and texts["Steam erstellt die Lobby …"])
now = 131; current.written_at = now; current.steam_lobby = "unavailable"
draw("Private Steam-Lobby erstellen")
assert(command == nil and texts["Steam-Plugin nicht erreichbar"])
now = 132; current.written_at = now; current.steam_lobby = "owned"
draw("Spieler über Steam einladen")
assert(command and command.action == "invite" and texts["Warten auf einen Spieler"])
now = 134; current.written_at = now; current.connected = true; current.lobby.data.connected = true
current.campaign_start_supported = true
current.campaign_start_ready = false
draw("Spiel starten")
assert(command == nil, "starting requires the guest's protected campaign consent")
assert(button_labels["Spiel starten"], "the start button remains visible while campaign readiness is pending")
current.lobby.data.ready = {leon = true, claire = true}
draw("Spiel starten")
assert(command == nil and texts["Gast: Bereitschaft zurücknehmen und für Kampagnenstart bestätigen."],
    "ordinary ready on both peers is distinct from consent to start the campaign")
current.campaign_start_ready = true
current.lobby.data.load_check = {phase = "prepared"}
draw("Spiel starten")
assert(command == nil and texts["Ladeprüfung aktiv. Erst abschließen oder abbrechen."],
    "an active ordinary load check also owns the backend start gate")
current.lobby.data.load_check = {phase = "failed", reason = "guest_file_mismatch", campaign_start = true}
draw()
assert(texts["Gast und Host haben verschiedene Slot-Dateien."], "surface the actual preflight failure")
current.lobby.data.load_check = nil
current.error = "Steam overlay is unavailable"
current.source_commit = string.rep("a", 40)
draw()
assert(texts[current.error] and log_lines[#log_lines]:find("build=" .. current.source_commit, 1, true))
current.error = [[File not found: X:\Steam\userdata\12345678\save.bin]]
draw()
assert(not texts[current.error] and texts["Datei- oder Bridge-Zugriff fehlgeschlagen. Installation prüfen."],
    "old bridge errors must not expose userdata paths on screen")
current.error = nil
draw("Spiel starten")
assert(command and command.action == "start-campaign" and command.value == true)
assert(log_lines[#log_lines]:find("start_enabled=true", 1, true),
    "the menu log must expose when the protected campaign start is enabled")
now = 136
current = {schema = 1, role = "G", connected = false, written_at = now, steam_lobby = "idle"}
draw("Steam-Einladung annehmen")
assert(command == nil and texts["Warten auf eine Steam-Einladung"])
now = 137; current.written_at = now; current.steam_lobby = "invite-pending"
draw("Steam-Einladung annehmen")
assert(command == nil, "an old plugin without an invitation revision must keep the button disabled")
now = 138; current.written_at = now
current.steam_invite = {session_id = "local-guest-run", revision = 7}
draw(nil)
assert(command == nil and texts["Steam-Einladung verfügbar"], "an invite requires a click")
draw("Steam-Einladung annehmen")
assert(command and command.value == true and command.action == "join-invite")
assert(command.session_id == "local-guest-run" and command.revision == 7)
draw("Steam-Einladung annehmen")
assert(command == nil, "the pending action must not be sent again")
now = 141; current.written_at = now; current.steam_lobby = "joining"
draw("Steam-Einladung annehmen")
assert(command == nil and texts["Steam prüft den Beitritt …"])
now = 142; current.written_at = now; current.steam_lobby = "joined"
draw("Bereit")
assert(command == nil and texts["Warten auf den Host"])
draw("Steam-Lobby verlassen")
assert(command == nil, "an older plugin cannot provide a scoped departure")
current.steam_membership = {session_id = "local-guest-run", revision = 9}
now = 143; current.written_at = now
draw("Steam-Lobby verlassen")
assert(command and command.action == "leave" and command.value == true)
assert(command.session_id == "local-guest-run" and command.revision == 9)
now = 146; current.written_at = now; current.steam_lobby = "leaving"
draw("Steam-Lobby verlassen")
assert(command == nil and texts["Steam-Lobby wird verlassen …"])
now = 148
current = {schema=1, role="H", connected=false, written_at=now, steam_lobby="idle",
    campaign_setup={session_id="runtime-setup", revision=1}}
local title = false
sdk = {get_managed_singleton=function()
    return {call=function(_, name) return name == 'get_IsInTitle' and title or false end}
end}
draw("Vorhandenen Spielstand vorbereiten")
assert(command == nil, "setup cannot lock saves outside the title menu")
title = true
draw("Vorhandenen Spielstand vorbereiten")
assert(command and command.action == "prepare-campaign" and command.value == true)
assert(command.session_id == "runtime-setup" and command.revision == 1)
now = 150; current.written_at = now; current.campaign_setup_status = "closing"
draw("Vorhandenen Spielstand vorbereiten")
assert(command == nil and texts["RE2 schließen. Steam startet das Spiel neu."])
draw("Private Steam-Lobby erstellen")
assert(command == nil, "lobby actions must wait until the supervised restart")
now = 154; current.written_at = now; current.campaign_setup_status = "failed"
current.campaign_setup_error = "Steam Cloud wurde waehrend der Vorbereitung aktiviert."
draw()
assert(texts[current.campaign_setup_error], "show the restart helper's failure in the lobby")
current.campaign_setup_error = {}
draw()
assert(texts["Vorbereitung fehlgeschlagen. Erneut versuchen."], "keep a fallback when no helper detail is available")
now = 155
fs.glob = function() return {} end
json.load_file = function() error("missing optional files must not be loaded") end
draw("Bereit")
assert(command == nil)
open_from_main_menu()
mouse_point = {x = 400, y = 550}
draw(nil)
assert(texts["STEAM-BRIDGE WARTET"] and capture_wanted, "main menu must open even before the Steam bridge")
assert(draw_layers == 2, "draw the pointer above the popup at the ImGui click hotspot")
framework_menu = true
draw(nil)
assert(draw_layers == 0, "REFramework owns the pointer while its menu is open")
framework_menu = false
mouse_point = {x = -3.4e38, y = -3.4e38}
draw(nil)
assert(draw_layers == 0, "an unavailable pointer must not be drawn")
draw("Zurück")
release_held = true
draw(nil)
assert(resume_count == 0, "held input must be released before returning to the native menu")
release_held = false
draw(nil)
assert(next(texts) == nil and not capture_wanted, "Back must release the lobby view")
draw(nil)
assert(resume_count == 1, "Back must resume native input exactly once")
open_from_main_menu()
draw_allowed = false
draw(nil)
escape_down = true
draw(nil)
assert(not capture_wanted and resume_count == 1, "Escape must close even if UI input is unavailable")
draw(nil)
assert(resume_count == 1, "held Escape must never fall through to the game")
escape_down = false
draw(nil)
assert(resume_count == 2 and not capture_wanted)
-- The pinned framework does not turn on ImGui's keyboard navigation.
now = now + 1
fs.glob = function() return {"present"} end
json.load_file = function(path) if path == "re2_coop_lobby.json" then return current end end
current = {schema = 1, role = "G", connected = false, written_at = now,
    steam_lobby = "invite-pending", steam_invite = {session_id = "keyboard-invite", revision = 1}}
draw_allowed = true
open_from_main_menu()
nav_keys[0x0D] = true
draw(nil)
assert(command == nil, "the key that opened the native menu must not accept an invitation")
nav_keys = {}; draw(nil)
nav_keys[0x28] = true; draw(nil) -- first enabled control, skipping disabled actions
nav_keys = {}; draw(nil)
nav_keys[0x0D] = true; draw(nil)
assert(command and command.action == "join-invite", "keyboard must accept a pending guest invite")
now = now + 3; current.written_at = now; draw(nil)
assert(command == nil, "holding Enter must not send another command after a pending request expires")
nav_keys = {}; draw(nil)
local ref = {available = true, scenario = 1, difficulty_label = "Standard", label = "Slot four"}
current = {schema = 1, role = "H", written_at = now + 1, connected = true, steam_lobby = "owned",
    lobby = {session_id = "keys", sequence = 1, data = {host_id = "h", guest_id = "g", revision = 1,
        connected = true, ready = {h=false, g=false}, save_ref = ref, settings = {}}},
    catalog = {available = true, entries = {{key = "scenario:4", saved_at = "2026-11-11", reference = ref}}}}
now = now + 1; native_choice = nil
draw("Zurück"); draw(nil); open_from_main_menu(); draw(nil)
local function tap(key)
    nav_keys = {}; draw(nil)
    nav_keys[key] = true; draw(nil)
    return command
end
tap(0x28); tap(0x27); tap(0x28)
assert(tap(0x0D) and command.action == "configure" and command.value.save_slot == "scenario:4",
    "arrows select a real native slot and Enter applies it")
nav_keys = {}; draw(nil)
draw_allowed = false; draw(nil)
now = now + 3; current.written_at = now
nav_keys[0x0D] = true; draw_allowed = true; draw(nil)
assert(command == nil, "resuming drawing while Enter is held must not activate a row")
nav_keys = {}; draw(nil)
tap(0x28); tap(0x27); tap(0x28)
popup_owner = "##coop-save"
assert(not tap(0x0D), "an open mouse combo must own input even while another command is focused")
popup_owner = nil

-- A protected new game has no native slot. The bridge owns the selection and the guest consent.
nav_keys = {}
local picks, offered = {}, {}
imgui.combo = function(id, index, labels)
    offered[id] = labels
    if not is_disabled() then
        for i, name in ipairs(labels) do
            if name == picks[id] then return true, i end
        end
    end
    return false, index
end
now = now + 3
current = {schema=1, role="H", written_at=now, connected=true, steam_lobby="owned",
    campaign_start_supported=true, campaign_start_ready=false, new_game_supported=true,
    catalog={available=false, entries={}}, lobby={session_id="fresh-campaign", sequence=1,
        data={host_id="h", guest_id="g", revision=7, connected=true, ready={h=false,g=false},
            settings={}, save_ref={available=false}}}}
picks = {["##coop-save"]="Neues Spiel", ["##coop-new-scenario"]="Claire (1. Durchlauf)",
    ["##coop-new-difficulty"]="Hardcore"}
draw("Auswahl übernehmen")
assert(command and command.action == "select-new-game" and command.revision == 7
    and command.session_id == "fresh-campaign" and command.value.scenario == "CLAIRE_A"
    and command.value.difficulty == "HARD" and command.value.save_slot == nil,
    "host selects a new game without a save catalog")
assert(current.lobby.data.new_game == nil)
draw("Auswahl übernehmen"); assert(not command, "selection pending")
picks = {}; now = now + 3; current.written_at = now
current.lobby.data.revision = 8
current.lobby.data.new_game = {scenario="CLAIRE_A", difficulty="HARD"}
current.lobby.data.save_ref = nil
current.role, current.steam_lobby = "G", "joined"
current.local_save_matches = false
draw("Auswahl übernehmen")
assert(not command and texts["Neues Spiel"] and texts["Claire (1. Durchlauf)"] and texts.Hardcore,
    "guest sees the accepted new-game scenario and difficulty")
draw("Für Kampagnenstart bereit")
assert(command and command.action == "ready-campaign" and command.revision == 8,
    "new-game consent needs no local slot")
now = now + 3; current.written_at = now; current.new_game_supported = false
draw("Für Kampagnenstart bereit"); assert(not command, "an incompatible peer cannot consent")
assert(texts["Neues Spiel erfordert kompatible, vorbereitete Spiele auf beiden PCs."],
    "the guest sees why consent is unavailable")
current.role, current.steam_lobby = "H", "owned"
current.lobby.data.ready = {h=true, g=true}; current.campaign_start_ready = true
draw("Spiel starten"); assert(not command, "an old peer cannot start a selected new game")
current.new_game_supported = true
draw("Spiel starten"); assert(command and command.action == "start-campaign")
now = now + 3; current.written_at = now
current.lobby.data.load_check = {phase="starting", campaign_start=true}
draw("Spiel starten")
assert(not command and texts["Beide Spiele bereiten die neue Kampagne vor …"], "pending start is visible")
current.lobby.data.load_check = nil
current.catalog = {available=true, entries={{key="scenario:4", saved_at="2026-11-11", reference=ref}}}
picks = {["##coop-save"]="Slot four | 2026-11-11"}
draw("Spiel starten")
assert(not command, "a draft switching from new game to slot must not launch the old selection")
draw("Auswahl übernehmen")
assert(command and command.action == "configure" and command.value.save_slot == "scenario:4",
    "host can switch back to a file-backed selection")
now = now + 3; current.written_at = now; current.lobby.data.save_slot = "scenario:4"
draw("Spiel starten")
assert(not command, "a contradictory slot and new-game report cannot start a campaign")
now = now + 3; current.written_at = now
current.lobby.data.save_slot, current.lobby.data.save_ref = nil, {available=false}
picks = {}
draw("Spiel starten")
assert(not command and texts["STEAM-BRIDGE WARTET"], "the Lua reader enforces the same exclusive selection as the bridge")
current.lobby.data.new_game, current.lobby.data.save_slot = nil, nil
current.lobby.data.revision = 9
current.lobby.data.ready = {h=false, g=false}
current.campaign_start_ready = false
now = now + 1; current.written_at = now
picks, nav_keys = {}, {}
draw("Zurück"); draw(nil); open_from_main_menu(); draw(nil)
tap(0x28); tap(0x27) -- first campaign choice is a new game even with a populated catalog
tap(0x28); tap(0x27) -- Leon to Claire
tap(0x28); tap(0x25) -- Standard to Assisted
tap(0x28)
assert(tap(0x0D) and command.action == "select-new-game" and command.value.scenario == "CLAIRE_A"
    and command.value.difficulty == "EASY", "keyboard selects the scenario and difficulty and applies both")
now = now + 5
current = {schema=1, role="G", connected=false, written_at=now, steam_lobby="joined",
    direct_campaign_available=true, steam_membership={session_id="guest-direct", revision=14}}
title = false
draw("Neues Spiel vorbereiten")
assert(command == nil, "preparation requires the native title")
title = true
draw("Neues Spiel vorbereiten")
assert(command and command.action == "prepare-new-campaign" and command.session_id == "guest-direct"
    and command.revision == 14, "guest prepares via current Steam membership without an old save or restart")
now=now+3
current.role,current.steam_lobby,current.campaign_start_supported,current.written_at="H","owned",true,now
local requests,solo_reply=0,nil
package.loaded["re2_coop.cutscene_test_peer"]={request_start=function()
    requests=requests+1
    return true,"click-"..requests
end}
local read_status=json.load_file
json.load_file=function(path)
    if path=="re2_coop_solo_status.json" then return solo_reply end
    return read_status(path)
end
local start_solo="Solotest starten (Leon A, Normal)"
draw(start_solo); assert(requests==1)
solo_reply={request_id="click-1",active=false,retryable=false,reason="solo_membership_changed"}
now=now+1; current.written_at=now; draw(start_solo)
assert(requests==1 and texts["Die Steam-Mitgliedschaft hat sich geändert. Leere Host-Lobby prüfen."],
    "failed native solo launch must reopen the lobby and explain the rejected scope")
solo_reply.retryable=true; now=now+1; current.written_at=now; draw(start_solo)
assert(requests==2, "the recovered title must accept an explicit second click")
print("Lobby UI: choices, Steam actions, input guards, foreground pointer and keyboard return passed")
dofile("tests/check_main_menu_lua.lua")
