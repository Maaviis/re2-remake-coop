local callback, reset, ui, messages, actor, layer
local now, clicked, destroyed, frame = 100, false, 0, 0
local command_data, player_present
player_present = true
local bank, clip, playback_name = 1000, 160, "pl00_0160_KFF_Gazing_Idle_F_Loop"
local requested, bank_ready = false, false
local remote_data = {
    schema = 1, connected = true, player_id = "leon", session_id = "session-1",
    sequence = 1, written_at = 100, observed_at = 100,
    pose = {position = {2, 0, 3}, rotation = {0, 0, 0, 1},
        motion = {bank = 1, id = 160, name = "pl00_0160_OFF_Gazing_Idle_F_Loop",
            frame = 10, end_frame = 1100}},
}
local applied_position
local mesh = { call = function(_, name)
    if name == "get_MeshReady" or name == "get_SkinningMesh" then return true end
end }
local motion = { call = function(_, name)
    if name == "findMotionBank(System.UInt32)" then return bank_ready and {} or nil end
    if name == "get_JointsConstructed" then return true end
    if name == "getLayer(System.UInt32)" then return layer end
end }
local transform = {
    get_position = function() return { x = 0, y = 0, z = 0 } end,
    get_rotation = function() return { x = 0, y = 0, z = 0, w = 1 } end,
    set_position = function(_, value) applied_position = value end,
    set_rotation = function() end,
}
layer = { call = function(_, name, ...)
    if name == "changeMotion(System.UInt32, System.UInt32, System.Single)" then
        local requested_bank, requested_clip, start = ...
        assert(requested_bank == bank and requested_clip == clip and start == 0)
        requested = true
    elseif name == "set_Frame(System.Single)" then
        frame = (...)
    elseif name == "get_MotionBankID" then return bank
    elseif name == "get_MotionID" then return clip
    elseif name == "get_Frame" then return frame
    elseif name == "get_EndFrame" then return 1100
    elseif name == "get_HighestWeightMotionNode" then
        return { call = function(_, method)
            assert(method == "get_MotionName")
            return playback_name
        end }
    end
end }
actor = { call = function(_, name, value)
    if name == "get_Transform" then return transform end
    assert(name == "createComponent(System.Type)")
    return value == "via.render.Mesh" and mesh or motion
end }
local player = { get_address = function() return 101 end,
    call = function(_, name) assert(name == "get_Transform"); return transform end }
local manager = { call = function(_, name)
    assert(name == "get_CurrentPlayer")
    return player_present and player or nil
end }
local camera_object = { call = function() return transform end }
local camera = { call = function() return camera_object end }
local scene_address = 102
local scene = { get_address = function() return scene_address end }
local game_type = { get_method = function(_, name)
    return {
        is_static = function() return true end,
        call = function()
            if name == "create(System.String)" then return actor end
            assert(name == "destroy(via.GameObject)")
            destroyed = destroyed + 1
        end,
    }
end }
reframework = { get_game_name = function() return "re2" end }
re = {
    on_pre_application_entry = function(_, fn) callback = fn end,
    on_script_reset = function(fn) reset = fn end,
    on_draw_ui = function(fn) ui = fn end,
}
imgui = {
    tree_node = function() return true end,
    tree_pop = function() end,
    text = function() end,
    button = function()
        local value = clicked
        clicked = false
        return value
    end,
}
sdk = {
    get_tdb_version = function() return 70 end,
    get_managed_singleton = function() return manager end,
    get_native_singleton = function() return {} end,
    call_native_func = function() return scene end,
    game_namespace = function(name) return name end,
    find_type_definition = function(name)
        if name == "via.GameObject" then return game_type end
        if name == "via.SceneManager" then return {} end
        if name == "via.motion.TreeLayer" then return { get_method = function() end } end
        error("unexpected type lookup " .. name)
    end,
    get_primary_camera = function() return camera end,
    typeof = function(name) return name end,
    is_managed_object = function(object) return object == actor end,
    create_instance = function(name)
        if name == "via.motion.TreeLayer" then return layer end
        return { call = function() end }
    end,
    create_resource = function()
        return { create_holder_global = function() return {} end }
    end,
}
Vector4f = { new = function(x, y, z, w) return {x=x, y=y, z=z, w=w} end }
Quaternion = { new = function(w, x, y, z) return {w=w, x=x, y=y, z=z} end }
fs = { read = function(name)
    if name == "re2_coop_guest_pose.json" then return "sample" end
    assert(name == "re2_coop_motion_command.json")
    return command_data and "command" or nil
end }
json = { load_string = function(contents)
    return contents == "command" and command_data or remote_data
end }
messages = {}
log = { info = function(message) messages[#messages + 1] = message end }
os.time = function() return now end

local function update()
    for _ = 1, 60 do callback() end
end
local function logged(pattern)
    for _, message in ipairs(messages) do
        if message:match(pattern) then return true end
    end
    return false
end

assert(loadfile("reframework/autorun/re2_coop_remote_motion.lua"))()
update()
assert(not requested and destroyed == 0, "the probe must be opt-in")
clicked = true
ui()
update()
assert(not requested, "wait for a separate engine update after allocation")
assert(applied_position.x == 2 and applied_position.z == 3, "use the verified remote position")
update()
assert(not requested and destroyed == 0, "wait while the motion bank is unavailable")
bank_ready = true
update()
assert(requested, "request the fixed stock clip")
update()
assert(not logged(" verified "), "matching IDs and a stationary frame are insufficient")
assert(frame == 10 and logged("phase aligned"), "seek to the remote clip phase")
frame = 12
update()
assert(logged(" verified "), "a matching clip with a moving frame verifies playback")
remote_data.sequence = 2
remote_data.pose.motion.frame = 550
update()
assert(frame == 550, "correct a large phase drift on a new host sequence")
remote_data.sequence = 1
update()
assert(destroyed == 1 and logged("remote session changed"), "reject a sequence rollback")
now = now + 21
update()
assert(destroyed == 1, "the verified object must be removed")
reset()
assert(destroyed == 1, "reset must not destroy the object twice")

clicked = true
ui()
remote_data.written_at, remote_data.observed_at = now, now
remote_data.sequence = 3
update()
update()
playback_name = "different_variant"
update()
assert(destroyed == 2 and logged("clip mismatch"), "a different resource at the same IDs must be rejected")
playback_name = "pl00_0160_KFF_Gazing_Idle_F_Loop"
clicked = true
ui()
update()
scene_address = 103
callback()
assert(destroyed == 3 and logged("campaign changed"), "scene loss must tear down the object at the next update")
clicked = true
ui()
update()
reset()
assert(destroyed == 4, "reset while active must destroy the owned object")
clicked = true
ui()
update()
remote_data.pose.position[1] = 5
callback()
assert(destroyed == 5 and logged("without a new sequence"),
    "a changed pose at the same verified sequence must remove the actor")
command_data = {schema = 1, action = "start", nonce = "stale-command-0001", issued_at = now - 6}
update()
assert(destroyed == 5, "a stale terminal command must be ignored")
command_data = {schema = 1, action = "start", nonce = "fresh-command-0001", issued_at = now}
player_present = false
update()
assert(logged("started by terminal command") and destroyed == 5,
    "a fresh terminal command waits for the campaign")
player_present = true
remote_data.sequence = 4
remote_data.written_at, remote_data.observed_at = now, now
update()
command_data = {schema = 1, action = "stop", nonce = "fresh-command-0002", issued_at = now}
update()
assert(destroyed == 6 and logged("stopped by terminal command"),
    "a terminal stop must remove the owned actor")
update()
assert(destroyed == 6, "one terminal command must be consumed only once")
print("Motion playback lifecycle passed")
