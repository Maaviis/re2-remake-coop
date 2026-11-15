local M = {}
local menu_type = "app.ropeway.gui.MenuMainBehavior"
local decision_type = menu_type .. ".DecidedResult"
local title_type = "app.ropeway.gamemastering.TitleFlow"
local stock = {0, 1, 2, 3, 4, 6}
local multiplayer_index = #stock

local function lookup(type_name, name, parameters)
    local def = assert(sdk.find_type_definition(type_name), type_name)
    local method = assert(def:get_method(name), name)
    local args = method:get_param_types()
    assert(not method:is_static() and #args == #parameters
        and method:get_return_type():get_full_name() == "System.Void", name)
    for index, parameter in ipairs(parameters) do
        assert(args[index]:get_full_name() == parameter, name)
    end
    return method
end

local function menu_label(row)
    local box = assert(row:call("getObject(System.String)", "c_list"), "missing menu label container")
    local label = assert(box:call("getObject(System.String)", "m_list"), "missing menu label")
    assert(label:get_type_definition():get_full_name() == "via.gui.Text")
    return label
end

local function restore_labels(selector, messages)
    local items = selector:call("get_Items")
    for index, message in ipairs(messages) do
        menu_label(items:get_element(index - 1)):call("set_MessageId", message)
    end
end

local function prepare(menu, decision)
    local choices = menu:call("get_DecidedList")
    local selector = menu:get_field("Selector")
    if not choices or not selector or choices:call("get_Count") ~= #stock
        or selector:call("get_ItemCount") ~= #stock or selector:call("get_ItemMax") ~= #stock then return end
    for index, value in ipairs(stock) do
        if choices:call("get_Item", index - 1) ~= value then return end
    end
    local items = selector:call("get_Items")
    if not items or items:get_size() ~= #stock + 1 then return end
    local spare = items:get_element(multiplayer_index)
    if not spare or spare:call("get_Visible") ~= false then return end
    local messages = {}
    for index = 1, #stock do
        messages[index] = assert(menu_label(items:get_element(index - 1)):call("get_MessageId"),
            "missing stock menu message ID")
    end

    local ok, item = pcall(function()
        choices:call("Add", decision)
        selector:call("set_ItemMax", #stock + 1)
        selector:call("set_ItemCount", #stock + 1)
        -- Resizing recreates the controls with the first row's localized message.
        restore_labels(selector, messages)
        local row = assert(selector:call("get_Items"):get_element(multiplayer_index), "missing multiplayer row")
        menu_label(row):call("set_Message", "Multiplayer")
        row:call("set_ListIndex", multiplayer_index)
        row:call("set_CanSelect", true)
        row:call("set_CanDecide", true)
        row:call("set_Enabled", true)
        row:call("set_Visible", true)
        return row
    end)
    if not ok then
        if choices:call("get_Count") == #stock + 1 and choices:call("get_Item", multiplayer_index) == decision then
            choices:call("RemoveAt", multiplayer_index)
        end
        selector:call("set_ItemCount", #stock)
        selector:call("set_ItemMax", #stock)
        restore_labels(selector, messages)
        log.error("RE2_COOP_MAIN_MENU " .. tostring(item))
        return
    end
    return {menu = menu:get_address(), object = menu, choices = choices, selector = selector, item = item,
            row = item:get_address(), messages = messages}
end

function M.install(open_lobby)
    if sdk.get_tdb_version() ~= 70 then return false end
    local enum = assert(sdk.find_type_definition(decision_type), decision_type)
    local decision = assert(enum:get_field("MAX"), "missing menu decision sentinel"):get_data(nil)
    assert(decision == #stock + 1)
    local init = lookup(menu_type, "initList", {decision_type})
    local close = lookup(menu_type, "close", {"System.Action"})
    local destroy = lookup(menu_type, "doOnDestroy", {})
    local choose_mouse = lookup(menu_type, "mouseSelectCallback", {})
    lookup(menu_type, "set_EnableInput", {"System.Boolean"})
    local decide_item = lookup("via.gui.SelectItem", "decide", {})
    local choose_title = lookup(title_type, "<update>b__39_19", {decision_type})
    local original, skip = sdk.PreHookResult.CALL_ORIGINAL, sdk.PreHookResult.SKIP_ORIGINAL
    local pending, active

    sdk.hook(init, function(args)
        thread.get_hook_storage().re2_coop_menu = args[2]
        return original
    end, function(retval)
        pending = thread.get_hook_storage().re2_coop_menu
        active = nil
        return retval
    end)
    local function remove_entry()
        local entry = active
        active = nil
        if not entry then return end
        local ok, failure = pcall(function()
            if entry.selector:call("get_SelectedIndex") == multiplayer_index then
                entry.selector:call("setCursorIndex(System.Int32, System.Boolean)", 0, false)
                entry.selector:call("setSelectedIndex(System.Int32, System.Boolean)", 0, false)
            end
            entry.item:call("set_Visible", false)
            if entry.choices:call("get_Item", multiplayer_index) == decision then
                entry.choices:call("RemoveAt", multiplayer_index)
            end
            entry.selector:call("set_ItemCount", #stock)
            entry.selector:call("set_ItemMax", #stock)
            restore_labels(entry.selector, entry.messages)
        end)
        if not ok then log.error("RE2_COOP_MAIN_MENU " .. tostring(failure)) end
    end
    local function forget(args, closing)
        local address = sdk.to_int64(args[2])
        if pending and sdk.to_int64(pending) == address then pending = nil end
        if active and active.menu == address then
            if closing then remove_entry() else active = nil end
        end
        return original
    end
    sdk.hook(close, function(args) return forget(args, true) end)
    sdk.hook(destroy, forget)

    local function open()
        active.lobby_opened, active.resume_requested = true, nil
        log.info("RE2_COOP_MAIN_MENU selected Multiplayer")
        open_lobby()
        return skip
    end
    local function resume_menu(entry)
        entry.resume_requested, entry.lobby_opened = nil, nil
        local ok, failure = pcall(function()
            if entry.object:call("get_EnableInput") == false then
                entry.object:call("set_EnableInput", true)
                log.info("RE2_COOP_MAIN_MENU resumed input")
            end
        end)
        if not ok then log.error("RE2_COOP_MAIN_MENU " .. tostring(failure)) end
    end
    sdk.hook(decide_item, function(args)
        if active and sdk.to_int64(args[2]) == active.row then return open() end
        return original
    end)
    sdk.hook(choose_mouse, function(args)
        if active and sdk.to_int64(args[2]) == active.menu
            and active.selector:call("get_SelectedIndex") == multiplayer_index then return open() end
        return original
    end)
    sdk.hook(choose_title, function(args)
        if active and (sdk.to_int64(args[3]) & 0xffffffff) == decision then return open() end
        return original
    end)
    re.on_pre_application_entry("UpdateBehavior", function()
        if active and active.resume_requested then resume_menu(active) end
        if not pending then return end
        local menu = sdk.to_managed_object(pending)
        if not menu then pending = nil; return end
        if menu:call("get_EnableInput") ~= true then return end
        pending = nil
        local ok, result = pcall(prepare, menu, decision)
        if ok then
            active = result
            if active then log.info("RE2_COOP_MAIN_MENU registered Multiplayer") end
        else
            log.error("RE2_COOP_MAIN_MENU " .. tostring(result))
        end
    end)
    re.on_script_reset(function()
        pending = nil
        if active and active.lobby_opened then resume_menu(active) end
        remove_entry()
    end)
    return function()
        if active and active.lobby_opened then active.resume_requested = true end
    end
end

return M
