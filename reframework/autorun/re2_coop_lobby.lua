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

local function text_at(x, y, text, color, font)
    imgui.set_cursor_pos({x, y})
    if font then imgui.push_font(font) end
    imgui.text_colored(text, color)
    if font then imgui.pop_font() end
end

local function style_color(index, color)
    -- REFramework d1461375 checks sol::object::is<int>() for style colors.
    if color > 0x7FFFFFFF then color = color - 0x100000000 end
    imgui.push_style_color(index, color)
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

local function render()
    poll()
    local down = reframework:is_key_down(0x78) -- F9
    local escape = reframework:is_key_down(0x1B)
    if escape and not escape_down and visible then
        visible = false
    elseif down and not toggle_down and (status or opened_from_main) then
        visible = not visible
    end
    toggle_down, escape_down = down, escape
    if not visible then
        input:frame(false)
        if opened_from_main and not input.captured and not escape and not down then
            opened_from_main = false
            if resume_main_menu then resume_main_menu() end
        end
        return
    end
    if not opened_from_main and (not status or not seen_live) then input:frame(false); return end
    local view_state = status or {connected = false}
    local screen = imgui.get_display_size()
    local scale = math.min(1, screen.y / 860, screen.x / 760)
    local font_scale = math.max(0.5, math.floor(scale * 10) / 10)
    if not font_cache[font_scale] then
        font_cache[font_scale] = {title = imgui.load_font(nil, 40 * font_scale),
            body = imgui.load_font(nil, 22 * font_scale), small = imgui.load_font(nil, 16 * font_scale)}
    end
    local fonts = font_cache[font_scale]
    if not fonts.title or not fonts.body or not fonts.small then
        font_cache[font_scale] = nil
        input:frame(false)
        return
    end
    input:frame(true)
    if not input:can_draw() then return end
    -- Fixed proportions follow the restrained, left-aligned RE2 menu style.
    local x, y = math.floor(screen.x * 0.055), math.floor((screen.y - 740 * scale) / 2)
    imgui.set_next_window_pos({x, y}, 1)
    imgui.set_next_window_size({620 * scale, 740 * scale}, 1)
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
    local function button(py, title, enabled, action)
        imgui.set_cursor_pos({28 * scale, py * scale})
        imgui.begin_disabled(not enabled)
        imgui.push_font(fonts.body)
        local pressed = imgui.button(title, {564 * scale, 42 * scale})
        imgui.pop_font()
        imgui.end_disabled()
        if pressed and enabled then action() end
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
    local enabled = live and data ~= nil and not restarting and steam_lobby ~= "leaving" and os.time() >= pending_until
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
    label(28, 205, "SPIELSTAND", 0xFFAAA79F, fonts.small)
    imgui.set_cursor_pos({28 * scale, 230 * scale})
    imgui.set_next_item_width(564 * scale)
    imgui.begin_disabled(not can_select)
    local changed, value
    if native then
        if host then
            changed, value = imgui.combo("##coop-save", selected, labels)
            if changed and keys[value] then slot, selected = keys[value], value end
        else
            imgui.text(data.save_ref.available and data.save_ref.label or "Spielstand nicht verfügbar")
        end
    else
        changed, value = imgui.input_text("##coop-save", slot)
        if changed then slot = value end
    end
    imgui.end_disabled()
    label(28, 271, "KAMPAGNE", 0xFFAAA79F, fonts.small)
    label(320, 271, "SCHWIERIGKEIT", 0xFFAAA79F, fonts.small)
    imgui.begin_disabled(not (enabled and host and not native))
    imgui.set_cursor_pos({28 * scale, 297 * scale})
    imgui.set_next_item_width(270 * scale)
    if native then
        local scenarios = {[0] = "Leon (1. Durchlauf)", "Claire (1. Durchlauf)", "Leon (2. Durchlauf)", "Claire (2. Durchlauf)"}
        imgui.text(save_available and scenarios[data.save_ref.scenario] or "Nicht verfügbar")
    else
        changed, value = imgui.combo("##coop-campaign", campaign, campaign_labels)
        if changed then campaign = value end
    end
    imgui.set_cursor_pos({320 * scale, 297 * scale})
    imgui.set_next_item_width(272 * scale)
    if native then
        imgui.text(save_available and data.save_ref.difficulty_label or "Nicht verfügbar")
    else
        changed, value = imgui.combo("##coop-difficulty", difficulty, difficulty_labels)
        if changed then difficulty = value end
    end
    imgui.end_disabled()
    button(343, "Auswahl übernehmen", can_select and #slot > 0 and #slot <= 128 and (not native or selected > 1), function()
        local settings = {}
        for key, item in pairs(data.settings) do settings[key] = item end
        if not native and campaign_values[campaign] then settings.campaign = campaign_values[campaign] end
        if not native and difficulty_values[difficulty] then settings.difficulty = difficulty_values[difficulty] end
        send("configure", {save_slot = slot, settings = settings})
    end)
    local host_ready = connected and data.ready[data.host_id]
    local guest_ready = connected and data.ready[data.guest_id]
    local campaign_supported = live and view_state.campaign_start_supported == true
    local peer_incompatible = connected and campaign_supported and view_state.campaign_peer_supported == false
    local check = data and data.load_check
    local campaign_pending = type(check) == "table" and check.campaign_start == true and check.phase ~= "failed"
    label(28, 411, host and "DU · HOST" or "HOST", 0xFFAAA79F, fonts.small)
    label(320, 411, view_state.role == "G" and "DU · GAST" or "GAST", 0xFFAAA79F, fonts.small)
    label(28, 437, host_ready and "Bereit" or "Nicht bereit", host_ready and 0xFFB5C89D or 0xFFE4E0D8)
    label(320, 437, guest_ready and "Bereit" or "Nicht bereit", guest_ready and 0xFFB5C89D or 0xFFE4E0D8)
    local own_ready = host and host_ready or not host and guest_ready
    local can_ready = enabled and connected and (own_ready or save_available and not local_save_missing)
    local ready_label = campaign_supported and not peer_incompatible and not host and "Für Kampagnenstart bereit" or "Bereit"
    button(481, own_ready and "Bereitschaft zurücknehmen" or ready_label, can_ready, function()
        send(ready_label == "Für Kampagnenstart bereit" and not own_ready and "ready-campaign" or "ready", not own_ready)
    end)
    if view_state.role == "G" and not message and steam_lobby ~= nil then
        button(533, "Steam-Einladung annehmen", invite and not restarting and os.time() >= pending_until,
            function() send("join-invite", true) end)
    elseif host and steam_lobby ~= nil and steam_lobby ~= "owned" then
        button(533, "Private Steam-Lobby erstellen", enabled and steam_lobby == "idle", function() send("create", true) end)
    elseif host and connected and campaign_supported then
        button(533, "Kampagne starten", enabled and not peer_incompatible
            and view_state.campaign_start_ready == true and not campaign_pending,
            function() send("start-campaign", true) end)
    else
        button(533, "Spieler über Steam einladen", enabled and host, function() send("invite", true) end)
    end
    if membership then
        button(586, "Steam-Lobby verlassen", os.time() >= pending_until, function() send("leave", true) end)
    elseif live and steam_scope(view_state.campaign_setup) then
        button(586, "Geschützte Kampagne vorbereiten", not restarting and in_title_menu() and os.time() >= pending_until,
            function() send("prepare-campaign", true) end)
    end
    label(28, 638, restarting and "RE2 schließen. Steam startet das Spiel neu." or
        os.time() < pending_until and "Anfrage wird verarbeitet …" or
        local_error or (local_save_missing and "Passender lokaler Spielstand erforderlich.") or
        (campaign_supported and view_state.error and "Kampagnenstart abgelehnt. Spielstand und Titelmenü prüfen.") or
        (peer_incompatible and "Beide Spieler brauchen einen kompatiblen Kampagnenbuild.") or
        (campaign_pending and "Beide Spiele bereiten den geschützten Start vor …") or
        (view_state.campaign_setup and view_state.error) or
        (view_state.campaign_setup_status == "failed" and "Vorbereitung fehlgeschlagen. Erneut versuchen.") or
        (view_state.error and "Anfrage fehlgeschlagen. Erneut versuchen.") or "", 0xFF9BA8D0, fonts.small)
    button(665, "Zurück", true, function()
        visible = false
    end)
    imgui.end_window()
    imgui.pop_style_color(7)
    if visible then draw_cursor(screen, scale) end
    local report = string.format("role=%s connected=%s revision=%s fresh=%s", view_state.role or "waiting",
        tostring(not not connected), tostring(data and data.revision or "none"), tostring(live))
    if report ~= last_report then
        log.info("RE2_COOP_LOBBY_VIEW " .. report .. string.format(" display=%.0fx%.0f", screen.x, screen.y))
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
