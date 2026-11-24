-- No RE2, filesystem or Steam access. Exercise the test fixtures' opt-in boundary.
local token = string.rep('a', 32)
local path = './coop-save-' .. token
local function observe(config, build)
    local mount, scheduled, result = './win64_save', nil, nil
    local getters = {
        hasInstance = function() return true end,
        get_SaveMountPath = function() return mount end,
        get_SaveDirectoryPath = function() return 'SAVESERVICE-LINE-0-' end,
        get_SaveState = function() return 1 end,
    }
    local calls = 0
    local service = {get_method = function(_, name)
        if name == 'set_SaveMountPath' then
            return {
                is_static = function() return true end,
                get_param_types = function()
                    return {{get_full_name = function() return 'System.String' end}}
                end,
                call = function(_, _, value) calls = calls + 1; mount = value end,
            }
        end
        return {is_static = function() return true end, get_num_params = function() return 0 end,
                call = assert(getters[name])}
    end}
    json = {load_file = function() return config end,
            dump_file = function(_, observation) result = observation end}
    sdk = {get_tdb_version = function() return build end, find_type_definition = function() return service end,
           get_managed_singleton = function() return {call = function() return true end} end}
    reframework = {get_game_name = function() return 're2' end}
    re = {on_pre_application_entry = function(_, callback) scheduled = callback end}
    dofile('tests/re2_coop_save_service_probe.lua')
    if scheduled then scheduled(); scheduled() end
    return calls, result
end

for _, request in ipairs({
    {}, {run = token}, {run = token, mount = path},
    {run = token, mount = '../' .. path, background = true},
    {run = token, mount = './win64_save', background = true},
    {run = string.rep('.', 32), mount = path, background = true},
}) do
    assert(observe(request, 70) == 0)
end
local request = {run = token, mount = path, background = true}
assert(observe(request, 69) == 0)
local calls, receipt = observe(request, 70)
assert(calls == 1 and receipt.redirected and receipt.redirect.value == path)
print('Only the supported test build and exact relative namespace may change the mount once')
