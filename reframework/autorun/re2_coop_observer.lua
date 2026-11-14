-- Read-only RE2 player-position observer. Output stays in reframework/data.
-- This does not modify game objects or save files.

local frames = 0
local sequence = 0
local run_id = tostring({})
local last_position = nil
local last_rotation = nil
local last_motion = nil
local last_available = nil
local last_observed_at = nil
local output = "re2_coop_observer.json"
local rotation_threshold = math.cos(math.rad(0.5) / 2)
local motion_type = sdk.typeof("via.motion.Motion")

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

local function read_motion(player)
    if sdk.get_tdb_version() ~= 70 or motion_type == nil then return nil end
    local component = player:call("getComponent(System.Type)", motion_type)
    if component == nil or component:call("getLayerCount") < 1 then return nil end
    local layer = component:call("getLayer(System.UInt32)", 0)
    if layer == nil then return nil end
    local node = layer:call("get_HighestWeightMotionNode")
    if node == nil then return nil end
    local bank, id = layer:call("get_MotionBankID"), layer:call("get_MotionID")
    local frame, end_frame = layer:call("get_Frame"), layer:call("get_EndFrame")
    local name = node:call("get_MotionName")
    if not (finite(bank) and bank >= 0 and bank == math.floor(bank)
        and finite(id) and id >= 0 and id == math.floor(id)
        and finite(frame) and frame >= 0 and finite(end_frame) and end_frame > 0
        and frame <= end_frame and type(name) == "string" and #name > 0 and #name <= 128
        and not name:find("%c")) then return nil end
    return { bank = bank, id = id, name = name, frame = frame, end_frame = end_frame }
end

local function motion_key(motion)
    if motion == nil then return nil end
    return ("%d:%d:%s:%.6f:%.6f"):format(
        motion.bank, motion.id, motion.name, motion.frame, motion.end_frame)
end

local function read_pose()
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
    local motion_ok, motion = pcall(read_motion, player)
    return xyz, quaternion, unit, motion_ok and motion or nil
end

local function observe()
    if reframework:get_game_name() ~= "re2" then return end
    local now = os.time()
    local xyz, quaternion, unit, motion = read_pose()
    local available = xyz ~= nil
    if not available and last_available == false then return end
    if available and last_position ~= nil and now == last_observed_at then
        local dx, dy, dz = xyz[1] - last_position[1], xyz[2] - last_position[2], xyz[3] - last_position[3]
        local dot = 0
        for i = 1, 4 do dot = dot + unit[i] * last_rotation[i] end
        -- Opposite quaternion signs encode the same orientation.
        if dx * dx + dy * dy + dz * dz < 0.0001 and math.abs(dot) > rotation_threshold
            and motion_key(motion) == last_motion then return end
    end

    local sample = {
        schema = 1,
        source = "re2",
        run_id = run_id,
        tdb = sdk.get_tdb_version(),
        sequence = sequence + 1,
        available = available,
        observed_at = now,
        position = xyz,
        rotation = quaternion,
        motion = motion,
    }
    local encoded = json.dump_string(sample)
    if type(encoded) ~= "string" or encoded == "" then error("could not encode player sample") end
    write_sample(encoded)
    last_position, last_rotation = xyz, unit
    last_motion = motion_key(motion)
    last_available, last_observed_at = available, now
    sequence = sample.sequence
end

re.on_pre_application_entry("UpdateBehavior", function()
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local ok, err = pcall(observe)
    if not ok then log.info("RE2_COOP_OBSERVER error: " .. tostring(err)) end
end)

log.info("RE2_COOP_OBSERVER loaded; output=reframework/data/" .. output)

