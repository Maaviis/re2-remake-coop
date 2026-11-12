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
}

log.info("RE2_COOP_PROBE script loaded")

local function type_name(object)
    if object == nil then return "unknown" end
    local definition = object:get_type_definition()
    if definition == nil then return "unknown" end
    return tostring(definition:get_full_name())
end

local function inspect()
    status.game = tostring(reframework:get_game_name())
    status.tdb = tostring(sdk.get_tdb_version())
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
    if transform ~= nil then
        local position = transform:get_position()
        local rotation = transform:get_rotation()
        if position ~= nil then
            status.position = string.format("%.3f, %.3f, %.3f", position.x, position.y, position.z)
        end
        if rotation ~= nil then
            status.rotation = string.format("%.3f, %.3f, %.3f, %.3f",
                rotation.x, rotation.y, rotation.z, rotation.w)
        end
    end

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
    if status.logged_player then return end
    local ok, err = pcall(inspect)
    if not ok then
        status.error = tostring(err)
        if not status.error_logged then
            status.error_logged = true
            log.info("RE2_COOP_PROBE error: " .. status.error)
        end
    elseif status.player == "found" then
        status.logged_player = true
        status.error = nil
        log.info("RE2_COOP_PROBE game=" .. status.game .. " tdb=" .. status.tdb
            .. " player=" .. status.player_type .. " position=" .. status.position
            .. " rotation=" .. status.rotation .. " inventory=" .. status.inventory_type)
    end
end)

re.on_draw_ui(function()
    if not imgui.tree_node("RE2 Coop - integration probe") then return end
    if imgui.button("Inspect loaded game") then
        local ok, err = pcall(inspect)
        status.error = ok and nil or tostring(err)
    end
    imgui.text("Game: " .. status.game)
    imgui.text("Type database: " .. status.tdb)
    imgui.text("Player: " .. status.player)
    imgui.text("Player type: " .. status.player_type)
    imgui.text("Player position: " .. status.position)
    imgui.text("Player rotation: " .. status.rotation)
    imgui.text("Inventory: " .. status.inventory)
    imgui.text("Inventory type: " .. status.inventory_type)
    if status.error ~= nil then imgui.text("Probe error: " .. status.error) end
    imgui.tree_pop()
end)
