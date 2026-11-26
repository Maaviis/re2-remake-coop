-- Test-only single-player driver on the supervisor's non-interactive desktop.
local request = json.load_file("re2_coop_save_service_probe_request.json")
if type(request) ~= "table" or request.background ~= true or type(request.run) ~= "string"
        or #request.run ~= 32 or not request.run:match("^[0-9a-f]+$")
        or request.mount ~= "./coop-save-"..request.run then return end
if reframework:get_game_name() ~= "re2" or sdk.get_tdb_version() ~= 70 then return end
local file = "re2_coop_autosave_experiment.json"
local phase, began, player_since, next_poll = "waiting", os.time(), nil, 0
local result = {run=request.run}
local service = sdk.find_type_definition("via.storage.saveService.SaveService")
local function static(name) return service:get_method(name):call(nil) end
local function record(state)
    phase, result.phase = state, state
    json.dump_file(file, result)
end
local function tick()
    if phase=="finished" or phase=="error" then return end
    if phase=="waiting" then
        if os.time()<next_poll then return end
        next_poll=os.time()+1
        local ok, auth=pcall(json.load_file,"re2_coop_autosave_experiment_go.json")
        if not ok or type(auth)~="table" or auth.run~=request.run then return end
    end
    local flow=sdk.get_managed_singleton("app.ropeway.gamemastering.MainFlowManager")
    local manager=sdk.get_managed_singleton("app.ropeway.gamemastering.SaveDataManager")
    local gui=sdk.get_managed_singleton("app.ropeway.gui.GUIMaster")
    if not flow or not manager or not gui then return end
    if static("get_SaveMountPath")~=request.mount then
        result.error="mount_changed"
        return record("error")
    end
    if phase=="waiting" then
        if not flow:call("get_IsInTitle") or manager:call("get_IsBusy") or manager:call("get_IsErrorBusy") then return end
        local title=flow:call("get_Title")
        if not title or not (gui:call("isTitleMenuOpened") or gui:call("isBusyMenuMain")) then return end
        result.before_write={state=static("get_SaveState"),failed=static("get_LastSaveFailed"),code=static("get_LastErrorCode")}
        result.system_accepted=manager:call("requestSaveSystemData")
        if not result.system_accepted then result.error="system_write_rejected";return record("error") end
        began=os.time()
        return record("system_write")
    elseif phase=="system_write" then
        if manager:call("get_IsBusy") then result.system_busy=true end
        if os.time()-began<4 or manager:call("get_IsBusy") and os.time()-began<20 then return end
        result.system_result={state=static("get_SaveState"),failed=static("get_LastSaveFailed"),
            code=static("get_LastErrorCode"),busy=manager:call("get_IsBusy"),error_busy=manager:call("get_IsErrorBusy")}
        if result.system_result.failed or result.system_result.error_busy or result.system_result.busy then
            result.error="system_write_failed"
            return record("error")
        end
        record("closing_menu")
        flow:call("setDifficulty",1)
        flow:call("setupNewGame",0)
        if gui:call("isTitleMenuOpened") then gui:call("closeTitleMenu",nil) end
        if gui:call("isBusyMenuMain") then gui:call("closeMenuMain",nil) end
    elseif phase=="closing_menu" then
        if gui:call("isTitleMenuOpened") or gui:call("isBusyMenuMain") then return end
        if not flow:call("get_IsInTitle") or not flow:call("get_Title") then return end
        record("loading")
        flow:call("get_Title"):call("set_StateValue",29)
    elseif phase=="loading" then
        local players=sdk.get_managed_singleton("app.ropeway.PlayerManager")
        local in_title=flow:call("get_IsInTitle")
        local loaded=flow:call("get_IsFinishedLoadScene")
        local player=players and players:call("get_CurrentPlayer")
        if os.time()>=next_poll then
            next_poll=os.time()+3
            local title=flow:call("get_Title")
            result.loading={in_title=in_title,scene_loaded=loaded,has_player=player~=nil,
                title_state=title and title:call("get_StateValue") or -1,load_flow=flow:call("get_IsInLoadGameData"),
                busy=manager:call("get_IsBusy"),error_busy=manager:call("get_IsErrorBusy"),
                mount_still_set=static("get_SaveMountPath")==request.mount,save_result=static("get_LastSaveResult")}
            record("loading")
        end
        if in_title or not loaded or not player then return end
        result.scenario=flow:call("get_CurrentScenarioType")
        result.difficulty=flow:call("get_CurrentDifficulty")
        player_since=os.time()
        record("scene_loaded")
    elseif phase=="scene_loaded" then
        if os.time()-player_since<12 or manager:call("get_IsBusy") then return end
        -- Distinguish the native autosave API from a gameplay-triggered checkpoint.
        record("requesting_native_autosave")
        result.accepted=manager:call("requestSaveGameDataAuto")
        if not result.accepted then result.error="autosave_rejected";return record("error") end
        result.state_at_request=static("get_SaveState")
        began=os.time()
        record("observing")
    elseif phase=="observing" then
        if manager:call("get_IsBusy") then result.observed_busy=true end
        if os.time()-began<10 then return end
        if manager:call("get_IsBusy") and os.time()-began<25 then return end
        result.busy_at_end=manager:call("get_IsBusy")
        result.error_busy=manager:call("get_IsErrorBusy")
        result.save_state=static("get_SaveState")
        result.last_result=static("get_LastSaveResult")
        result.last_failed=static("get_LastSaveFailed")
        result.last_code=static("get_LastErrorCode")
        if result.last_failed or result.last_code~=0 or result.error_busy or result.busy_at_end then
            result.error="autosave_failed"
            return record("error")
        end
        record("checking_checkpoint")
    elseif phase=="checking_checkpoint" then
        if manager:call("get_IsBusy") then return end
        local detail = manager:call("getSaveFileDetail",1,0)
        if not detail or detail:call("get_EmptyData") then
            result.error="no_native_auto_slot_detail"
            return record("error")
        end
        result.checkpoint={slot=detail:call("get_Slot"),stamp=tostring(detail:call("get_LastUpdateTimeStamp")),
            scenario=manager:call("getScenarioTypeFromDetailString",detail)}
        if result.checkpoint.slot~=0 or result.checkpoint.scenario~=result.scenario then return record("error") end
        flow:call("goResetGameToTitle")
        return record("returning_to_title")
    elseif phase=="returning_to_title" then
        if not flow:call("get_IsInTitle") or flow:call("get_IsInLoadGameData") or manager:call("get_IsBusy")
                or not (gui:call("isTitleMenuOpened") or gui:call("isBusyMenuMain")) then return end
        local detail=manager:call("getSaveFileDetail",1,0)
        if not detail or detail:call("get_EmptyData") or tostring(detail:call("get_LastUpdateTimeStamp"))~=result.checkpoint.stamp then
            result.error="checkpoint_identity_changed_at_title"
            return record("error")
        end
        result.read_accepted=manager:call("requestLoadGameData",1,0)
        if result.read_accepted~=true then return record("error") end
        began=os.time()
        record("reading_checkpoint")
    elseif phase=="reading_checkpoint" then
        if manager:call("get_IsBusy") then result.read_busy=true end
        local has=manager:call("get_IsExistLoadedGameData")
        local slot=manager:call("get_LoadGameDataIndex")
        local ok=manager:call("isNoErrorLoad")
        if has and ok and slot==0 and not manager:call("get_IsBusy") or os.time()-began>25 then
            result.read_result={has_data=has,slot=slot,ok=ok,error_busy=manager:call("get_IsErrorBusy")}
            if not (has and ok and slot==0 and not result.read_result.error_busy) then return record("error") end
            if gui:call("isTitleMenuOpened") then gui:call("closeTitleMenu",nil) end
            if gui:call("isBusyMenuMain") then gui:call("closeMenuMain",nil) end
            if gui:call("isBusyMenuStory") then gui:call("closeMenuStory",nil,true) end
            return record("closing_for_reload")
        end
    elseif phase=="closing_for_reload" then
        if gui:call("isTitleMenuOpened") or gui:call("isBusyMenuMain") or gui:call("isBusyMenuStory") or gui:call("isBusyLoad") then return end
        flow:call("get_Title"):call("set_StateValue",29)
        record("reloading_world")
    elseif phase=="reloading_world" then
        if flow:call("get_IsInTitle") or flow:call("get_IsInLoadGameData") or not flow:call("get_IsFinishedLoadScene") then return end
        if not sdk.get_managed_singleton("app.ropeway.PlayerManager"):call("get_CurrentPlayer") then return end
        result.reloaded_world={scenario=flow:call("get_CurrentScenarioType"),difficulty=flow:call("get_CurrentDifficulty"),
            slot=manager:call("get_LoadGameDataIndex"),has_player=true}
        if result.reloaded_world.scenario~=result.scenario or result.reloaded_world.difficulty~=result.difficulty
                or result.reloaded_world.slot~=result.checkpoint.slot then
            result.error="reloaded_checkpoint_mismatch"
            return record("error")
        end
        record("finished")
    end
end
re.on_pre_application_entry("UpdateBehavior",function()
    local ok,err=pcall(tick)
    if not ok then result.error=tostring(err):sub(1,220);record("error") end
end)
