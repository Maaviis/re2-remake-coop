-- Native RE2 load primitive for the opt-in read-only test probe; no save calls.
local M = {}
local manager_name = 'app.ropeway.gamemastering.SaveDataManager'
local flow_name = 'app.ropeway.gamemastering.MainFlowManager'

function M.new(guard)
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70)
    assert(guard and guard.active and type(guard.allow) == 'function')
    local self = {phase = 'idle', error = '', reference = nil, started_at = nil}

    local function reject(reason)
        self.error = reason
        return false, reason
    end

    function self:start(reference)
        if self.phase == 'reading_save' or self.phase == 'loading' then return false, 'load_in_progress' end
        local manager, flow = sdk.get_managed_singleton(manager_name), sdk.get_managed_singleton(flow_name)
        if not manager or not flow then return reject('load_managers_unavailable') end
        local inspected, title_ready = pcall(function()
            return manager:call('get_IsBusy') == false and flow:call('get_IsInLoadGameData') == false
                and flow:call('get_IsInTitle') == true
        end)
        if not inspected then return reject('load_status_unavailable') end
        if not title_ready then return reject('title_not_ready') end
        local authorized = pcall(guard.allow, guard, reference)
        if not authorized then return reject('save_reference_not_available') end
        self.reference = {mode = reference.mode, slot_id = reference.slot_id,
            timestamp = reference.timestamp, scenario = reference.scenario}
        self.error, self.phase, self.started_at = '', 'reading_save', os.time()
        local ok, accepted = pcall(manager.call, manager, 'requestLoadGameData', 1, reference.slot_id)
        if not ok or accepted ~= true then
            self.phase, self.error = 'failed', 'load_request_rejected'
            return false, self.error
        end
        return true
    end

    function self:poll(observation)
        if self.phase ~= 'reading_save' and self.phase ~= 'loading' then return end
        local now = os.time()
        local has_player = type(observation) == 'table' and observation.source == 're2' and observation.tdb == 70
            and observation.available == true and type(observation.observed_at) == 'number'
            and observation.observed_at > self.started_at and observation.observed_at <= now
            and now - observation.observed_at <= 3
        local ok = pcall(function()
            local manager, flow = sdk.get_managed_singleton(manager_name), sdk.get_managed_singleton(flow_name)
            if not manager or not flow then self.error = 'load_status_unavailable'; return end
            if manager:call('get_IsErrorBusy') then self.phase, self.error = 'failed', 'native_load_error'; return end
            self.error = ''
            if self.phase == 'reading_save' then
                -- Native menu trace: goLoadGameData follows completed async file reading.
                -- Calling it in the request frame skips loadGameSaveData and stalls scene loading.
                if manager:call('get_IsBusy') == false and manager:call('get_IsExistLoadedGameData') == true
                    and manager:call('get_LoadGameDataIndex') == self.reference.slot_id
                    and manager:call('isNoErrorLoad') == true and flow:call('get_IsInTitle') == true
                    and flow:call('get_IsInLoadGameData') == false then
                    self.phase = 'loading'
                    local started = pcall(flow.call, flow, 'goLoadGameData')
                    if not started then self.phase, self.error = 'failed', 'load_flow_start_failed' end
                end
                return
            end
            if has_player and manager:call('get_IsBusy') == false and flow:call('get_IsInLoadGameData') == false
                and flow:call('get_IsInTitle') == false and flow:call('get_IsFinishedLoadScene') == true
                and manager:call('get_LoadGameDataIndex') == self.reference.slot_id
                and flow:call('get_CurrentScenarioType') == self.reference.scenario then
                -- This proves scene/actor loading only; it does not verify title UI cleanup.
                self.phase, self.error = 'scene_loaded', ''
            end
        end)
        if not ok then self.error = 'load_status_unavailable' end
    end
    return self
end

return M
