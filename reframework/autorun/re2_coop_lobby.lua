-- Lobby front end. All authoritative changes go through the Python bridge.
if reframework:get_game_name() ~= "re2" then return end

local status, local_error, last_poll, last_view_id
local visible, opened_from_main = false, false
local resume_main_menu
local font_cache, draft_key, slot = {}, nil, ""
local campaign, difficulty = 1, 1
local campaign_labels = { "Nicht festgelegt", "Leon", "Claire" }
local campaign_values = { false, "leon", "claire" }
local difficulty_labels = { "Nicht festgelegt", "Assistiert", "Standard", "Hardcore" }
local difficulty_values = { false, "assisted", "standard", "hardcore" }
local command_number, pending_until = 0, 0
local last_report
local input = require('re2_coop.lobby_input').new()
local toggle_down, escape_down = false, false
local seen_live = false
local load_failures = {
    selection_changed = "Auswahl geändert. Spielstand und Bereitschaft erneut prüfen.",
    local_source_unavailable = "Host: Geschützten Spielstand erneut prüfen.",
    local_file_changed = "Die Slot-Datei des Hosts hat sich geändert.",
    guest_source_unavailable = "Gast: Geschützten Spielstand erneut prüfen.",
    guest_file_mismatch = "Gast und Host haben verschiedene Slot-Dateien.",
    guest_ack_expired = "Gastbestätigung abgelaufen. Verbindung prüfen und erneut starten.",
    start_window_expired = "Startfreigabe abgelaufen. Beide Spieler erneut prüfen.",
    cancelled = "Ladeprüfung abgebrochen. Bereitschaft erneut prüfen.",
}

local function load_file(path)
    local matches = fs.glob("^" .. path:gsub("%.", "\\.") .. "$")
    if not matches or #matches == 0 then return nil end
    local ok, value = pcall(json.load_file, path)
    return ok and value or nil
end

local function integer(value)
    return type(value) == "number" and value >= 0 and value <= 9007199254740991 and value % 1 == 0
end

local function fresh(value)
    return integer(value) and os.time() - value >= 0 and os.time() - value <= 3
end

local function valid(value)
    if type(value) ~= "table" or value.schema ~= 1 or not integer(value.written_at)
        or (value.role ~= "H" and value.role ~= "G") or type(value.connected) ~= "boolean" then return false end
    if value.lobby == nil then return true end
    local message = value.lobby
    if type(message) ~= "table" or type(message.session_id) ~= "string" or message.session_id == ""
        or not integer(message.sequence) or type(message.data) ~= "table" then return false end
    local data = message.data
    local reference = data.save_ref
    if reference ~= nil then
        if type(reference) ~= "table" or type(reference.available) ~= "boolean" then return false end
        if reference.available and (not integer(reference.scenario) or reference.scenario > 3
            or type(reference.label) ~= "string" or type(reference.difficulty_label) ~= "string") then return false end
    end
    return type(data.host_id) == "string" and type(data.guest_id) == "string"
        and data.host_id ~= data.guest_id and integer(data.revision)
        and type(data.connected) == "boolean" and type(data.settings) == "table"
        and (data.save_slot == nil or type(data.save_slot) == "string")
        and type(data.ready) == "table" and type(data.ready[data.host_id]) == "boolean"
        and type(data.ready[data.guest_id]) == "boolean"
end

local function find(values, value)
    for i, item in ipairs(values) do if item == value then return i end end
    return 1
end

local function poll()
    local now = os.time()
    if now == last_poll then return end
    last_poll = now
    local value = load_file("re2_coop_lobby.json")
    status = valid(value) and value or nil
    if status and fresh(status.written_at) then seen_live = true end
    local view = load_file("re2_coop_lobby_view.json")
    if type(view) == "table" and type(view.visible) == "boolean"
        and type(view.id) == "string" and view.id ~= last_view_id then
        visible, last_view_id = view.visible, view.id
    end
    if status and status.lobby then
        local key = status.lobby.session_id .. ":" .. status.lobby.data.revision
        if key ~= draft_key then
            local data = status.lobby.data
            draft_key, slot = key, data.save_slot or ""
            campaign = find(campaign_values, data.settings.campaign)
            difficulty = find(difficulty_values, data.settings.difficulty)
        end
    end
end

local function steam_scope(scope)
    if type(scope) == "table" and type(scope.session_id) == "string" and scope.session_id ~= ""
        and integer(scope.revision) and scope.revision > 0 and scope.revision <= 0xffffffff then
        return scope
    end
end

local function pending_invite(state)
    if state.role ~= "G" or state.connected or state.lobby or state.steam_lobby ~= "invite-pending" then return nil end
    return steam_scope(state.steam_invite)
end

local function active_membership(state)
    if (state.role == "H" and state.steam_lobby == "owned")
        or (state.role == "G" and state.steam_lobby == "joined") then
        return steam_scope(state.steam_membership)
    end
end

local function in_title_menu()
    local ok, ready = pcall(function()
        local flow = sdk.get_managed_singleton('app.ropeway.gamemastering.MainFlowManager')
        return flow and flow:call('get_IsInTitle') == true and flow:call('get_IsInLoadGameData') == false
    end)
    return ok and ready == true
end

local function send(action, value)
    if not status or not fresh(status.written_at) then return end
    if status.campaign_setup_status == "closing" then return end
    if os.time() < pending_until then return end
    local session_id, revision
    if action == "prepare-campaign" then
        local scope = steam_scope(status.campaign_setup)
        if not scope or not in_title_menu() then return end
        session_id, revision = scope.session_id, scope.revision
    elseif action == "join-invite" or action == "leave" then
        local find_scope = action == "leave" and active_membership or pending_invite
        local scope = find_scope(status)
        if not scope then return end
        session_id, revision = scope.session_id, scope.revision
    else
        if not status.lobby then return end
        local readiness = action == "ready" or action == "ready-campaign"
        if not readiness and status.role ~= "H" then return end
        if readiness and not status.connected then return end
        session_id, revision = status.lobby.session_id, status.lobby.data.revision
    end
    command_number = command_number + 1
    local command = { id = string.format("lobby-ui-%d-%d-%.6f", os.time(), command_number, os.clock()),
        written_at = os.time(), session_id = session_id, revision = revision, action = action, value = value }
    local ok, result = pcall(json.dump_file, "re2_coop_lobby_command.json", command)
    if ok and result ~= false then
        pending_until, local_error = os.time() + 2, nil
    else
        local_error = "Die Anfrage konnte nicht gespeichert werden."
    end
end

local function style_color(index, color)
    -- REFramework d1461375 checks sol::object::is<int>() for style colors.
    if color > 0x7FFFFFFF then color = color - 0x100000000 end
    imgui.push_style_color(index, color)
end

local function text_at(x, y, text, color, font)
    imgui.set_cursor_pos({x, y})
    if font then imgui.push_font(font) end
    -- text() is the unformatted binding; bridge messages may contain percent signs.
    style_color(0, color)
    imgui.text(text)
    imgui.pop_style_color(1)
    if font then imgui.pop_font() end
end

local function draw_cursor(screen, scale)
    if reframework:is_drawing_ui() or not imgui.get_mouse or not imgui.get_foreground_draw_list then return end
    local point = imgui.get_mouse()
    if not point or not (point.x >= 0 and point.x < screen.x and point.y >= 0 and point.y < screen.y) then return end
    local size = math.max(12, 22 * scale)
    local tip = {point.x, point.y}
    local bottom = {point.x + size * 0.27, point.y + size}
    local right = {point.x + size * 0.83, point.y + size * 0.66}
    local layer = imgui.get_foreground_draw_list()
    layer:add_triangle_filled(tip, bottom, right, 0xFFF5EFE3)
    layer:add_triangle(tip, bottom, right, 0xFF0B0C0D, 1.7)
end

-- REFramework's window key state is cleared on WM_KILLFOCUS. A neutral
-- sample is required after opening the menu or missing a render update.
local navigation_keys = {[0x26] = "up", [0x28] = "down", [0x25] = "left", [0x27] = "right",
    [0x0D] = "accept", [0x20] = "accept"}
local focused_row, previous_rows, armed, previous_frame = nil, {}, false, nil
local editing_field = false

local function reset_navigation()
    focused_row, previous_rows, armed, previous_frame = nil, {}, false, nil
    editing_field = false
end

local function navigation_key()
    local now = os.clock()
    if not previous_frame or now < previous_frame or now - previous_frame > 0.5 then reset_navigation() end
    previous_frame = now
    if editing_field or reframework:is_drawing_ui() or reframework:is_key_down(0x12) or reframework:is_key_down(0x11)
        or imgui.is_mouse_down and imgui.is_mouse_down(0)
        or imgui.is_mouse_released and imgui.is_mouse_released(0) then
        armed, focused_row = false, nil
        return
    end
    local action
    for key, name in pairs(navigation_keys) do
        if reframework:is_key_down(key) then
            if action then armed = false; return end
            action = name
        end
    end
    if not action then armed = true; return end
    if not armed then return end
    armed = false
    if (action == "up" or action == "down") and #previous_rows > 0 then
        local i
        for index, id in ipairs(previous_rows) do if id == focused_row then i = index; break end end
        if action == "down" then i = (i or 0) % #previous_rows + 1
        else i = ((i or 1) - 2) % #previous_rows + 1 end
        focused_row = previous_rows[i]
    end
    return action
end

local function render()
    poll()
    local down = reframework:is_key_down(0x78) -- F9
    local escape = reframework:is_key_down(0x1B)
    if escape and not escape_down and visible then
        visible = false
    elseif down and not toggle_down and (visible or status or opened_from_main) then
        visible = not visible
    end
    toggle_down, escape_down = down, escape
    if not visible then
        reset_navigation()
        input:frame(false)
        if opened_from_main and not input.captured and not escape and not down then
            opened_from_main = false
            if resume_main_menu then resume_main_menu() end
        end
        return
    end
    if not opened_from_main and not seen_live then reset_navigation(); input:frame(false); return end
    local view_state = status or {connected = false}
    input:frame(true)
    local screen = imgui.get_display_size()
    if not screen or screen.x <= 0 or screen.y <= 0 then reset_navigation(); return end
    local scale = math.min(1, screen.y / 860, screen.x / 760)
    local font_scale = math.max(0.5, math.floor(scale * 10) / 10)
    if not font_cache[font_scale] then
        font_cache[font_scale] = {title = imgui.load_font(nil, 40 * font_scale),
            body = imgui.load_font(nil, 22 * font_scale), small = imgui.load_font(nil, 16 * font_scale)}
    end
    local fonts = font_cache[font_scale]
    if not fonts.title or not fonts.body or not fonts.small then
        font_cache[font_scale] = nil
        reset_navigation()
        return
    end
    if not input:can_draw() then reset_navigation(); return end
    local key, rows, keyboard_action = navigation_key(), {}, nil
    local mouse_activated, focused_present = false, false
    editing_field = false
    local function capture_field()
        editing_field, focused_row, key, armed = true, nil, nil, false
    end
    local function row(id, enabled)
        if enabled then rows[#rows + 1] = id end
        if enabled and focused_row == id then focused_present = true; return true end
        return false
    end
    local function combo(id, index, values, enabled, first)
        local selected = row(id, enabled)
        if selected then style_color(7, 0xFF695D49) end
        local changed, value = imgui.combo(id, index, values)
        if selected then imgui.pop_style_color(1) end
        -- BeginCombo seeds its popup ID with this widget's ID.
        imgui.push_id(id)
        local popup_open = imgui.is_popup_open("##ComboPopup")
        imgui.pop_id()
        if popup_open then capture_field() end
        if changed then mouse_activated = true; return changed, value end
        if selected and (key == "left" or key == "right") then
            first = first or 1
            local count = #values - first + 1
            if count > 0 then
                if index < first then return true, key == "left" and #values or first end
                return true, first + (index - first + (key == "left" and -1 or 1)) % count
            end
        end
        return false, index
    end
    imgui.get_background_draw_list():add_rect_filled({0, 0}, {screen.x, screen.y}, 0xFF131312, 0, 0)
    -- Fixed proportions follow the restrained, left-aligned RE2 menu style.
    local x, y = math.floor(screen.x * 0.055), math.floor((screen.y - 800 * scale) / 2)
    imgui.set_next_window_pos({x, y}, 1)
    imgui.set_next_window_size({620 * scale, 800 * scale}, 1)
    style_color(0, 0xFFE4E0D8)
    style_color(2, 0xF0151618)
    style_color(5, 0xFF424342)
    style_color(7, 0xFF292A2B)
    style_color(21, 0xFF353638)
    style_color(22, 0xFF505153)
    style_color(23, 0xFF616265)
    imgui.begin_window("RE2 Coop Lobby", nil, 1 | 2 | 4 | 32 | 256)
    local function label(px, py, value, color, font)
        text_at(px * scale, py * scale, value, color or 0xFFE4E0D8, font or fonts.body)
    end
    local function disabled_hint(reason)
        -- ImGuiHoveredFlags_AllowWhenDisabled in the pinned REFramework ImGui.
        if reason and imgui.is_item_hovered(1 << 10) then
            imgui.begin_tooltip()
            imgui.text(reason)
            imgui.end_tooltip()
        end
    end
    local function button(py, title, enabled, action, reason)
        imgui.set_cursor_pos({28 * scale, py * scale})
        imgui.begin_disabled(not enabled)
        imgui.push_font(fonts.body)
        local selected = row(title, enabled)
        if selected then style_color(21, 0xFF695D49) end
        local pressed = imgui.button(title, {564 * scale, 42 * scale})
        if selected then imgui.pop_style_color(1) end
        imgui.pop_font()
        imgui.end_disabled()
        if not enabled then disabled_hint(reason) end
        if pressed and enabled then mouse_activated = true; action()
        elseif selected and key == "accept" then keyboard_action = action end
    end
    local live = fresh(view_state.written_at)
    local message = view_state.lobby
    local data = message and message.data
    local connected = live and view_state.connected and data and data.connected
    local host = view_state.role == "H"
    local steam_lobby = view_state.steam_lobby
    local invite = live and pending_invite(view_state)
    local membership = live and active_membership(view_state)
    local restarting = live and view_state.campaign_setup_status == "closing"
    local waiting
    if not live then waiting = "Kein aktueller Bridge-Status. Verbindung wird geprüft."
    elseif restarting then waiting = "RE2 schließen. Steam startet das Spiel neu."
    elseif steam_lobby == "leaving" then waiting = "Steam-Lobby wird verlassen …"
    elseif os.time() < pending_until then waiting = "Anfrage wird verarbeitet …" end
    local lobby_wait = waiting or (not data and "Warten auf den Lobby-Status.")
    local enabled = not lobby_wait
    local native = data and data.save_ref ~= nil
    local save_available = not native or data.save_ref.available
    local local_save_missing = connected and native and not host and save_available and view_state.local_save_matches ~= true
    local catalog = host and view_state.catalog
    local labels, keys, selected = {"Spielstand wählen"}, {false}, 1
    if native and type(catalog) == "table" and catalog.available and type(catalog.entries) == "table" then
        for _, entry in ipairs(catalog.entries) do
            if type(entry) == "table" and type(entry.key) == "string" and type(entry.reference) == "table"
                and type(entry.reference.label) == "string" and type(entry.saved_at) == "string" then
                labels[#labels + 1] = entry.reference.label .. " | " .. entry.saved_at:sub(1, 16)
                keys[#keys + 1] = entry.key
                if entry.key == slot then selected = #keys end
            end
        end
    end
    local can_select = enabled and host and (not native or #keys > 1)
    local selection_help = lobby_wait or (not host and "Der Host wählt den Spielstand.")
        or (native and #keys <= 1 and "Kein verfügbarer Eintrag im Spielstandkatalog.")
    label(28, 22, "RESIDENT EVIL 2", 0xFFAAA79F, fonts.small)
    label(26, 45, "K O O P", nil, fonts.title)
    label(28, 103, "PRIVATE SITZUNG", 0xFFAAA79F, fonts.small)
    label(412, 103, "Esc / F9: Schließen", 0xFFAAA79F, fonts.small)
    local connection_label = connected and "Mit Spieler verbunden" or "Warten auf einen Spieler"
    if not live then
        connection_label = status and "Verbindung unterbrochen" or "Koop-Verbindung wird aufgebaut …"
    elseif steam_lobby == "unavailable" then
        connection_label = "Steam-Plugin nicht erreichbar"
    elseif steam_lobby == "leaving" then
        connection_label = "Steam-Lobby wird verlassen …"
    elseif host and steam_lobby ~= nil and steam_lobby ~= "owned" then
        if steam_lobby == "idle" then
            connection_label = "Keine Steam-Lobby geöffnet"
        elseif steam_lobby == "creating" then
            connection_label = "Steam erstellt die Lobby …"
        else
            connection_label = "Steam-Lobby nicht erreichbar"
        end
    elseif view_state.role == "G" and not connected then
        if invite then
            connection_label = "Steam-Einladung verfügbar"
        elseif steam_lobby == "joining" or steam_lobby == "verifying" then
            connection_label = "Steam prüft den Beitritt …"
        elseif steam_lobby == "idle" then
            connection_label = "Warten auf eine Steam-Einladung"
        elseif steam_lobby == "joined" then
            connection_label = "Warten auf den Host"
        end
    end
    label(28, 131, connection_label)
    local role_label = view_state.role and (host and "DU BIST HOST" or "DU BIST GAST") or "STEAM-BRIDGE WARTET"
    label(28, 167, role_label, 0xFFAAA79F, fonts.small)
    label(28, 205, native and "VORHANDENEN SPIELSTAND LADEN" or "SPIELSTAND", 0xFFAAA79F, fonts.small)
    if native then label(320, 205, "Neues Spiel noch nicht verfügbar", 0xFFAAA79F, fonts.small) end
    imgui.set_cursor_pos({28 * scale, 230 * scale})
    imgui.set_next_item_width(564 * scale)
    imgui.begin_disabled(not can_select)
    local changed, value
    if native then
        if host then
            changed, value = combo("##coop-save", selected, labels, can_select, 2)
            if changed and keys[value] then slot, selected = keys[value], value end
        else
            imgui.text(data.save_ref.available and data.save_ref.label or "Spielstand nicht verfügbar")
        end
    else
        changed, value = imgui.input_text("##coop-save", slot)
        if imgui.is_item_active() then capture_field() end
        if changed then slot = value end
    end
    imgui.end_disabled()
    if not can_select then disabled_hint(selection_help) end
    label(28, 271, "KAMPAGNE", 0xFFAAA79F, fonts.small)
    label(320, 271, "SCHWIERIGKEIT", 0xFFAAA79F, fonts.small)
    imgui.begin_disabled(not (enabled and host and not native))
    imgui.set_cursor_pos({28 * scale, 297 * scale})
    imgui.set_next_item_width(270 * scale)
    if native then
        local scenarios = {[0] = "Leon (1. Durchlauf)", "Claire (1. Durchlauf)", "Leon (2. Durchlauf)", "Claire (2. Durchlauf)"}
        imgui.text(save_available and scenarios[data.save_ref.scenario] or "Nicht verfügbar")
    else
        changed, value = combo("##coop-campaign", campaign, campaign_labels, enabled and host)
        if changed then campaign = value end
        if not enabled or not host then disabled_hint(selection_help) end
    end
    imgui.set_cursor_pos({320 * scale, 297 * scale})
    imgui.set_next_item_width(272 * scale)
    if native then
        imgui.text(save_available and data.save_ref.difficulty_label or "Nicht verfügbar")
    else
        changed, value = combo("##coop-difficulty", difficulty, difficulty_labels, enabled and host)
        if changed then difficulty = value end
        if not enabled or not host then disabled_hint(selection_help) end
    end
    imgui.end_disabled()
    button(343, "Auswahl übernehmen", can_select and #slot > 0 and #slot <= 128 and (not native or selected > 1), function()
        local settings = {}
        for key, item in pairs(data.settings) do settings[key] = item end
        if not native and campaign_values[campaign] then settings.campaign = campaign_values[campaign] end
        if not native and difficulty_values[difficulty] then settings.difficulty = difficulty_values[difficulty] end
        send("configure", {save_slot = slot, settings = settings})
    end, selection_help or "Gültigen Spielstand auswählen.")
    local host_ready = connected and data.ready[data.host_id]
    local guest_ready = connected and data.ready[data.guest_id]
    local campaign_supported = live and view_state.campaign_start_supported == true
    local peer_incompatible = connected and campaign_supported and view_state.campaign_peer_supported == false
    local check = data and data.load_check
    local load_pending = type(check) == "table" and check.phase ~= "failed"
    local load_help
    if load_pending then
        load_help = check.campaign_start and "Beide Spiele bereiten den geschützten Start vor …"
            or "Ladeprüfung aktiv. Erst abschließen oder abbrechen."
    elseif type(check) == "table" and check.phase == "failed" then
        load_help = load_failures[check.reason] or "Ladeprüfung fehlgeschlagen. Status beider PCs prüfen."
    end
    label(28, 411, host and "DU · HOST" or "HOST", 0xFFAAA79F, fonts.small)
    label(320, 411, view_state.role == "G" and "DU · GAST" or "GAST", 0xFFAAA79F, fonts.small)
    label(28, 437, host_ready and "Bereit" or "Nicht bereit", host_ready and 0xFFB5C89D or 0xFFE4E0D8)
    label(320, 437, guest_ready and "Bereit" or "Nicht bereit", guest_ready and 0xFFB5C89D or 0xFFE4E0D8)
    local own_ready = host and host_ready or not host and guest_ready
    local can_ready = enabled and connected and (own_ready or save_available and not local_save_missing)
    local ready_label = campaign_supported and not peer_incompatible and not host and "Für Kampagnenstart bereit" or "Bereit"
    button(481, own_ready and "Bereitschaft zurücknehmen" or ready_label, can_ready, function()
        send(ready_label == "Für Kampagnenstart bereit" and not own_ready and "ready-campaign" or "ready", not own_ready)
    end, lobby_wait or (not connected and "Zuerst die Verbindung zum Mitspieler herstellen.")
        or (local_save_missing and "Passender lokaler Spielstand erforderlich.") or "Host muss einen verfügbaren Spielstand wählen.")
    local start_block = lobby_wait or (not host and "Der Host startet die Kampagne.")
        or (not connected and "Warte auf den Mitspieler und eine aktive Lobby.")
        or (load_pending and load_help)
        or (not campaign_supported and "Geschützte Kampagne zuerst vorbereiten.")
        or (peer_incompatible and "Geschützten Kampagnenmodus auf beiden PCs prüfen.")
        or (view_state.campaign_start_ready ~= true and
            (not save_available and "Host muss einen verfügbaren Spielstand wählen."
            or not host_ready and "Der Host muss seine Bereitschaft bestätigen."
            or not guest_ready and "Der Gast muss seine Bereitschaft bestätigen."
            or "Gast: Bereitschaft zurücknehmen und für Kampagnenstart bestätigen."))
    local can_start = not start_block
    local start_label = view_state.role == "G" and "Warten auf Host" or "Spiel starten"
    button(533, start_label, can_start, function() send("start-campaign", true) end, start_block)
    if view_state.role == "G" and not message and steam_lobby ~= nil then
        button(586, "Steam-Einladung annehmen", invite and not restarting and os.time() >= pending_until,
            function() send("join-invite", true) end, waiting or "Eine aktuelle Steam-Einladung des Hosts abwarten.")
    elseif host and steam_lobby ~= nil and steam_lobby ~= "owned" then
        button(586, "Private Steam-Lobby erstellen", enabled and steam_lobby == "idle", function() send("create", true) end,
            lobby_wait or connection_label)
    elseif host and (not connected or not campaign_supported or steam_lobby == nil) then
        button(586, "Spieler über Steam einladen", enabled, function() send("invite", true) end, lobby_wait)
    end
    if membership then
        button(638, "Steam-Lobby verlassen", not waiting, function() send("leave", true) end, waiting)
    elseif live and steam_scope(view_state.campaign_setup) then
        button(638, "Geschützte Kampagne vorbereiten", not restarting and in_title_menu() and os.time() >= pending_until,
            function() send("prepare-campaign", true) end, waiting or "Vorbereitung im Titelmenü öffnen.")
    end
    local setup_error = type(view_state.campaign_setup_error) == "string" and view_state.campaign_setup_error
    local bridge_error = type(view_state.error) == "string" and view_state.error ~= "" and view_state.error
    label(28, 690, waiting or
        local_error or (local_save_missing and "Passender lokaler Spielstand erforderlich.") or
        bridge_error or load_help or
        (peer_incompatible and "Geschützten Kampagnenmodus auf beiden PCs prüfen.") or
        (view_state.campaign_setup_status == "failed" and
            (setup_error or "Vorbereitung fehlgeschlagen. Erneut versuchen.")) or
        start_block or "", 0xFF9BA8D0, fonts.small)
    if bridge_error or setup_error then disabled_hint(bridge_error or setup_error) end
    button(722, "Zurück", true, function()
        visible = false
    end)
    label(28, 773, "Pfeile: Navigieren / Auswählen    Eingabe: Bestätigen", 0xFFAAA79F, fonts.small)
    previous_rows = rows
    if not focused_present or mouse_activated then focused_row = nil end
    if keyboard_action and not mouse_activated then keyboard_action() end
    imgui.end_window()
    imgui.pop_style_color(7)
    if visible then draw_cursor(screen, scale) end
    local report = string.format("role=%s connected=%s revision=%s fresh=%s start_button_visible=true start_button=%s start_enabled=%s blocked=%s load=%s display=%.0fx%.0f",
        view_state.role or "waiting", tostring(not not connected), tostring(data and data.revision or "none"),
        tostring(live), start_label, tostring(can_start), start_block or "-", load_help or "-", screen.x, screen.y)
    local source = view_state.source_commit
    local session = message and message.session_id
    local loss = type(view_state.last_link_loss) == "table" and view_state.last_link_loss.reason
    report = report .. string.format(" build=%s session=%s steam=%s last_link_loss=%s",
        type(source) == "string" and #source == 40 and source:match("^%x+$") or "unknown",
        type(session) == "string" and #session == 32 and session:match("^%x+$") or "-",
        type(steam_lobby) == "string" and steam_lobby:match("^[a-z-]+$") or "-",
        type(loss) == "string" and loss:match("^[a-z_]+$") or "-")
    if report ~= last_report then
        log.info("RE2_COOP_LOBBY_VIEW " .. report)
        last_report = report
    end
end

local ok, installed = pcall(function()
    if not input.installed then return false end
    return require('re2_coop.main_menu').install(function()
        visible, opened_from_main = true, true
    end)
end)
if ok and installed then
    resume_main_menu = installed
    visible = false
elseif not ok then
    log.info("RE2_COOP_MAIN_MENU unavailable: " .. tostring(installed))
end
re.on_frame(render)
