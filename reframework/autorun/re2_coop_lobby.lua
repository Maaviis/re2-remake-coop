-- Lobby front end. All authoritative changes go through the Python bridge.
if reframework:get_game_name() ~= "re2" then return end

local status, local_error, last_poll, last_view_id
local visible, opened_from_main = false, false
local resume_main_menu
local font_cache, draft_key = {}, nil
local page, archive_page = "lobby", 1
local archive_choices
local new_scenarios, new_scenario_labels = {"LEON_A", "CLAIRE_A"}, {"Leon (1. Durchlauf)", "Claire (1. Durchlauf)"}
local new_difficulties, new_difficulty_labels = {"EASY", "NORMAL", "HARD"}, {"Assistiert", "Standard", "Hardcore"}
local new_scenario, new_difficulty = 1, 2
local command_number, pending_until = 0, 0
local solo_request, solo_block
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

local start_errors = {
    solo_lobby_stale = "Steam-Bridge hat keinen aktuellen Lobby-Status geliefert.",
    solo_lobby_changed = "Für den Solotest wird eine eigene leere Steam-Lobby benötigt.",
    solo_native_peer_stale = "Steam hat die aktuelle Mitgliedschaft noch nicht bestätigt.",
    solo_membership_changed = "Die Steam-Mitgliedschaft hat sich geändert. Leere Host-Lobby prüfen.",
    solo_mount_lost = "RE2 konnte den geschützten Koop-Ordner nicht bestätigen.",
    solo_scope_changed = "Lobby oder Koop-Ordner hat während des Starts gewechselt.",
    solo_request_failed = "Solostart konnte nicht an RE2 übergeben werden.",
    new_game_title_not_ready = "RE2 wartet auf das Hauptmenü. Andere Titelmenüs schließen.",
    new_game_title_changed = "Das Titelmenü hat gewechselt. Beide Testspiele neu vorbereiten.",
    new_game_protection_lost = "Spielstandschutz verloren. RE2 beenden und die geschützte Kopie prüfen.",
    new_game_lobby_changed = "Lobby oder Bereitschaft hat sich beim Start geändert. Beide Testspiele neu vorbereiten.",
    new_game_admission_lost = "Die Startfreigabe ist abgelaufen. Verbindung prüfen und neu vorbereiten.",
    new_game_selection_mismatch = "Die geladene Figur oder Schwierigkeit weicht ab. Beide Testspiele beenden.",
    new_game_setup_failed = "RE2 konnte die neue Kampagne nicht anlegen. Build und REFramework-Version prüfen.",
    new_game_transition_failed = "Der native Szenenwechsel ist fehlgeschlagen. Guard-Bericht beider PCs prüfen.",
    new_game_transition_timeout = "RE2 hat den Szenenwechsel nicht bestätigt. Guard-Bericht beider PCs prüfen.",
}

local function ui_error(value)
    if type(value) ~= "string" or value == "" then return nil end
    -- Older bridges can include a user's private Steam path in a filesystem error.
    if value:find("\\", 1, true) or value:find("/", 1, true) or value:find("%c") then
        return "Datei- oder Bridge-Zugriff fehlgeschlagen. Installation prüfen."
    end
    return start_errors[value:match("^Kampagnenstart: (new_game_[a-z_]+)$")] or value
end

local function find(values, value)
    for i, item in ipairs(values) do if item == value then return i end end
end

local function valid(value)
    if type(value) ~= "table" or value.schema ~= 1 or not integer(value.written_at)
        or (value.role ~= "H" and value.role ~= "G") or type(value.connected) ~= "boolean" then return false end
    if value.lobby == nil then return true end
    local message = value.lobby
    if type(message) ~= "table" or type(message.session_id) ~= "string" or message.session_id == ""
        or not integer(message.sequence) or type(message.data) ~= "table" then return false end
    local data = message.data
    if type(data.settings) ~= "table" then return false end
    local archive = data.settings.coop_checkpoint
    if archive ~= nil and (type(archive) ~= "table" or not integer(archive.scenario) or archive.scenario > 1
        or not integer(archive.difficulty) or archive.difficulty > 2 or type(archive.saved_at) ~= "string"
        or not archive.saved_at:match("^%d%d%d%d%-%d%d%-%d%d %d%d:%d%d:%d%d$")
        or data.new_game ~= nil or data.save_slot ~= nil) then return false end
    local reference = data.save_ref
    if reference ~= nil then
        if type(reference) ~= "table" or type(reference.available) ~= "boolean" then return false end
        if reference.available and (not integer(reference.scenario) or reference.scenario > 3
            or type(reference.label) ~= "string" or type(reference.difficulty_label) ~= "string") then return false end
    end
    if data.new_game ~= nil then
        local choice = data.new_game
        if type(choice) ~= "table" or data.save_slot ~= nil or reference ~= nil
            or not find(new_scenarios, choice.scenario) or not find(new_difficulties, choice.difficulty) then
            return false
        end
    end
    return type(data.host_id) == "string" and type(data.guest_id) == "string"
        and data.host_id ~= data.guest_id and integer(data.revision)
        and type(data.connected) == "boolean" and type(data.settings) == "table"
        and (data.save_slot == nil or type(data.save_slot) == "string")
        and type(data.ready) == "table" and type(data.ready[data.host_id]) == "boolean"
        and type(data.ready[data.guest_id]) == "boolean"
end

local function poll()
    local now = os.time()
    if now == last_poll then return end
    last_poll = now
    local value = load_file("re2_coop_lobby.json")
    status = valid(value) and value or nil
    archive_choices = nil
    if status and status.role == "H" and integer(status.game_pid) and fresh(status.written_at) then
        local catalog = load_file("re2_coop_host_archive.json")
        if type(catalog) == "table" and catalog.schema == 1 and catalog.game_pid == status.game_pid and type(catalog.choices) == "table" then
            archive_choices = {}
            for _, item in ipairs(catalog.choices) do
                if type(item) == "table" and type(item.digest) == "string" and #item.digest == 64 and item.digest:match("^%x+$")
                    and type(item.namespace) == "string" and #item.namespace == 32 and item.namespace:match("^%x+$")
                    and item.slot == 0 and integer(item.scenario) and item.scenario <= 1 and integer(item.difficulty) and item.difficulty <= 2
                    and type(item.saved_at) == "string" and item.saved_at:match("^%d%d%d%d%-%d%d%-%d%d %d%d:%d%d:%d%d$") then
                    archive_choices[#archive_choices+1] = item
                end
            end
        end
    end
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
            draft_key, page, archive_page = key, "lobby", 1
            new_scenario = data.new_game and find(new_scenarios, data.new_game.scenario) or 1
            new_difficulty = data.new_game and find(new_difficulties, data.new_game.difficulty) or 2
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

local function poll_solo()
    if not solo_request then return end
    local now=os.time()
    if solo_request.checked==now then return end
    solo_request.checked=now
    local reply=load_file("re2_coop_solo_status.json")
    if type(reply)=="table" and reply.request_id==solo_request.id then
        if reply.active then
            if not in_title_menu() then solo_request=nil end
        elseif in_title_menu() then
            local_error=start_errors[reply.reason] or "RE2 hat den Solostart abgebrochen."
            if not solo_request.reported then visible=true; solo_request.reported=true end
            if reply.retryable then
                solo_block,solo_request=nil,nil
            else
                solo_block="RE2 muss zuerst wieder ein bedienbares Titelmenü bestätigen."
            end
        end
    elseif now-solo_request.sent>4 and in_title_menu() then
        visible,solo_request,solo_block=true,nil,nil
        local_error="RE2 hat die Startanfrage nicht bestätigt. Lobby und Koop-Ordner prüfen."
    end
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
    elseif action == "join-invite" or action == "leave" or action == "prepare-new-campaign" then
        if action == "prepare-new-campaign" and (not in_title_menu() or not status.direct_campaign_available) then return end
        local find_scope = action == "join-invite" and pending_invite or active_membership
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
    poll_solo()
    local down = reframework:is_key_down(0x78) -- F9
    local escape = reframework:is_key_down(0x1B)
    if escape and not escape_down and visible then
        if page ~= "lobby" then page = "lobby"; reset_navigation() else visible = false end
    elseif down and not toggle_down and (visible or status or opened_from_main) then
        visible = not visible
    end
    toggle_down, escape_down = down, escape
    if not visible then
        page = "lobby"
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
    elseif view_state.campaign_setup_status == "preparing" then waiting = "RE2 prüft den Koop-Ordner …"
    elseif steam_lobby == "leaving" then waiting = "Steam-Lobby wird verlassen …"
    elseif os.time() < pending_until then waiting = "Anfrage wird verarbeitet …" end
    local lobby_wait = waiting or (not data and "Warten auf den Lobby-Status.")
    local enabled = not lobby_wait
    local campaign_supported = live and view_state.campaign_start_supported == true
    local peer_incompatible = connected and campaign_supported and view_state.campaign_peer_supported == false
    local new_supported = connected and campaign_supported and not peer_incompatible and view_state.new_game_supported == true
    local new_game = data and data.new_game
    local selected_checkpoint = data and data.settings.coop_checkpoint
    local can_browse = enabled and host and steam_lobby == "owned" and membership
        and not (data.load_check and data.load_check.phase ~= "failed")
    local function change_page(value)
        page, archive_page = value, 1
        reset_navigation()
    end
    local function finish()
        previous_rows = rows
        if not focused_present or mouse_activated then focused_row = nil end
        if keyboard_action and not mouse_activated then keyboard_action() end
        imgui.end_window()
        imgui.pop_style_color(7)
        if visible then draw_cursor(screen, scale) end
    end
    if (not can_browse and page == "archive") or ((not host or not new_supported) and page == "new") then change_page("lobby") end
    if page == "archive" then
        label(28, 45, "Spiel laden", nil, fonts.title)
        local entries = archive_choices or {}
        local last_page = math.max(1, math.ceil(#entries / 8))
        archive_page = math.min(archive_page, last_page)
        if #entries == 0 then
            label(28, 146, archive_choices and "Keine Koop-Spielstände vorhanden." or "Host-Archiv noch nicht verfügbar.")
        end
        local first = (archive_page - 1) * 8 + 1
        for i = first, math.min(first + 7, #entries) do
            local entry = entries[i]
            local title = (entry.scenario == 0 and "Leon A" or "Claire A") .. " · " .. new_difficulty_labels[entry.difficulty+1] .. " · " .. entry.saved_at
            button(120 + (i-first)*53, title.."##"..entry.digest, true, function()
                send("select-checkpoint", {namespace=entry.namespace, digest=entry.digest})
                change_page("lobby")
            end)
        end
        if last_page > 1 then
            button(560, "Vorherige Seite", archive_page > 1, function() archive_page = archive_page-1 end, "Erste Seite.")
            button(612, "Nächste Seite", archive_page < last_page, function() archive_page = archive_page+1 end, "Letzte Seite.")
        end
        button(722, "Zurück", true, function() change_page("lobby") end)
        finish()
        return
    elseif page == "new" then
        label(28, 45, "Neues Spiel", nil, fonts.title)
        label(28, 150, "Geschichte")
        imgui.set_cursor_pos({28*scale, 180*scale})
        local changed, value = combo("##coop-new-scenario", new_scenario, new_scenario_labels, true)
        if changed then new_scenario = value end
        label(28, 243, "Schwierigkeit")
        imgui.set_cursor_pos({28*scale, 273*scale})
        changed, value = combo("##coop-new-difficulty", new_difficulty, new_difficulty_labels, true)
        if changed then new_difficulty = value end
        button(343, "Kampagne wählen", enabled, function()
            send("select-new-game", {scenario=new_scenarios[new_scenario], difficulty=new_difficulties[new_difficulty]})
            change_page("lobby")
        end, lobby_wait)
        button(722, "Zurück", true, function() change_page("lobby") end)
        finish()
        return
    end
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
    if selected_checkpoint then
        label(28, 202, (selected_checkpoint.scenario == 0 and "Leon A" or "Claire A") .. " · " .. new_difficulty_labels[selected_checkpoint.difficulty+1] .. " · " .. selected_checkpoint.saved_at)
    elseif new_game then
        label(28, 202, new_scenario_labels[find(new_scenarios,new_game.scenario)] .. " · " .. new_difficulty_labels[find(new_difficulties,new_game.difficulty)])
    end
    if membership and view_state.direct_campaign_available then
        button(252, "Neues Spiel vorbereiten", not waiting and in_title_menu(), function() send("prepare-new-campaign", true) end,
            waiting or "Im RE2-Titelmenü vorbereiten.")
    elseif host then
        button(252, "Neues Spiel", enabled and new_supported, function() change_page("new") end,
            lobby_wait or (not connected and "Warte auf den Mitspieler." or "Beide Spieler müssen die Kampagne vorbereiten."))
    end
    if host then
        button(307, "Spiel laden", can_browse, function() change_page("archive") end,
            lobby_wait or (not membership and "Private Steam-Lobby erstellen." or "Aktiven Ladevorgang zuerst beenden."))
    end
    local host_ready = connected and data.ready[data.host_id]
    local guest_ready = connected and data.ready[data.guest_id]
    local choice_block = selected_checkpoint and "Gemeinsames Laden archivierter Spielstände ist noch nicht verfügbar."
        or (not new_game and "Der Host wählt eine Koop-Kampagne.")
        or (new_game and not new_supported and "Neues Spiel erfordert kompatible, vorbereitete Spiele auf beiden PCs.")
    local check = data and data.load_check
    local load_pending = type(check) == "table" and check.phase ~= "failed"
    local load_help
    if load_pending then
        load_help = check.campaign_start and (new_game and "Beide Spiele bereiten die neue Kampagne vor …"
            or "Beide Spiele bereiten den geschützten Start vor …")
            or "Ladeprüfung aktiv. Erst abschließen oder abbrechen."
    elseif type(check) == "table" and check.phase == "failed" then
        load_help = load_failures[check.reason] or "Ladeprüfung fehlgeschlagen. Status beider PCs prüfen."
    end
    label(28, 411, host and "DU · HOST" or "HOST", 0xFFAAA79F, fonts.small)
    label(320, 411, view_state.role == "G" and "DU · GAST" or "GAST", 0xFFAAA79F, fonts.small)
    label(28, 437, host_ready and "Bereit" or "Nicht bereit", host_ready and 0xFFB5C89D or 0xFFE4E0D8)
    label(320, 437, guest_ready and "Bereit" or "Nicht bereit", guest_ready and 0xFFB5C89D or 0xFFE4E0D8)
    local own_ready = host and host_ready or not host and guest_ready
    local can_ready = enabled and connected and (own_ready or (new_game and new_supported and not choice_block))
    local ready_label = campaign_supported and not peer_incompatible and not host and "Für Kampagnenstart bereit" or "Bereit"
    button(481, own_ready and "Bereitschaft zurücknehmen" or ready_label, can_ready, function()
        send(ready_label == "Für Kampagnenstart bereit" and not own_ready and "ready-campaign" or "ready", not own_ready)
    end, lobby_wait or (not connected and "Zuerst die Verbindung zum Mitspieler herstellen.") or choice_block
        or "Host muss einen verfügbaren Spielstand wählen.")
    local start_block = lobby_wait or (not host and "Der Host startet die Kampagne.")
        or (not connected and "Warte auf den Mitspieler und eine aktive Lobby.")
        or (load_pending and load_help)
        or choice_block
        or (not campaign_supported and "Geschützte Kampagne zuerst vorbereiten.")
        or (peer_incompatible and "Geschützten Kampagnenmodus auf beiden PCs prüfen.")
        or (view_state.campaign_start_ready ~= true and
            (not new_game and "Host muss einen verfügbaren Spielstand wählen."
            or not host_ready and "Der Host muss seine Bereitschaft bestätigen."
            or not guest_ready and "Der Gast muss seine Bereitschaft bestätigen."
            or "Gast: Bereitschaft zurücknehmen und für Kampagnenstart bestätigen."))
    local can_start = not start_block
    local start_label = view_state.role == "G" and "Warten auf Host" or "Spiel starten"
    local solo_available = host and not selected_checkpoint and membership and view_state.connected == false and campaign_supported and in_title_menu()
    if solo_available then
        button(533, "Solotest starten (Leon A, Normal)", not waiting and not solo_request, function()
            local ok, simulator = pcall(require, "re2_coop.cutscene_test_peer")
            if not ok then local_error="Solotest-Modul fehlt. Test-ZIP prüfen."; return end
            local sent,result=simulator.request_start(view_state)
            if sent then
                solo_request={id=result,sent=os.time()}
                visible,local_error,solo_block=false,nil,nil
            else local_error=start_errors[result] or "Solostart konnte nicht vorbereitet werden." end
        end, waiting or solo_block or "RE2 prüft den Solostart.")
    else
        button(533, start_label, can_start, function() send("start-campaign", true) end, start_block)
    end
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
    end
    local setup_error = ui_error(view_state.campaign_setup_error)
    local bridge_error = ui_error(view_state.error)
    label(28, 690, waiting or
        local_error or
        bridge_error or load_help or (connected and choice_block) or
        (peer_incompatible and "Geschützten Kampagnenmodus auf beiden PCs prüfen.") or
        (view_state.campaign_setup_status == "failed" and
            (setup_error or "Vorbereitung fehlgeschlagen. Erneut versuchen.")) or
        (solo_available and "Solotest: Im freien Spiel schaltet F5 die Gastfigur ein oder aus.") or
        start_block or "", 0xFF9BA8D0, fonts.small)
    if bridge_error or setup_error then disabled_hint(bridge_error or setup_error) end
    button(722, "Zurück", true, function()
        visible = false
    end)
    label(28, 773, "Pfeile: Navigieren / Auswählen    Eingabe: Bestätigen", 0xFFAAA79F, fonts.small)
    finish()
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
