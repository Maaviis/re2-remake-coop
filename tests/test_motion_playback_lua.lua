local callback, reset, ui, messages, actor, layer
local now, clicked, destroyed, frame = 100, false, 0, 0
local bank, clip, playback_name = 1000, 160, "pl00_0160_KFF_Gazing_Idle_F_Loop"
local requested = false
local mesh = { call = function(_, name)
    if name == "get_MeshReady" or name == "get_SkinningMesh" then return true end
end }
local motion = { call = function(_, name)
    if name == "findMotionBank(System.UInt32)" then return {} end
    if name == "get_JointsConstructed" then return true end
    if name == "getLayer(System.UInt32)" then return layer end
end }
local transform = {
    get_position = function() return { x = 0, y = 0, z = 0 } end,
    get_rotation = function() return { x = 0, y = 0, z = 0, w = 1 } end,
    set_position = function() end,
}
layer = { call = function(_, name, ...)
    if name == "changeMotion(System.UInt32, System.UInt32, System.Single)" then
        local requested_bank, requested_clip, start = ...
        assert(requested_bank == bank and requested_clip == clip and start == 0)
        requested = true
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
    return player
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

assert(loadfile("reframework/autorun/re2_coop_motion_playback.lua"))()
update()
assert(not requested and destroyed == 0, "the probe must be opt-in")
clicked = true
ui()
update()
assert(not requested, "wait for a separate engine update after allocation")
update()
assert(requested, "request the fixed stock clip")
update()
assert(not logged(" verified "), "matching IDs and a stationary frame are insufficient")
frame = 12
update()
assert(logged(" verified "), "a matching clip with a moving frame verifies playback")
now = now + 21
update()
assert(destroyed == 1, "the verified object must expire")
reset()
assert(destroyed == 1, "reset must not destroy the object twice")

clicked = true
ui()
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
print("Motion playback lifecycle passed")
