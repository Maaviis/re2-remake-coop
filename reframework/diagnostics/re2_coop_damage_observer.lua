-- Opt-in passive enemy callback export, outside native damage hooks.
if reframework:get_game_name() ~= 're2' then return end
local timing_ok, timing = pcall(function() return require('re2_coop.damage_timing').new() end)
if not timing_ok then
    log.info('RE2_COOP_DAMAGE_TIMING unavailable: ' .. tostring(timing))
    timing = nil
end
local ok, reader = pcall(function() return require('re2_coop.damage_observer').new({timing=timing}) end)
local run_id = string.format('damage-%d-%.6f', os.time(), os.clock())
local frames = 0
if not ok then
    log.info('RE2_COOP_DAMAGE_OBSERVER unavailable: ' .. tostring(reader))
    pcall(json.dump_file, 're2_coop_damage_observer.json', {schema = 1, source = 're2', tdb = sdk.get_tdb_version(),
        observed_at = os.time(), run_id = run_id, available = false, reason = 'unsupported_interfaces'})
    return
end

local function protected_load()
    local raw = fs.read('re2_coop_save_guard.json')
    if type(raw) ~= 'string' or #raw == 0 or #raw > 131072 then return nil end
    local decoded, guard = pcall(json.load_string, raw)
    if not decoded or type(guard) ~= 'table' or guard.schema ~= 1 or guard.active ~= true or guard.hooks ~= 26
        or guard.protection_active ~= true or guard.in_title ~= false or guard.load_phase ~= 'scene_loaded'
        or guard.load_error ~= '' or guard.denied_loads ~= 0
        or type(guard.protection) ~= 'table' or type(guard.protection.run_id) ~= 'string'
        or type(guard.load_request_id) ~= 'string' or guard.load_request_id ~= guard.policy_id
        or math.type(guard.at) ~= 'integer' then return nil end
    local age = os.time() - guard.at
    if 0 <= age and age <= 3 then return guard.protection.run_id .. ':' .. guard.load_request_id, guard.at end
end

local binding, binding_at
re.on_application_entry('UpdateBehavior', function()
    -- Native game getters are deliberately outside the hit hooks.
    local found, player = pcall(function()
        local manager = sdk.get_managed_singleton(sdk.game_namespace('PlayerManager'))
        return manager and manager:call('get_CurrentPlayer')
    end)
    frames = frames + 1
    if frames % 6 == 1 then
        local read, scope, at = pcall(protected_load)
        binding, binding_at = read and scope or nil, at
    end
    reader:set_local_player(found and player or nil)
    if timing then
        local now = os.time()
        local fresh = binding and binding_at <= now and now - binding_at <= 3
        timing:frame(fresh and found and player or nil, fresh and binding or nil)
    end
    if frames % 6 ~= 0 then return end
    pcall(json.dump_file, 're2_coop_damage_observer.json', {schema = 1, source = 're2', tdb = sdk.get_tdb_version(),
        observed_at = os.time(), run_id = run_id, available = true, scope = 'enemy_damage_callback', state = reader:snapshot()})
end)
re.on_script_reset(function()
    if timing then timing:frame(nil) end
    reader:stop()
end)
