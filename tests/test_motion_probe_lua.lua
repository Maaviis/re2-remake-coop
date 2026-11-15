local probe = "reframework/autorun/re2_coop_motion_probe.lua"
local tdb, available, bank, motion, frame = 70, false, 51, 3, 5
local player_address, layer_address, reads = 100, 200, 0
local tick
local messages = {}

reframework = { get_game_name = function() return "re2" end }
sdk = {
    get_tdb_version = function() return tdb end,
    game_namespace = function(name) return "app.ropeway." .. name end,
    typeof = function(name)
        assert(name == "via.motion.Motion")
        return name
    end,
}
re = { on_pre_application_entry = function(name, callback)
    assert(name == "UpdateBehavior")
    tick = callback
end }
log = { info = function(message) messages[#messages + 1] = message end }

local layer = { get_address = function() return layer_address end, call = function(_, name)
    if name == "get_MotionBankID" then return bank end
    if name == "get_MotionID" then return motion end
    if name == "get_Frame" then return frame end
    if name == "get_EndFrame" then return 60 end
    error("unexpected TreeLayer call " .. name)
end }
local component = { call = function(_, name, index)
    if name == "getLayerCount" then return 1 end
    assert(name == "getLayer(System.UInt32)" and index == 0)
    return layer
end }
local player = { get_address = function() return player_address end, call = function(_, name, arg)
    assert(name == "getComponent(System.Type)" and arg == "via.motion.Motion")
    return component
end }
local manager = { call = function(_, name)
    assert(name == "get_CurrentPlayer")
    reads = reads + 1
    if available then return player end
end }
sdk.get_managed_singleton = function(name)
    assert(name == "app.ropeway.PlayerManager")
    return manager
end

assert(loadfile(probe))()
assert(tick, "the RE2 TDB 70 probe must register a game update callback")
local function update()
    for _ = 1, 6 do tick() end
end
local function count(pattern)
    local result = 0
    for _, message in ipairs(messages) do
        if message:match(pattern) then result = result + 1 end
    end
    return result
end

for _ = 1, 5 do tick() end
assert(reads == 0, "the probe must wait five callbacks before sampling")
tick()
assert(reads == 1, "the sixth callback must sample the current player")
assert(count(" unavailable") == 1, "report the menu without a player once")
available = true
update()
assert(count("bank=51 motion=3 frame=5%.000 end_frame=60%.000") == 1, "report the current clip once")
frame = 9
update()
frame = 11
update()
assert(count(" frame_changed ") == 1, "confirm progression once for an unchanged clip")
bank, motion, frame = 52, 7, 1
update()
assert(count("bank=52 motion=7 frame=1%.000") == 1, "report a different clip immediately")
available = false
update()
available = true
update()
assert(count(" unavailable") == 2 and count("bank=52 motion=7 frame=1%.000") == 2,
    "returning to a player must report the current clip again")
player_address, frame = 101, 7
update()
assert(count("clip layer=0 bank=52 motion=7 frame=7%.000") == 1,
    "switching players with identical bank and motion IDs must start a new sample")
layer_address, frame = 201, 4
update()
assert(count("clip layer=0 bank=52 motion=7 frame=4%.000") == 1,
    "switching layers with identical bank and motion IDs must start a new sample")
frame = 1
update()
assert(count(" from=4%.000 to=1%.000") == 1, "a reset or wrap is also a frame change")
frame = 0 / 0
update()
assert(count(" unavailable") == 3, "suppress non-finite frame values")

tdb, tick = 69, nil
assert(loadfile(probe))()
assert(tick == nil, "unsupported builds must not register the native probe")
print("Motion probe lifecycle passed")
