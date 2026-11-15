local now, clock, frame = 100, 0, nil
local clicked, input_slot, command, view
local native_choice
local f9_down = false
local capture_wanted
local texts, windows, styles, font_depth = {}, 0, 0, 0
local disabled = {}
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
reframework = {get_game_name = function() return "re2" end, is_key_down = function() return f9_down end}
package.loaded['re2_coop.lobby_input'] = {new = function()
    return {frame = function(self, wanted) self.wanted = wanted; capture_wanted = wanted end,
            can_draw = function(self) return self.wanted end}
end}
re = {on_frame = function(fn) frame = fn end}
log = {info = function() end}
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
    get_display_size = function() return {x = 1920, y = 1080} end,
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
    text_colored = function(value) texts[value] = true end,
    text = function(value) assert(type(value) == "string"); texts[value] = true end,
    begin_disabled = function(value) disabled[#disabled + 1] = not not value end,
    end_disabled = function() table.remove(disabled) end,
    input_text = function(_, value)
        return input_slot ~= nil and not is_disabled(), not is_disabled() and input_slot or value
    end,
    combo = function(label, value)
        if label == "##coop-save" and native_choice and not is_disabled() then return true, native_choice end
        return false, value
    end,
    button = function(label) return clicked == label end,
}
dofile("reframework/autorun/re2_coop_lobby.lua")
local function draw(button)
    clicked, command, texts = button, nil, {}
    clock = clock + 0.1
    frame()
    assert(windows == 0 and styles == 0 and font_depth == 0 and #disabled == 0, "unbalanced UI stack")
end
current.written_at = 90
draw("Spieler über Steam einladen")
assert(command == nil and next(texts) == nil and not capture_wanted,
    "a previous run's expired file must not open a modal at startup")
now = 101; current.written_at = now
draw("Bereit")
assert(command == nil, "cannot become ready without a peer")
assert(texts["Warten auf einen Spieler"])
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
draw("Bereit")
assert(command.action == "ready" and command.value == true and command.revision == 4)
now = 115; current = {schema = 1, role = "forged", written_at = now}
draw("Bereit")
assert(command == nil, "malformed status must disable the menu")
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
now = 128
fs.glob = function() return {} end
json.load_file = function() error("missing optional files must not be loaded") end
draw("Bereit")
assert(command == nil)
print("Lobby UI: choices, invite, stale state, guest authority, readiness and F9 edge passed")
