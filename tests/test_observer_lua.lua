-- Run from the repository root with Lua 5.4.
local function new_observer()
    local fixture = {
        now = 100,
        loaded = true,
        position = {x = 0, y = 0, z = 0},
        rotation = {x = 0, y = 0, z = 0, w = 1},
        motion = nil,
        written = {},
    }
    local transform = {
        get_position = function() return fixture.position end,
        get_rotation = function() return fixture.rotation end,
    }
    local layer = {call = function(_, method)
        if fixture.motion_error then error("motion unavailable") end
        if method == "get_HighestWeightMotionNode" then
            return {call = function() return fixture.motion.name end}
        end
        local fields = {get_MotionBankID = "bank", get_MotionID = "id",
            get_Frame = "frame", get_EndFrame = "end_frame"}
        return fixture.motion[assert(fields[method])]
    end}
    local motion_component = {call = function(_, method)
        if method == "getLayerCount" then return 1 end
        assert(method == "getLayer(System.UInt32)")
        return layer
    end}
    local player = {call = function(_, method, argument)
        if method == "get_Transform" then return transform end
        assert(method == "getComponent(System.Type)" and argument == "via.motion.Motion")
        if fixture.motion then return motion_component end
    end}
    local manager = {call = function(_, method)
        assert(method == "get_CurrentPlayer")
        if fixture.loaded then return player end
    end}
    local env = setmetatable({
        os = {time = function() return fixture.now end},
        reframework = {get_game_name = function() return "re2" end},
        sdk = {
            get_tdb_version = function() return 70 end,
            typeof = function(name) return name end,
            game_namespace = function(name) return "app.ropeway." .. name end,
            get_managed_singleton = function(name)
                assert(name == "app.ropeway.PlayerManager")
                return manager
            end,
        },
        log = {info = function() end},
        re = {
            on_pre_application_entry = function(name, callback)
                assert(name == "UpdateBehavior")
                fixture.update = callback
            end,
        },
        json = {dump_string = function(sample)
            fixture.encoding = sample
            return fixture.fail_encoding and "" or "encoded sample"
        end},
        io = {open = function(path, mode)
            assert(path == "re2_coop_observer.json" and mode == "wb")
            if fixture.fail_open then return nil end
            local pending
            return {
                write = function(self, encoded)
                    assert(encoded == "encoded sample")
                    if fixture.fail_write then return nil, "write failed" end
                    pending = fixture.encoding
                    return self
                end,
                close = function()
                    if fixture.fail_close then return nil, "close failed" end
                    if pending then table.insert(fixture.written, pending) end
                    return true
                end,
            }
        end},
    }, {__index = _G})
    assert(loadfile("reframework/autorun/re2_coop_observer.lua", "t", env))()
    return fixture
end

local function sample(fixture)
    for _ = 1, 6 do fixture.update() end
end

local cases = {
    {"refreshes a stationary pose and reports absence and return", function()
        local fixture = new_observer()
        sample(fixture)
        sample(fixture)
        assert(#fixture.written == 1 and fixture.written[1].observed_at == 100)
        fixture.now = 101
        sample(fixture)
        assert(#fixture.written == 2 and fixture.written[2].observed_at == 101)
        assert(fixture.written[2].position[1] == fixture.written[1].position[1])
        fixture.loaded = false
        sample(fixture)
        fixture.now = 102
        sample(fixture)
        assert(#fixture.written == 3 and fixture.written[3].available == false)
        assert(fixture.written[3].position == nil and fixture.written[3].rotation == nil)
        fixture.loaded = true
        sample(fixture)
        assert(#fixture.written == 4 and fixture.written[4].available == true)
        assert(fixture.written[4].sequence == 4)
    end},
    {"emits rotation at an unchanged position", function()
        local fixture = new_observer()
        sample(fixture)
        fixture.rotation.y, fixture.rotation.w = 0.5, 0.5
        sample(fixture)
        assert(#fixture.written == 2, "rotation-only sample was dropped")
        local pose = fixture.written[2]
        assert(pose.sequence == 2 and pose.position[1] == 0)
        assert(pose.rotation[2] == 0.5 and pose.rotation[4] == 0.5)
    end},
    {"does not resend an equivalent quaternion with flipped sign and scale", function()
        local fixture = new_observer()
        fixture.rotation.y, fixture.rotation.w = 0.5, 0.5
        sample(fixture)
        fixture.rotation.y, fixture.rotation.w = -1, -1
        sample(fixture)
        assert(#fixture.written == 1, "equivalent orientation produced another sample")
    end},
    {"emits translation and suppresses unchanged poses", function()
        local fixture = new_observer()
        sample(fixture)
        sample(fixture)
        fixture.position.x = 1
        sample(fixture)
        assert(#fixture.written == 2 and fixture.written[2].position[1] == 1)
    end},
    {"emits motion-only changes without losing the player pose", function()
        local fixture = new_observer()
        fixture.motion = {bank = 1, id = 160, name = "pl00_0160_OFF_Gazing_Idle_F_Loop",
            frame = 10, end_frame = 1100}
        sample(fixture)
        assert(fixture.written[1].motion.frame == 10)
        fixture.motion.frame = 12
        sample(fixture)
        assert(#fixture.written == 2 and fixture.written[2].motion.frame == 12)
        fixture.motion_error = true
        sample(fixture)
        assert(#fixture.written == 3 and fixture.written[3].motion == nil)
        assert(fixture.written[3].position[1] == 0)
    end},
    {"retries an unchanged pose after an output failure", function()
        for _, failure in ipairs({"fail_open", "fail_write", "fail_close", "fail_encoding"}) do
            local fixture = new_observer()
            sample(fixture)
            fixture.position.x = 2
            fixture[failure] = true
            sample(fixture)
            assert(#fixture.written == 1, failure .. " was accepted")
            fixture[failure] = false
            sample(fixture)
            assert(#fixture.written == 2, failure .. " consumed the new pose")
            assert(fixture.written[2].sequence == 2 and fixture.written[2].position[1] == 2)
        end
    end},
    {"reports an unavailable pose when the position or quaternion is invalid", function()
        local fixture = new_observer()
        fixture.position.x = 0 / 0
        sample(fixture)
        fixture.position.x, fixture.rotation.w = 0, 0
        sample(fixture)
        assert(#fixture.written == 1 and fixture.written[1].available == false)
        fixture.rotation.w = 1
        sample(fixture)
        assert(#fixture.written == 2 and fixture.written[2].sequence == 2)
    end},
}

local failures = 0
for _, case in ipairs(cases) do
    local ok, err = pcall(case[2])
    if ok then
        print("ok - " .. case[1])
    else
        failures = failures + 1
        io.stderr:write("not ok - " .. case[1] .. ": " .. tostring(err) .. "\n")
    end
end
print(string.format("%d Lua observer tests, %d failures", #cases, failures))
if failures > 0 then os.exit(1) end

