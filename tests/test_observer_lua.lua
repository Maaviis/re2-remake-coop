-- Run from the repository root with Lua 5.4.
local function new_observer()
    local fixture = {
        position = {x = 0, y = 0, z = 0},
        rotation = {x = 0, y = 0, z = 0, w = 1},
        written = {},
    }
    local transform = {
        get_position = function() return fixture.position end,
        get_rotation = function() return fixture.rotation end,
    }
    local player = {call = function(_, method)
        assert(method == "get_Transform")
        return transform
    end}
    local manager = {call = function(_, method)
        assert(method == "get_CurrentPlayer")
        return player
    end}
    local env = setmetatable({
        reframework = {get_game_name = function() return "re2" end},
        sdk = {
            get_tdb_version = function() return 70 end,
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
    {"rejects invalid positions and zero quaternions before writing", function()
        local fixture = new_observer()
        fixture.position.x = 0 / 0
        sample(fixture)
        fixture.position.x, fixture.rotation.w = 0, 0
        sample(fixture)
        assert(#fixture.written == 0, "invalid pose was written")
        fixture.rotation.w = 1
        sample(fixture)
        assert(#fixture.written == 1 and fixture.written[1].sequence == 1)
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
