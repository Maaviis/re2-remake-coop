local menu_name = "app.ropeway.gui.MenuMainBehavior"
local enum_name = menu_name .. ".DecidedResult"
local title_name = "app.ropeway.gamemastering.TitleFlow"
local item_name = "via.gui.SelectItem"
local hooks, objects, storage = {}, {}, {}
local update, reset
local function kind(name) return {get_full_name = function() return name end} end
local function method(key, parameters)
    return {
        key = key, is_static = function() return false end,
        get_return_type = function() return kind("System.Void") end,
        get_param_types = function()
            local types = {}
            for index, name in ipairs(parameters) do types[index] = kind(name) end
            return types
        end,
    }
end
local methods = {
    [menu_name] = {
        initList = method("init", {enum_name}), close = method("close", {"System.Action"}),
        doOnDestroy = method("destroy", {}), mouseSelectCallback = method("mouse", {}),
    },
    [title_name] = {["<update>b__39_19"] = method("title", {enum_name})},
    [item_name] = {decide = method("item", {})},
}
local tdb = 70
sdk = {
    get_tdb_version = function() return tdb end, PreHookResult = {CALL_ORIGINAL = 0, SKIP_ORIGINAL = 1},
    to_int64 = function(value) return value end,
    to_managed_object = function(address) return objects[address] end,
    find_type_definition = function(name)
        return {
            get_method = function(_, key) return methods[name][key] end,
            get_field = function(_, key)
                assert(name == enum_name and key == "MAX")
                return {get_data = function() return 7 end}
            end,
        }
    end,
    hook = function(target, pre, post) hooks[target.key] = {pre = pre, post = post} end,
}
thread = {get_hook_storage = function() return storage end}
re = {on_pre_application_entry = function(event, callback) assert(event == "UpdateBehavior"); update = callback end,
      on_script_reset = function(callback) reset = callback end}
local failures = {}
log = {info = function() end, error = function(message) failures[#failures + 1] = message end}

local stock_messages = {"campaign", "extras", "bonus", "shop", "options", "quit"}
local expected_messages = table.concat(stock_messages, ",")
local function fixture(choices, label_available)
    local model = {choices = choices, count = #choices, max = #choices, selected = 0,
                   visible = false, messages = {table.unpack(stock_messages)}}
    local function make_row(index)
        local label = {get_type_definition = function() return kind("via.gui.Text") end,
            call = function(_, name, value)
                if name == "get_MessageId" then return model.messages[index + 1] end
                if name == "set_MessageId" then model.messages[index + 1] = value; return end
                assert(name == "set_Message"); model.text = value
            end}
        local box = {call = function(_, _, name)
            assert(name == "m_list")
            if index < 6 or label_available then return label end
        end}
        return {get_address = function() return 54 + index end, call = function(_, name, value)
            if name == "get_Visible" then return model.visible end
            if name == "getObject(System.String)" then assert(value == "c_list"); return box end
            if name == "set_Visible" then model.visible = value end
        end}
    end
    local items = {get_size = function() return model.max + 1 end,
                   get_element = function(_, index) return make_row(index) end}
    local selector = {call = function(_, name, value)
        if name == "get_ItemCount" then return model.count end
        if name == "get_ItemMax" then return model.max end
        if name == "get_Items" then return items end
        if name == "get_SelectedIndex" then return model.selected end
        if name == "setCursorIndex(System.Int32, System.Boolean)" then return end
        if name == "setSelectedIndex(System.Int32, System.Boolean)" then model.selected = value; return end
        if name == "set_ItemMax" then
            model.max = value
            for index = 1, #stock_messages do model.messages[index] = stock_messages[1] end
            return
        end
        if name == "set_ItemCount" then model.count = value; return end
        error(name)
    end}
    local list = {call = function(_, name, value)
        if name == "get_Count" then return #choices end
        if name == "get_Item" then return choices[value + 1] end
        if name == "Add" then choices[#choices + 1] = value; return end
        if name == "RemoveAt" then table.remove(choices, value + 1); return end
        error(name)
    end}
    objects[100] = {get_address = function() return 100 end,
                    get_field = function(_, name) assert(name == "Selector"); return selector end,
                    call = function(_, name)
                        if name == "get_EnableInput" then return true end
                        assert(name == "get_DecidedList"); return list
                    end}
    return model
end

local module = dofile("reframework/autorun/re2_coop/main_menu.lua")
local opens = 0
local function open() opens = opens + 1 end
tdb = 69
assert(module.install(open) == false and next(hooks) == nil)
tdb = 70
assert(module.install(open))
local function init()
    assert(hooks.init.pre({0, 100}) == 0)
    assert(hooks.init.post(123) == 123)
    update()
end

local model = fixture({0, 1, 2, 3, 4, 6}, true)
init()
assert(table.concat(model.choices, ",") == "0,1,2,3,4,6,7")
assert(model.count == 7 and model.max == 7 and model.text == "Multiplayer" and model.visible)
assert(table.concat(model.messages, ",") == expected_messages, "resize overwrote the stock menu labels")
assert(hooks.mouse.pre({0, 100}) == 0 and hooks.item.pre({0, 50}) == 0)
assert(hooks.title.pre({0, 200, 4}) == 0 and opens == 0)
model.selected = 6
assert(hooks.mouse.pre({0, 100}) == 1 and opens == 1)
assert(hooks.item.pre({0, 60}) == 1 and hooks.title.pre({0, 200, 7}) == 1 and opens == 3)
assert(hooks.close.pre({0, 100}) == 0)
assert(model.count == 6 and model.max == 6 and not model.visible and model.selected == 0)
assert(table.concat(model.messages, ",") == expected_messages, "close overwrote the stock menu labels")
assert(hooks.item.pre({0, 60}) == 0 and hooks.title.pre({0, 200, 7}) == 0)
model = fixture({0, 1, 2, 3, 4, 6}, true)
init()
reset()
assert(model.count == 6 and model.max == 6 and not model.visible and #model.choices == 6)
assert(table.concat(model.messages, ",") == expected_messages, "reset overwrote the stock menu labels")
model = fixture({0, 1, 2, 3, 4, 6}, true)
assert(hooks.init.pre({0, 100}) == 0)
hooks.init.post(123)
assert(hooks.destroy.pre({0, 100}) == 0)
update()
assert(#model.choices == 6 and model.text == nil, "destroyed menu was modified")

model = fixture({0, 1, 2, 3, 4, 5, 6}, true)
init()
assert(model.text == nil and table.concat(model.choices, ",") == "0,1,2,3,4,5,6")
model = fixture({0, 1, 2, 3, 4, 6}, false)
init()
assert(model.count == 6 and model.max == 6 and #model.choices == 6 and #failures == 1)
assert(table.concat(model.messages, ",") == expected_messages, "rollback overwrote the stock menu labels")
print("RE2 main menu: insert, native dispatch, vanilla actions, destruction and rollback passed")
