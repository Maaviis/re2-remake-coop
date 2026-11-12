-- Read-only RE2 player-position observer. Output stays in reframework/data.
-- This does not modify game objects or save files.

local frames = 0
local sequence = 0
local run_id = tostring({})
local last_position = nil
local last_rotation = nil
local output = "re2_coop_observer.json"
local rotation_threshold = math.cos(math.rad(0.5) / 2)

local function finite(value)
    return type(value) == "number" and value > -math.huge and value < math.huge
end

local function unit_rotation(quaternion)
    local squared_length = 0
    for i = 1, 4 do
        if not finite(quaternion[i]) then return nil end
        squared_length = squared_length + quaternion[i]^2
    end
    if not finite(squared_length) or squared_length == 0 then return nil end
    local length = math.sqrt(squared_length)
    return { quaternion[1] / length, quaternion[2] / length,
        quaternion[3] / length, quaternion[4] / length }
end

local function write_sample(data)
    -- REFramework resolves relative io.open paths under reframework/data.
    local file = assert(io.open(output, "wb"), "could not open player sample")
    local written, write_error = file:write(data)
    local closed, close_error = file:close()
    if not written or not closed then
        error(write_error or close_error or "could not write player sample")
    end
end

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
    if not (finite(xyz[1]) and finite(xyz[2]) and finite(xyz[3])) then return end
    local quaternion = { rotation.x, rotation.y, rotation.z, rotation.w }
    local unit = unit_rotation(quaternion)
    if unit == nil then return end

    if last_position ~= nil then
        local dx, dy, dz = xyz[1] - last_position[1], xyz[2] - last_position[2], xyz[3] - last_position[3]
        local dot = 0
        for i = 1, 4 do dot = dot + unit[i] * last_rotation[i] end
        -- Opposite quaternion signs encode the same orientation.
        if dx * dx + dy * dy + dz * dz < 0.0001 and math.abs(dot) > rotation_threshold then return end
    end

    local sample = {
        schema = 1,
        source = "re2",
        run_id = run_id,
        tdb = sdk.get_tdb_version(),
        sequence = sequence + 1,
        position = xyz,
        rotation = quaternion,
    }
    local encoded = json.dump_string(sample)
    if type(encoded) ~= "string" or encoded == "" then error("could not encode player sample") end
    write_sample(encoded)
    last_position, last_rotation = xyz, unit
    sequence = sample.sequence
end

re.on_pre_application_entry("UpdateBehavior", function()
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local ok, err = pcall(observe)
    if not ok then log.info("RE2_COOP_OBSERVER error: " .. tostring(err)) end
end)

log.info("RE2_COOP_OBSERVER loaded; output=reframework/data/" .. output)
