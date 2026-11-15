-- Opt-in local evidence only. No native load, save, network or gameplay release.
local ok, reader = pcall(function() return require('re2_coop.load_state').new({details = true}) end)
local run_id = 'inventory-state-' .. os.time() .. '-' .. tostring({})
local sequence, frames, last_hint = 0, 0, nil
local function publish(state, reason)
    sequence = sequence + 1
    json.dump_file('re2_coop_inventory_state.json', {schema = 1, source = 're2', tdb = sdk.get_tdb_version(),
        run_id = run_id, sequence = sequence, observed_at = os.time(), scope = 'load_header_and_inventory_detail',
        available = state ~= nil, reason = reason, state = state})
end
if not ok then
    pcall(publish, nil, 'unsupported_interfaces')
    log.info('RE2_COOP_INVENTORY_STATE unavailable: ' .. tostring(reader))
    return
end
re.on_pre_application_entry('UpdateBehavior', function()
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local success, state, reason, hint = pcall(reader.capture)
    if not success then state, reason, hint = nil, 'state_read_failed', tostring(state) end
    if hint and hint ~= last_hint then
        last_hint = hint
        pcall(log.info, 'RE2_COOP_INVENTORY_STATE ' .. hint)
    end
    pcall(publish, state, reason)
end)
