-- Opt-in remote-pose diagnostic using assets from the installed game.
if reframework:get_game_name() ~= "re2" or sdk.get_tdb_version() ~= 70 then return end

local filename = "re2_coop_guest_pose.json"
local expected_remote_clip = "pl00_0160_OFF_Gazing_Idle_F_Loop"
local bank_id, motion_id = 1000, 160
local clip_name = "pl00_0160_KFF_Gazing_Idle_F_Loop"
local common = "SectionRoot/Animation/Player/common/pl_common"
local leon = "SectionRoot/Character/Player/pl0000/pl0001/pl0001"
local object_type = sdk.find_type_definition("via.GameObject")
local create = object_type and object_type:get_method("create(System.String)")
local destroy = object_type and object_type:get_method("destroy(via.GameObject)")
local scene_type = sdk.find_type_definition("via.SceneManager")
local phase, status, updates = "idle", "Ready", 0
local actor, renderer, motion, layer, resources
local player_address, scene_address, deadline, first_frame
local remote_session, remote_player, remote_sequence
local last_remote

local function remote_pose()
    local contents = fs.read(filename)
    if type(contents) ~= "string" or contents == "" or #contents > 4096 then return nil end
    local data = json.load_string(contents)
    if type(data) ~= "table" or data.schema ~= 1 or data.connected ~= true
        or data.player_id ~= "leon" or type(data.session_id) ~= "string" or data.session_id == ""
        or type(data.sequence) ~= "number" or data.sequence < 0
        or data.sequence > 9007199254740991 or data.sequence % 1 ~= 0
        or type(data.written_at) ~= "number" or os.time() - data.written_at < 0
        or os.time() - data.written_at > 5
        or (data.observed_at ~= nil and (type(data.observed_at) ~= "number"
            or os.time() - data.observed_at < 0 or os.time() - data.observed_at > 5))
        or type(data.pose) ~= "table" then return nil end
    local position, rotation, selected = data.pose.position, data.pose.rotation, data.pose.motion
    if type(position) ~= "table" or #position ~= 3 or type(rotation) ~= "table" or #rotation ~= 4
        or type(selected) ~= "table" or selected.bank ~= 1 or selected.id ~= motion_id
        or selected.name ~= expected_remote_clip or type(selected.frame) ~= "number"
        or type(selected.end_frame) ~= "number" or selected.frame < 0
        or selected.frame >= math.huge or selected.end_frame <= 0
        or selected.end_frame >= math.huge or selected.frame > selected.end_frame then return nil end
    for _, value in ipairs(position) do
        if type(value) ~= "number" or value <= -math.huge or value >= math.huge then return nil end
    end
    local norm = 0
    for _, value in ipairs(rotation) do
        if type(value) ~= "number" or value <= -math.huge or value >= math.huge then return nil end
        norm = norm + value * value
    end
    if norm <= 0 or norm >= math.huge then return nil end
    return {position = {position[1], position[2], position[3]},
        rotation = {rotation[1], rotation[2], rotation[3], rotation[4]}, session = data.session_id,
        player = data.player_id, sequence = data.sequence}
end

local function same_remote(a, b)
    if a == nil then return false end
    for i = 1, 3 do if a.position[i] ~= b.position[i] then return false end end
    for i = 1, 4 do if a.rotation[i] ~= b.rotation[i] then return false end end
    return true
end

local function report(message)
    status = message
    log.info("RE2_COOP_MOTION_PLAYBACK " .. message)
end

local function remove_actor()
    if actor ~= nil and sdk.is_managed_object(actor) then
        destroy:call(nil, actor)
    end
    actor, renderer, motion, layer, resources = nil, nil, nil, nil, nil
    remote_session, remote_player, remote_sequence, last_remote = nil, nil, nil, nil
    phase = "idle"
end

local function finish(message)
    local ok, err = pcall(remove_actor)
    if ok then
        report(message)
    else
        phase = "cleanup"
        report("cleanup failed " .. tostring(err))
    end
end

local function holder(resource_type, path)
    local resource = assert(sdk.create_resource(resource_type, path), "resource unavailable " .. path)
    return assert(resource:create_holder_global(resource_type .. "Holder"), "holder unavailable " .. path)
end

local function managed_instance(name)
    local instance = assert(sdk.create_instance(name), "allocation failed " .. name)
    -- The RE2 TDB 70 layer disappears after attachment without this initializer.
    if name == "via.motion.TreeLayer" then
        local constructor = sdk.find_type_definition(name):get_method(".ctor()")
        if constructor ~= nil then constructor:call(instance) end
    end
    return instance
end

local function place_actor(remote)
    local transform = assert(actor:call("get_Transform"), "test transform unavailable")
    local p, q = remote.position, remote.rotation
    transform:set_position(Vector4f.new(p[1], p[2], p[3], 1), false)
    transform:set_rotation(Quaternion.new(q[4], q[1], q[2], q[3]))
end

local function create_actor(remote)
    assert(create and create:is_static() and destroy and destroy:is_static(), "GameObject API unavailable")
    resources = {
        mesh = holder("via.render.MeshResource", leon .. ".mesh"),
        material = holder("via.render.MeshMaterialResource", leon .. ".mdf2"),
        common_bank = holder("via.motion.MotionBankResource", common .. ".motbank"),
        joint_map = holder("via.motion.JointMapResource", common .. ".jmap"),
        dynamic_bank = holder("via.motion.MotionBankResource", "SectionRoot/Animation/Player/pl00/bank/BareHand.motbank"),
    }
    actor = assert(create:call(nil, "RE2CoopMotionPlaybackTest"), "test object unavailable")
    place_actor(remote)

    renderer = assert(actor:call("createComponent(System.Type)", sdk.typeof("via.render.Mesh")))
    renderer:call("setMesh(via.render.MeshResourceHolder)", resources.mesh)
    renderer:call("set_Material(via.render.MeshMaterialResourceHolder)", resources.material)

    motion = assert(actor:call("createComponent(System.Type)", sdk.typeof("via.motion.Motion")))
    motion:call("set_JointMap", resources.joint_map)
    motion:call("set_TargetBankType", 31)
    motion:call("set_MotionBankAsset", resources.common_bank)
    local dynamic_bank = managed_instance("via.motion.DynamicMotionBank")
    dynamic_bank:call("set_MotionBank", resources.dynamic_bank)
    motion:call("setDynamicMotionBankCount(System.Int32)", 1)
    motion:call("setDynamicMotionBank(System.Int32, via.motion.DynamicMotionBank)", 0, dynamic_bank)
    motion:call("setupMotionBank()")
    motion:call("setLayerCount(System.UInt32)", 1)
    if motion:call("getLayer(System.UInt32)", 0) == nil then
        motion:call("setLayer(System.UInt32, via.motion.TreeLayer)", 0, managed_instance("via.motion.TreeLayer"))
    end
    phase = "initialize"
    deadline = os.time() + 10
end

local function start_clip()
    -- A holder can exist before its bank is registered in the current scene.
    motion:call("setupMotionBank()")
    if not motion:call("findMotionBank(System.UInt32)", bank_id) then return end
    if not renderer:call("get_MeshReady") or not motion:call("get_JointsConstructed") then return end
    assert(renderer:call("get_SkinningMesh"), "test mesh cannot be skinned")
    layer = assert(motion:call("getLayer(System.UInt32)", 0), "test layer unavailable")
    layer:call("set_LocalBankType", -1)
    layer:call("set_BlendRate", 1.0)
    layer:call("set_Speed", 1.0)
    layer:call("setup()")
    layer:call("changeMotion(System.UInt32, System.UInt32, System.Single)", bank_id, motion_id, 0.0)
    first_frame = nil
    phase = "verify"
end

local function verify_clip()
    local node = layer:call("get_HighestWeightMotionNode")
    local end_frame = layer:call("get_EndFrame")
    if node == nil or end_frame == 0 then return end
    assert(layer:call("get_MotionBankID") == bank_id and layer:call("get_MotionID") == motion_id
        and node:call("get_MotionName") == clip_name, "clip mismatch")
    local frame = layer:call("get_Frame")
    assert(type(frame) == "number" and frame >= 0 and frame <= end_frame
        and end_frame < math.huge, "invalid frame readback")
    if first_frame == nil then
        first_frame = frame
    elseif frame > first_frame then
        report(("verified bank=%d motion=%d name=%s frames=%.3f..%.3f end_frame=%.3f"):format(
            bank_id, motion_id, clip_name, first_frame, frame, end_frame))
        status = ("Playback verified at frame %.1f"):format(frame)
        phase = "observe"
        deadline = os.time() + 20
    end
end

local function tick(sample_due)
    if phase == "cleanup" then
        if sample_due then
            remove_actor()
            report("removed test object")
        end
        return
    end
    local manager = sdk.get_managed_singleton(sdk.game_namespace("PlayerManager"))
    local player = manager and manager:call("get_CurrentPlayer")
    local scene_manager = sdk.get_native_singleton("via.SceneManager")
    local scene = scene_manager and scene_type and sdk.call_native_func(scene_manager, scene_type, "get_CurrentScene")
    assert(player ~= nil and scene ~= nil, "load a campaign first")
    if phase == "start" then
        if not sample_due then return end
        local remote = remote_pose()
        if remote == nil then return end
        player_address, scene_address = player:get_address(), scene:get_address()
        remote_session, remote_player, remote_sequence = remote.session, remote.player, remote.sequence
        last_remote = remote
        create_actor(remote)
        return
    end
    assert(player:get_address() == player_address and scene:get_address() == scene_address, "campaign changed")
    local remote = remote_pose()
    if remote == nil then error("remote pose or supported clip expired") end
    if remote.session ~= remote_session or remote.player ~= remote_player
        or remote.sequence < remote_sequence then error("remote session changed") end
    if remote.sequence == remote_sequence and not same_remote(last_remote, remote) then
        error("remote pose changed without a new sequence")
    end
    if remote.sequence ~= remote_sequence then
        place_actor(remote)
        remote_sequence = remote.sequence
        last_remote = remote
    end
    if os.time() >= deadline then
        if phase == "observe" then finish("removed test object"); return end
        error("timed out waiting for clip playback")
    end
    if not sample_due then return end
    assert(sdk.is_managed_object(actor), "test object unavailable")
    if phase == "initialize" then
        start_clip()
    elseif phase == "verify" then
        verify_clip()
    end
end

re.on_pre_application_entry("UpdateBehavior", function()
    if phase == "idle" then return end
    updates = updates + 1
    local ok, err = pcall(tick, updates % 60 == 0)
    if not ok then finish("failed " .. tostring(err)) end
end)

re.on_draw_ui(function()
    if not imgui.tree_node("RE2 Coop - motion playback") then return end
    if phase == "idle" and imgui.button("Render verified remote Leon idle") then
        phase, status, updates = "start", "Starting", 0
    end
    imgui.text(status)
    imgui.tree_pop()
end)

re.on_script_reset(function()
    if actor ~= nil then finish("removed test object on script reset") end
end)

