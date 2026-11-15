-- Read-only campaign animation probe for RE2's TDB 70 runtime.
if reframework:get_game_name() ~= "re2" or sdk.get_tdb_version() ~= 70 then return end

local motion_type = sdk.typeof("via.motion.Motion")
local layer_index = 0
local updates = 0
local last_status, last_source, last_clip, last_frame, frame_change_logged

local function finite(value)
    return type(value) == "number" and value > -math.huge and value < math.huge
end

local function read_layer()
    if motion_type == nil then return nil, "motion type missing" end
    local manager = sdk.get_managed_singleton(sdk.game_namespace("PlayerManager"))
    local player = manager and manager:call("get_CurrentPlayer")
    if player == nil then return nil, "no current player" end

    local motion = player:call("getComponent(System.Type)", motion_type)
    if motion == nil or motion:call("getLayerCount") <= layer_index then
        return nil, "motion layer missing"
    end
    local layer = motion:call("getLayer(System.UInt32)", layer_index)
    if layer == nil then return nil, "motion layer missing" end

    local bank_id = layer:call("get_MotionBankID")
    local motion_id = layer:call("get_MotionID")
    local frame = layer:call("get_Frame")
    local end_frame = layer:call("get_EndFrame")
    if not (finite(bank_id) and finite(motion_id) and finite(frame) and finite(end_frame)) then
        return nil, "invalid layer values"
    end
    local source = ("%s:%s"):format(player:get_address(), layer:get_address())
    local clip = ("layer=%d bank=%d motion=%d"):format(layer_index, bank_id, motion_id)
    return clip, frame, end_frame, source
end

re.on_pre_application_entry("UpdateBehavior", function()
    updates = updates + 1
    if updates % 6 ~= 0 then return end

    local ok, clip, frame, end_frame, source = pcall(read_layer)
    if not ok or clip == nil then
        local status = ok and frame or tostring(clip)
        if status ~= last_status then
            log.info("RE2_COOP_MOTION unavailable " .. status)
        end
        last_status, last_source = status, nil
        return
    end

    last_status = nil
    if source ~= last_source or clip ~= last_clip then
        log.info(("RE2_COOP_MOTION clip %s frame=%.3f end_frame=%.3f"):format(clip, frame, end_frame))
        last_source, last_clip, last_frame, frame_change_logged = source, clip, frame, false
    elseif not frame_change_logged and frame ~= last_frame then
        log.info(("RE2_COOP_MOTION frame_changed %s from=%.3f to=%.3f"):format(clip, last_frame, frame))
        frame_change_logged = true
    end
end)

log.info("RE2_COOP_MOTION loaded tdb=70 layer=0")
