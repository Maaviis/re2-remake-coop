local path = "reframework/autorun/re2_coop_guest_pose.lua"

local function fixture()
    local f = {
        now = 100,
        game = "re2",
        player = true,
        markers = {},
        lines = {},
        document = {
            schema = 1, player_id = "claire", connected = true, written_at = 100,
            session_id = "test", sequence = 1,
            pose = {position = {1, 2, 3}, rotation = {0, 0, 0, 1}},
        },
    }
    local env = setmetatable({
        reframework = {get_game_name = function() return f.game end},
        sdk = {
            game_namespace = function(name) return name end,
            get_managed_singleton = function(name)
                assert(name == "PlayerManager")
                return {call = function(_, method)
                    assert(method == "get_CurrentPlayer")
                    if f.player then return {} end
                end}
            end,
        },
        os = {time = function() return f.now end},
        re = {
            on_pre_application_entry = function(name, callback)
                assert(name == "UpdateBehavior")
                f.update = callback
            end,
            on_frame = function(callback) f.draw = callback end,
        },
        fs = {read = function(filename)
            assert(filename == "re2_coop_guest_pose.json")
            if f.bad_read then error("invalid file") end
            return "fixture"
        end},
        json = {load_string = function(contents)
            assert(contents == "fixture")
            return f.document
        end},
        Vector3f = {new = function(x, y, z) return {x = x, y = y, z = z} end},
        draw = {
            text = function(label, x, y)
                f.markers[#f.markers + 1] = {label = label, x = x, y = y}
            end,
            world_to_screen = function(position)
                if f.bad_projection then return {x = math.huge, y = 0} end
                return {x = position.x, y = position.z}
            end,
            line = function(x1, y1, x2, y2)
                f.lines[#f.lines + 1] = {x1, y1, x2, y2}
            end,
        },
    }, {__index = _G})
    assert(loadfile(path, "t", env))()
    return f
end

local function render(f)
    f.markers, f.lines = {}, {}
    for _ = 1, 6 do f.update() end
    f.draw()
end

local function close_to(actual, expected)
    assert(math.abs(actual - expected) < 0.0001, tostring(actual))
end

local f = fixture()
render(f)
assert(#f.markers == 1 and f.markers[1].label:find("claire", 1, true))
assert(f.markers[1].x == 1 and f.markers[1].y == 3)
assert(#f.lines == 1)
local length = f.lines[1][4] - f.lines[1][2]
assert(length > 0)

-- A quarter turn around +Y rotates the +Z diagnostic axis toward +X.
f.document.pose.rotation = {0, math.sqrt(0.5), 0, math.sqrt(0.5)}
render(f)
close_to(f.lines[1][3] - f.lines[1][1], length)
close_to(f.lines[1][4] - f.lines[1][2], 0)
print("ok - world marker tracks position and quaternion rotation")

f.now = 107
render(f)
assert(#f.markers == 0 and #f.lines == 0)
f.document.written_at = f.now
render(f)
assert(#f.markers == 1)
f.document.connected = false
render(f)
assert(#f.markers == 0)
print("ok - marker disappears when the lease expires or guest disconnects")

f.document.connected = true
f.player = false
render(f)
assert(#f.markers == 0)
f.player, f.bad_read = true, true
render(f)
assert(#f.markers == 0)
f.bad_read = false
f.document.pose.rotation = {0, 0, 0, 0}
render(f)
assert(#f.markers == 0)
f.document.pose.rotation = {0, 0, 0, 1}
f.document.pose.position = {1e39, 2, 3}
render(f)
assert(#f.markers == 0)
f.document.pose.position = {1, 2, 3}
f.game = "re3"
render(f)
assert(#f.markers == 0)
print("ok - marker requires RE2, a loaded player and valid pose data")

f.game, f.bad_projection = "re2", true
render(f)
assert(#f.markers == 0 and #f.lines == 0)
print("ok - rejects a non-finite screen projection")

f = fixture()
f.document.observed_at = 100
render(f)
assert(#f.markers == 1)
f.now = 106
f.markers, f.lines = {}, {}
f.draw()
assert(#f.markers == 0 and #f.lines == 0)
f.document.written_at = 106
render(f)
assert(#f.markers == 0)
f.document.observed_at = 106
render(f)
assert(#f.markers == 1)
print("ok - source observation expires even with a fresh local file")
print("5 Lua guest pose tests, 0 failures")
