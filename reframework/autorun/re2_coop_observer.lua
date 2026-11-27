-- Read-only RE2 player-position observer. Output stays in reframework/data.
-- This does not modify game objects or save files.

local campaign = require("re2_coop.campaign_pose_scope")
local frames = 0
local sequence = 0
local run_id = tostring({})
local last_position = nil
local last_rotation = nil
local last_motion = nil
local last_available = nil
local last_observed_at = nil
local last_campaign_context = nil
local releases = campaign.release_history()
local waiting_for_area = false
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

local function read_motion(player, scoped)
    if sdk.get_tdb_version() ~= 70 or motion_type == nil then return nil end
    local component = player:call("getComponent(System.Type)", motion_type)
    if component == nil or component:call("getLayerCount") < 1 then return nil end
    local layer = component:call("getLayer(System.UInt32)", 0)
    if layer == nil then return nil end
    local node = layer:call("get_HighestWeightMotionNode")
    if node == nil then return nil end
    -- The state machine may report a virtual layer bank. Campaign playback resolves the actual clip.
    local source = scoped and node or layer
    local bank, id = source:call("get_MotionBankID"), source:call("get_MotionID")
    local frame, end_frame = source:call("get_Frame"), source:call("get_EndFrame")
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

local function campaign_context(player)
    local read_ok, scope = pcall(campaign.read_release)
    if not read_ok then scope = nil end
    if not last_campaign_context and not scope then return nil, false end
    local scene_ok, scene = pcall(campaign.scene_address)
    local player_address = player and player:get_address()
    if last_campaign_context and ((scene_ok and scene and scene ~= 0 and scene ~= last_campaign_context.scene)
        or (player_address and player_address ~= 0 and player_address ~= last_campaign_context.player)) then
        waiting_for_area = true
    end
    if not scope or not scene_ok or not scene or scene == 0 or not player_address or player_address == 0 then
        return nil, true
    end
    if not releases:allows(scope) then return nil, true end
    local new_release = not releases.current or releases.current.request_id ~= scope.request_id
    if new_release then
        if scene ~= scope.scene_address or player_address ~= scope.player_address then return nil, true end
    end
    if not campaign.peer_matches(scope) then return nil, true end
    local area_ok, area = pcall(campaign.read_area)
    if not area_ok or not area or area.scenario ~= scope.scenario
        or (not new_release and waiting_for_area and campaign.same_area(area, last_campaign_context.area)) then
        return nil, true
    end
    return {release = scope, request_id = scope.request_id, attempt_id = scope.attempt_id, player = player_address,
        scene = scene, area = area}, true
end

local function read_pose()
    local manager = sdk.get_managed_singleton(sdk.game_namespace("PlayerManager"))
    local player = manager and manager:call("get_CurrentPlayer")
    local context, scoped = campaign_context(player)
    if player == nil or (scoped and context == nil) then return end
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
    local motion_ok, motion = pcall(read_motion, player, context ~= nil)
    if context then
        local area_ok, area = pcall(campaign.read_area)
        local scene_ok, scene = pcall(campaign.scene_address)
        local current = manager:call("get_CurrentPlayer")
        if not area_ok or not campaign.same_area(area, context.area) or not scene_ok or scene ~= context.scene
            or not current or current:get_address() ~= context.player then return end
    end
    return xyz, quaternion, unit, motion_ok and motion or nil, context
end

local function observe()
    if reframework:get_game_name() ~= "re2" then return end
    local now = os.time()
    local xyz, quaternion, unit, motion, context = read_pose()
    local attempt, area = context and context.attempt_id, context and context.area
    local available = xyz ~= nil
    if not available and last_available == false then return end
    if available and last_position ~= nil and now == last_observed_at then
        local dx, dy, dz = xyz[1] - last_position[1], xyz[2] - last_position[2], xyz[3] - last_position[3]
        local dot = 0
        for i = 1, 4 do dot = dot + unit[i] * last_rotation[i] end
        -- Opposite quaternion signs encode the same orientation.
        local same_context = (not context and not last_campaign_context)
            or (context and last_campaign_context and context.request_id == last_campaign_context.request_id
                and campaign.same_area(area, last_campaign_context.area))
        if same_context
            and dx * dx + dy * dy + dz * dz < 0.0001 and math.abs(dot) > rotation_threshold
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
        campaign_attempt_id = attempt,
        campaign_area = area,
        campaign_local_context = context and {request_id = context.request_id,
            player = tostring(context.player), scene = tostring(context.scene)},
    }
    local encoded = json.dump_string(sample)
    if type(encoded) ~= "string" or encoded == "" then error("could not encode player sample") end
    write_sample(encoded)
    if context then
        releases:adopt(context.release)
        last_campaign_context, waiting_for_area = context, false
    end
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
