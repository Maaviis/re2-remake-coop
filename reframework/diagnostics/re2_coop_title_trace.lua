-- Opt-in observer of native title/menu and load transitions. All hooks pass through.
if reframework:get_game_name() ~= "re2" or sdk.get_tdb_version() ~= 70 then return end

local flow_type = "app.ropeway.gamemastering.MainFlowManager"
local targets = {
    {flow_type, "goLoadGameData"},
    {"app.ropeway.gamemastering.TitleFlow", "setup"},
    {"app.ropeway.gamemastering.LoadGameDataFlow", "setup"},
    {"app.ropeway.gamemastering.LoadGameDataFlow", "unloadTitleEnvironment"},
    {"app.ropeway.gamemastering.LoadGameDataFlow", "end"},
    {"app.ropeway.gui.TitleRBehavior", "open"},
    {"app.ropeway.gui.TitleRBehavior", "openDirectly"},
    {"app.ropeway.gui.TitleRBehavior", "close"},
    {"app.ropeway.gui.TitleRBehavior", "doOnDestroy"},
    {"app.ropeway.gui.MenuMainBehavior", "open"},
    {"app.ropeway.gui.MenuMainBehavior", "close"},
    {"app.ropeway.gui.MenuMainBehavior", "doOnDestroy"},
}

local prefix = "RE2_COOP_TITLE_TRACE "
local first_tick = os.clock()
local reported_calls = 0

local function record(message)
    log.info(("%s%.3f %s"):format(prefix, os.clock() - first_tick, message))
end

for _, target in ipairs(targets) do
    local type_name, method_name = target[1], target[2]
    local name = type_name .. "." .. method_name
    local ok = pcall(function()
        local def = assert(sdk.find_type_definition(type_name))
        local method = assert(def:get_method(method_name))
        sdk.hook(method, function()
            if reported_calls < 128 then
                reported_calls = reported_calls + 1
                pcall(record, "called " .. name)
            end
            return sdk.PreHookResult.CALL_ORIGINAL
        end, function(retval)
            return retval
        end)
    end)
    record((ok and "observing " or "unavailable ") .. name)
end

local last, updates = nil, 0
re.on_pre_application_entry("UpdateBehavior", function()
    updates = updates + 1
    if updates % 30 ~= 0 then return end
    local ok, state = pcall(function()
        local flow = sdk.get_managed_singleton(flow_type)
        if not flow then return end
        local title = flow:call("get_Title")
        local title_state = title and title:call("get_StateValue")
        return ("title=%s title_state=%s load_flow=%s scene_finished=%s"):format(
            tostring(flow:call("get_IsInTitle")), tostring(title_state),
            tostring(flow:call("get_IsInLoadGameData")), tostring(flow:call("get_IsFinishedLoadScene")))
    end)
    if not ok then state = "flow unavailable" end
    if state and state ~= last then
        last = state
        record("state " .. state)
    end
end)
