-- Run from the repository root with Lua 5.4.
local function new_probe()
    local fixture = {
        address = 1,
        position = {x = 0, y = 0, z = 0},
        logs = {},
        reads = 0,
    }
    local transform = {
        get_position = function()
            fixture.reads = fixture.reads + 1
            return fixture.position
        end,
        get_rotation = function() return {x = 0, y = 0, z = 0, w = 1} end,
    }
    local player = {
        get_address = function() return fixture.address end,
        get_type_definition = function()
            return {get_full_name = function() return "via.GameObject" end}
        end,
        call = function(_, method)
            if method == "get_Transform" then return transform end
            if method == "getComponent(System.Type)" then
                if fixture.inventory_error then error("inventory unavailable") end
                return nil
            end
            error("unexpected player method " .. method)
        end,
    }
    local manager = {call = function(_, method)
        assert(method == "get_CurrentPlayer")
        if fixture.address then return player end
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
            typeof = function(name)
                assert(name == "app.ropeway.survivor.Inventory")
                return {}
            end,
        },
        log = {info = function(line) table.insert(fixture.logs, line) end},
        re = {
            on_pre_application_entry = function(name, callback)
                assert(name == "UpdateBehavior")
                fixture.update = callback
            end,
            on_draw_ui = function(callback) fixture.draw = callback end,
        },
        imgui = {
            tree_node = function() return true end,
            tree_pop = function() end,
            text = function() end,
            button = function(label) return fixture.inspect and label == "Inspect loaded game" end,
        },
    }, {__index = _G})
    assert(loadfile("reframework/autorun/re2_coop_probe.lua", "t", env))()
    return fixture
end

local function advance(fixture, updates)
    for _ = 1, updates do fixture.update() end
end

local function assert_log_count(fixture, fragment, expected)
    local count = 0
    for _, line in ipairs(fixture.logs) do
        if line:find(fragment, 1, true) then count = count + 1 end
    end
    assert(count == expected, string.format("expected %d '%s' logs, got %d", expected, fragment, count))
end

local function assert_movement_logs(fixture, expected)
    assert_log_count(fixture, "RE2_COOP_PROBE movement observed", expected)
end

local cases = {
    {"observes movement on the same player once", function()
        local fixture = new_probe()
        advance(fixture, 120)
        assert_movement_logs(fixture, 0)
        fixture.position.x = 1
        advance(fixture, 120)
        assert_movement_logs(fixture, 1)
    end},
    {"logs initial player discovery once during periodic sampling", function()
        local fixture = new_probe()
        advance(fixture, 240)
        assert_log_count(fixture, "RE2_COOP_PROBE game=re2", 1)
    end},
    {"observes valid movement while optional inventory inspection fails", function()
        local fixture = new_probe()
        fixture.inventory_error = true
        advance(fixture, 60)
        fixture.position.x = 1
        advance(fixture, 60)
        assert_movement_logs(fixture, 1)
    end},
    {"starts a new baseline when the player changes", function()
        local fixture = new_probe()
        advance(fixture, 60)
        fixture.address, fixture.position.x = 2, 20
        advance(fixture, 60)
        assert_movement_logs(fixture, 0)
        fixture.position.x = 21
        advance(fixture, 60)
        assert_movement_logs(fixture, 1)
    end},
    {"starts a new baseline after a missing player even when its address is reused", function()
        local fixture = new_probe()
        advance(fixture, 60)
        fixture.address = nil
        advance(fixture, 60)
        fixture.address, fixture.position.x = 1, 20
        advance(fixture, 60)
        assert_movement_logs(fixture, 0)
        fixture.position.x = 21
        advance(fixture, 60)
        assert_movement_logs(fixture, 1)
    end},
    {"starts a new baseline after a missing or non-finite position", function()
        for _, invalid in ipairs({false, math.huge, 0 / 0}) do
            local fixture = new_probe()
            advance(fixture, 60)
            fixture.position = invalid and {x = invalid, y = 0, z = 0} or nil
            advance(fixture, 60)
            fixture.position = {x = 20, y = 0, z = 0}
            advance(fixture, 60)
            assert_movement_logs(fixture, 0)
            fixture.position.x = 21
            advance(fixture, 60)
            assert_movement_logs(fixture, 1)
        end
    end},
    {"refreshes the panel without turning a manual inspection into a movement sample", function()
        local fixture = new_probe()
        advance(fixture, 60)
        local reads = fixture.reads
        fixture.position.x = 5
        fixture.inspect = true
        fixture.draw()
        fixture.inspect = false
        assert(fixture.reads == reads, "drawing UI must not read game objects")
        advance(fixture, 1)
        assert(fixture.reads == reads + 1, "queued inspection did not read the transform")
        assert_movement_logs(fixture, 0)
        fixture.position.x = 0
        advance(fixture, 59)
        assert_movement_logs(fixture, 0)
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
print(string.format("%d Lua probe tests, %d failures", #cases, failures))
if failures > 0 then os.exit(1) end
