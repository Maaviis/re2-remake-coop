-- Opt-in local evidence only. No native load, save, network or gameplay release.
local same_state
local ok, reader = pcall(function()
    local module = require('re2_coop.load_state')
    same_state = module.same_state
    return module.new()
end)
local run_id = 'load-state-' .. os.time() .. '-' .. tostring({})
local sequence, frames, last_hint = 0, 0, nil
local last_at, last_state, last_reason
local function publish(state, reason)
    local now = os.time()
    if now == last_at and reason == last_reason and same_state(state, last_state) then return end
    local result = json.dump_file('re2_coop_load_state.json', {schema = 1, source = 're2', tdb = sdk.get_tdb_version(),
        run_id = run_id, sequence = sequence + 1, observed_at = now, scope = 'load_header_and_inventory_core',
        available = state ~= nil, reason = reason, state = state})
    if result ~= false then
        sequence, last_at, last_reason, last_state = sequence + 1, now, reason, state
    end
end
if not ok then
    pcall(publish, nil, 'unsupported_interfaces')
    log.info('RE2_COOP_LOAD_STATE unavailable: ' .. tostring(reader))
    return
end
re.on_pre_application_entry('UpdateBehavior', function()
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local success, state, reason, hint = pcall(reader.capture)
    if not success then state, reason, hint = nil, 'state_read_failed', tostring(state) end
    if hint and hint ~= last_hint then
        last_hint = hint
        pcall(log.info, 'RE2_COOP_LOAD_STATE ' .. hint)
    end
    pcall(publish, state, reason)
end)
