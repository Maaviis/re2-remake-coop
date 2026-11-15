-- Opt-in observer of native title/menu and load transitions. All hooks pass through.
if reframework:get_game_name() ~= "re2" or sdk.get_tdb_version() ~= 70 then return end

local flow_type = "app.ropeway.gamemastering.MainFlowManager"
local gui_type = "app.ropeway.gui.GUIMaster"
local targets = {
    {flow_type, "goLoadGameData"},
    {"app.ropeway.gamemastering.TitleFlow", "setup"},
    {"app.ropeway.gamemastering.TitleFlow", "set_StateValue"},
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
    {"app.ropeway.gui.MenuStoryBehavior", "close"},
    {gui_type, "closeTitleMenu"},
    {gui_type, "closeMenuMain"},
    {gui_type, "closeMenuStory"},
}

local prefix = "RE2_COOP_TITLE_TRACE "
local first_tick = os.clock()
local reported_events = 0
local last_snapshot, updates, sample_requested = "not sampled", 0, true

local function record(message)
    -- Diagnostics must not change a hooked method's return path when logging fails.
    pcall(function() log.info(("%s%.3f %s"):format(prefix, os.clock() - first_tick, message)) end)
end

local function read(object, method)
    if not object then return "unavailable" end
    local ok, value = pcall(object.call, object, method)
    return ok and value ~= nil and tostring(value) or "unavailable"
end

local function snapshot()
    local flow = sdk.get_managed_singleton(flow_type)
    if not flow then return "flow unavailable" end
    local title = flow:call("get_Title")
    local save = sdk.get_managed_singleton("app.ropeway.gamemastering.SaveDataManager")
    local gui = sdk.get_managed_singleton(gui_type)
    return ("title=%s title_state=%s load_flow=%s scene_finished=%s " ..
        "save_busy=%s save_error=%s load_index=%s load_buffer=%s " ..
        "title_menu=%s main_menu=%s story_menu=%s load_menu=%s"):format(
        read(flow, "get_IsInTitle"), read(title, "get_StateValue"),
        read(flow, "get_IsInLoadGameData"), read(flow, "get_IsFinishedLoadScene"),
        read(save, "get_IsBusy"), read(save, "get_IsErrorBusy"),
        read(save, "get_LoadGameDataIndex"), read(save, "get_IsExistLoadedGameData"),
        read(gui, "isTitleMenuOpened"), read(gui, "isBusyMenuMain"),
        read(gui, "isBusyMenuStory"), read(gui, "isBusyLoad"))
end

local function report_call(stage, name, args, is_setter)
    if reported_events >= 128 then return end
    reported_events = reported_events + 1
    sample_requested = true
    local requested = ""
    if is_setter and stage == "enter" then
        local ok, state = pcall(function()
            local word = sdk.to_int64(args[3]) & 0xffffffff
            return word >= 0x80000000 and word - 0x100000000 or word
        end)
        requested = " requested_state=" .. (ok and tostring(state) or "unavailable")
    end
    -- The cached snapshot is explicitly older; no game getters run inside native hooks.
    record(stage .. " " .. name .. requested .. " cached=[" .. last_snapshot .. "]")
end

for _, target in ipairs(targets) do
    local type_name, method_name = target[1], target[2]
    local name = type_name .. "." .. method_name
    local ok = pcall(function()
        local def = assert(sdk.find_type_definition(type_name))
        local method = assert(def:get_method(method_name))
        sdk.hook(method, function(args)
            pcall(report_call, "enter", name, args, method_name == "set_StateValue")
            return sdk.PreHookResult.CALL_ORIGINAL
        end, function(retval)
            pcall(report_call, "leave", name)
            return retval
        end)
    end)
    record((ok and "observing " or "unavailable ") .. name)
end

re.on_pre_application_entry("UpdateBehavior", function()
    updates = updates + 1
    if updates % 30 ~= 0 and not sample_requested then return end
    sample_requested = false
    local ok, state = pcall(snapshot)
    if not ok then state = "flow unavailable" end
    if state ~= last_snapshot then
        last_snapshot = state
        record("sample " .. state)
    end
end)
