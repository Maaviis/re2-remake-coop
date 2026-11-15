-- Lobby front end. All authoritative changes go through the Python bridge.
if reframework:get_game_name() ~= "re2" then return end

local status, local_error, last_poll, last_view_id
local visible = true
local font_cache, draft_key, slot = {}, nil, ""
local campaign, difficulty = 1, 1
local campaign_labels = { "Nicht festgelegt", "Leon", "Claire" }
local campaign_values = { false, "leon", "claire" }
local difficulty_labels = { "Nicht festgelegt", "Assistiert", "Standard", "Hardcore" }
local difficulty_values = { false, "assisted", "standard", "hardcore" }
local command_number, pending_until = 0, 0
local last_report
local input = require('re2_coop.lobby_input').new()
local toggle_down = false
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

local function send(action, value)
    if not status or not fresh(status.written_at) or not status.lobby then return end
    if action ~= "ready" and status.role ~= "H" then return end
    if action == "ready" and not status.connected then return end
    if os.time() < pending_until then return end
    command_number = command_number + 1
    local command = { id = string.format("lobby-ui-%d-%d-%.6f", os.time(), command_number, os.clock()),
        written_at = os.time(), session_id = status.lobby.session_id,
        revision = status.lobby.data.revision, action = action, value = value }
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

local function render()
    poll()
    local down = reframework:is_key_down(0x78) -- F9
    if down and not toggle_down and status then visible = not visible end
    toggle_down = down
    if not visible or not status or not seen_live then input:frame(false); return end
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
    imgui.begin_window("RE2 Coop Lobby", nil, 1 | 2 | 4 | 32 | 256 | 4096)
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
    local live = fresh(status.written_at)
    local message = status.lobby
    local data = message and message.data
    local connected = live and status.connected and data and data.connected
    local host = status.role == "H"
    local enabled = live and data ~= nil and os.time() >= pending_until
    local native = data and data.save_ref ~= nil
    local save_available = not native or data.save_ref.available
    local local_save_missing = connected and native and not host and save_available and status.local_save_matches ~= true
    local catalog = host and status.catalog
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
    label(390, 103, "F9: Lobby schließen", 0xFFAAA79F, fonts.small)
    label(28, 131, connected and "Mit Spieler verbunden" or live and "Warten auf einen Spieler" or "Verbindung unterbrochen")
    label(28, 167, host and "DU BIST HOST" or "DU BIST GAST", 0xFFAAA79F, fonts.small)
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
    label(28, 411, host and "DU · HOST" or "HOST", 0xFFAAA79F, fonts.small)
    label(320, 411, not host and "DU · GAST" or "GAST", 0xFFAAA79F, fonts.small)
    label(28, 437, host_ready and "Bereit" or "Nicht bereit", host_ready and 0xFFB5C89D or 0xFFE4E0D8)
    label(320, 437, guest_ready and "Bereit" or "Nicht bereit", guest_ready and 0xFFB5C89D or 0xFFE4E0D8)
    local own_ready = host and host_ready or not host and guest_ready
    local can_ready = enabled and connected and (own_ready or save_available and not local_save_missing)
    button(481, own_ready and "Bereitschaft zurücknehmen" or "Bereit", can_ready, function()
        send("ready", not own_ready)
    end)
    button(533, "Spieler über Steam einladen", enabled and host, function() send("invite", true) end)
    label(28, 602, os.time() < pending_until and "Anfrage wird verarbeitet …" or
        local_error or (local_save_missing and "Passender lokaler Spielstand erforderlich.") or
        (status.error and "Anfrage abgelehnt. Lobby im Terminal prüfen.") or "", 0xFF9BA8D0, fonts.small)
    label(28, 640, "ENTWICKLUNGSFASSUNG", 0xFFAAA79F, fonts.small)
    label(28, 665, "Auswahl und Bereitschaft werden geteilt.", 0xFFAAA79F, fonts.small)
    label(28, 688, "Spielstandladen und Kampagnenstart folgen.", 0xFFAAA79F, fonts.small)
    imgui.end_window()
    imgui.pop_style_color(7)
    local report = string.format("role=%s connected=%s revision=%s fresh=%s", status.role,
        tostring(not not connected), tostring(data and data.revision or "none"), tostring(live))
    if report ~= last_report then
        log.info("RE2_COOP_LOBBY_VIEW " .. report .. string.format(" display=%.0fx%.0f", screen.x, screen.y))
        last_report = report
    end
end

re.on_frame(render)
