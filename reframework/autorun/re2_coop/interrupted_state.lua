-- Bind a native observation to the same owned interruption before and after the read.
local M = {}
local scope_fields = {'session_id', 'attempt_id', 'release_id', 'game_pid', 'role', 'protection_run_id', 'at'}

function M.new(capture, report_scope)
    local sequence = 0
    local run_id = 'interrupted-state-' .. os.time() .. '-' .. tostring({})
    return function(before, read_hold)
        local scope = before.interruption
        if before.phase ~= 'interrupted' or before.native_phase ~= 'held' or not scope
            or before.observed_at <= scope.at then return nil end
        local state, reason = capture()
        local after = read_hold()
        local current = after and after.interruption
        local now = os.time()
        if not current or after.phase ~= 'interrupted' or after.native_phase ~= 'held'
            or after.load_request_id ~= before.load_request_id or after.guard_run_id ~= before.guard_run_id
            or after.observed_at > now or now - after.observed_at > 1
            or current.area.scenario ~= scope.area.scenario or current.area.map ~= scope.area.map
            or current.area.area ~= scope.area.area then return nil end
        for _, field in ipairs(scope_fields) do
            if current[field] ~= scope[field] then return nil end
        end
        if state and (state.scenario or state.checkpoint.scenario) ~= scope.area.scenario then
            state, reason = nil, 'interrupted_scenario_changed'
        end
        if state then
            state.interruption = {scope=scope, load_request_id=before.load_request_id, guard_run_id=before.guard_run_id}
        end
        sequence = sequence + 1
        return {schema=1, source='re2', tdb=70, run_id=run_id, sequence=sequence, observed_at=now,
            scope=report_scope, available=state ~= nil, reason=reason, state=state}
    end
end

return M
