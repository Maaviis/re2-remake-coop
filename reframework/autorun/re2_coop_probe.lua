-- Read-only RE2 integration probe. Copy into reframework/autorun only after
-- installing a compatible, working REFramework build for this RE2 version.
-- It deliberately does not change game objects or save data.

local status = {
    game = "unknown",
    player = "not found",
    player_type = "unknown",
    position = "unknown",
    rotation = "unknown",
    inventory = "not found",
    inventory_type = "unknown",
    tdb = "unknown",
    error = nil,
    logged_player = false,
    error_logged = false,
    frames = 0,
    samples = 0,
    first_position = nil,
    movement_seen = false,
}

local inspect_requested = false

log.info("RE2_COOP_PROBE script loaded")

local function type_name(object)
    if object == nil then return "unknown" end
    local definition = object:get_type_definition()
    if definition == nil then return "unknown" end
    return tostring(definition:get_full_name())
end

local function finite(value)
    return type(value) == "number" and value > -math.huge and value < math.huge
end

local function record_position(player, position, start)
    if position == nil then return end
    local address = player:get_address()
    if address == nil or address == 0 then return end
    status.samples = status.samples + 1
    if status.movement_seen then return end

    -- This address identifies the object only within the current process.
    if start == nil or start.address ~= address then
        status.first_position = {address = address, x = position.x, y = position.y, z = position.z}
        return
    end

    local dx, dy, dz = position.x - start.x, position.y - start.y, position.z - start.z
    if dx * dx + dy * dy + dz * dz > 0.01 then
        status.movement_seen = true
        log.info("RE2_COOP_PROBE movement observed after " .. status.samples
            .. " samples; position=" .. status.position)
    else
        status.first_position = start
    end
end

local function inspect(scheduled)
    local start = status.first_position
    -- Restore or replace the baseline only after a valid scheduled reading.
    if scheduled then status.first_position = nil end
    status.game = tostring(reframework:get_game_name())
    status.tdb = tostring(sdk.get_tdb_version())
    status.position, status.rotation = "unknown", "unknown"
    if status.game ~= "re2" then
        status.error = "This probe is for Resident Evil 2 Remake only"
        return
    end

    local manager = sdk.get_managed_singleton(sdk.game_namespace("PlayerManager"))
    if manager == nil then
        status.player = "PlayerManager unavailable"
        return
    end
    local player = manager:call("get_CurrentPlayer")
    if player == nil then
        status.player = "no current player (load a campaign save)"
        return
    end
    status.player = "found"
    status.player_type = type_name(player)
    local transform = player:call("get_Transform")
    local position
    if transform ~= nil then
        position = transform:get_position()
        local rotation = transform:get_rotation()
        if position ~= nil and finite(position.x) and finite(position.y) and finite(position.z) then
            status.position = string.format("%.3f, %.3f, %.3f", position.x, position.y, position.z)
        else
            position = nil
        end
        if rotation ~= nil then
            status.rotation = string.format("%.3f, %.3f, %.3f, %.3f",
                rotation.x, rotation.y, rotation.z, rotation.w)
        end
    end
    if scheduled then record_position(player, position, start) end

    local inventory_type = sdk.typeof(sdk.game_namespace("survivor.Inventory"))
    if inventory_type == nil then
        status.inventory = "type unavailable"
        return
    end
    local inventory = player:call("getComponent(System.Type)", inventory_type)
    if inventory ~= nil then
        status.inventory = "found"
        status.inventory_type = type_name(inventory)
    end
end

re.on_pre_application_entry("UpdateBehavior", function()
    status.frames = status.frames + 1
    local scheduled = status.frames % 60 == 0
    if not scheduled and not inspect_requested then return end
    inspect_requested = false
    status.error = nil
    local ok, err = pcall(inspect, scheduled)
    if not ok then
        status.error = tostring(err)
        if not status.error_logged then
            status.error_logged = true
            log.info("RE2_COOP_PROBE error: " .. status.error)
        end
    elseif status.player == "found" and not status.logged_player then
        status.logged_player = true
        log.info("RE2_COOP_PROBE game=" .. status.game .. " tdb=" .. status.tdb
            .. " player=" .. status.player_type .. " position=" .. status.position
            .. " rotation=" .. status.rotation .. " inventory=" .. status.inventory_type)
    end
end)

re.on_draw_ui(function()
    if not imgui.tree_node("RE2 Coop - integration probe") then return end
    if imgui.button("Inspect loaded game") then
        inspect_requested = true
    end
    imgui.text("Game: " .. status.game)
    imgui.text("Type database: " .. status.tdb)
    imgui.text("Player: " .. status.player)
    imgui.text("Player type: " .. status.player_type)
    imgui.text("Player position: " .. status.position)
    imgui.text("Position samples: " .. status.samples)
    imgui.text("Movement observed: " .. tostring(status.movement_seen))
    imgui.text("Player rotation: " .. status.rotation)
    imgui.text("Inventory: " .. status.inventory)
    imgui.text("Inventory type: " .. status.inventory_type)
    if status.error ~= nil then imgui.text("Probe error: " .. status.error) end
    imgui.tree_pop()
end)

