-- Read-only RE2 player-position observer. Output stays in reframework/data.
-- This does not modify game objects or save files.

local frames = 0
local sequence = 0
local last_position = nil
local output = "re2_coop_observer.json"

local function observe()
    if reframework:get_game_name() ~= "re2" then return end
    local manager = sdk.get_managed_singleton(sdk.game_namespace("PlayerManager"))
    if manager == nil then return end
    local player = manager:call("get_CurrentPlayer")
    if player == nil then return end
    local transform = player:call("get_Transform")
    if transform == nil then return end
    local position = transform:get_position()
    local rotation = transform:get_rotation()
    if position == nil or rotation == nil then return end

    local xyz = { position.x, position.y, position.z }
    if last_position ~= nil then
        local dx, dy, dz = xyz[1] - last_position[1], xyz[2] - last_position[2], xyz[3] - last_position[3]
        if dx * dx + dy * dy + dz * dz < 0.0001 then return end
    end
    last_position = xyz
    sequence = sequence + 1
    local sample = {
        schema = 1,
        source = "re2",
        tdb = sdk.get_tdb_version(),
        sequence = sequence,
        position = xyz,
        rotation = { rotation.x, rotation.y, rotation.z, rotation.w },
    }
    local encoded = json.dump_string(sample)
    if encoded ~= "" then fs.write(output, encoded) end
end

re.on_pre_application_entry("UpdateBehavior", function()
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local ok, err = pcall(observe)
    if not ok then log.info("RE2_COOP_OBSERVER error: " .. tostring(err)) end
end)

log.info("RE2_COOP_OBSERVER loaded; output=reframework/data/" .. output)

