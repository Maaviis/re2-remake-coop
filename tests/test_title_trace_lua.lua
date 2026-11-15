local function install(options)
    options = options or {}
    local fixture = {hooks = {}, logs = {}, forbidden = 0, in_hook = false, now = 10,
        title = true, title_state = 100, load_flow = false, finished = false,
        busy = false, save_error = false, load_index = 4, buffer = false,
        title_menu = true, main_menu = false, story_menu = false, load_menu = false}
    local function check_read()
        if fixture.in_hook then fixture.forbidden = fixture.forbidden + 1; error('game getter inside hook') end
    end
    local function object(fields)
        return {call = function(_, name)
            check_read()
            if name == fixture.throw_method then error('unavailable') end
            assert(fields[name], 'unexpected game mutation or getter: ' .. name)
            return fields[name]()
        end}
    end
    local title = object({get_StateValue = function() return fixture.title_state end})
    local flow = object({get_Title = function() return title end,
        get_IsInTitle = function() return fixture.title end,
        get_IsInLoadGameData = function() return fixture.load_flow end,
        get_IsFinishedLoadScene = function() return fixture.finished end})
    local save = object({get_IsBusy = function() return fixture.busy end,
        get_IsErrorBusy = function() return fixture.save_error end,
        get_LoadGameDataIndex = function() return fixture.load_index end,
        get_IsExistLoadedGameData = function() return fixture.buffer end})
    local gui = object({isTitleMenuOpened = function() return fixture.title_menu end,
        isBusyMenuMain = function() return fixture.main_menu end,
        isBusyMenuStory = function() return fixture.story_menu end,
        isBusyLoad = function() return fixture.load_menu end})
    reframework = {get_game_name = function() return options.game or 're2' end}
    os.clock = function() return fixture.now end
    sdk = {
        get_tdb_version = function() return options.tdb or 70 end,
        PreHookResult = {CALL_ORIGINAL = 123},
        to_int64 = function(value) assert(math.type(value) == 'integer'); return value end,
        find_type_definition = function(name)
            if name == options.missing then return nil end
            return {get_method = function(_, method) return {name = name .. '.' .. method} end}
        end,
        get_managed_singleton = function(name)
            check_read()
            if name == 'app.ropeway.gamemastering.MainFlowManager' then return not fixture.no_flow and flow or nil end
            if name == 'app.ropeway.gamemastering.SaveDataManager' then return save end
            assert(name == 'app.ropeway.gui.GUIMaster'); return not fixture.no_gui and gui or nil
        end,
        hook = function(method, pre, post) fixture.hooks[method.name] = {pre = pre, post = post} end,
    }
    log = {info = function(line)
        if fixture.fail_log then error('logger unavailable') end
        fixture.logs[#fixture.logs + 1] = line
    end}
    re = {on_pre_application_entry = function(entry, callback)
        assert(entry == 'UpdateBehavior'); fixture.update = callback
    end}
    dofile('reframework/diagnostics/re2_coop_title_trace.lua')
    function fixture:invoke(name, retval, args)
        self.in_hook = true
        local hook = assert(self.hooks[name])
        assert(hook.pre(args or {}) == sdk.PreHookResult.CALL_ORIGINAL)
        assert(hook.post(retval) == retval, 'native return value was changed')
        self.in_hook = false
    end
    function fixture:step(count)
        for _ = 1, count or 1 do self.now = self.now + 0.01; self.update() end
    end
    return fixture
end

local fixture = install()
local count = 0
for _ in pairs(fixture.hooks) do count = count + 1 end
assert(count == 17 and fixture.update)
fixture:step()
assert(fixture.logs[#fixture.logs]:find('save_busy=false', 1, true)
    and fixture.logs[#fixture.logs]:find('title_menu=true', 1, true))
local sentinel = {}
for name in pairs(fixture.hooks) do fixture:invoke(name, sentinel, {[3] = 29}) end
assert(fixture.forbidden == 0, 'a native hook re-entered game getters')
local setter = 'app.ropeway.gamemastering.TitleFlow.set_StateValue'
fixture:invoke(setter, false, {[3] = 0xffffffff})
assert(fixture.logs[#fixture.logs - 1]:find('requested_state=-1', 1, true))
fixture:invoke(setter, nil, {[3] = 'invalid'})
assert(fixture.logs[#fixture.logs - 1]:find('requested_state=unavailable', 1, true))
fixture.busy, fixture.save_error, fixture.story_menu = true, true, true
fixture:step()
assert(fixture.logs[#fixture.logs]:find('save_error=true', 1, true)
    and fixture.logs[#fixture.logs]:find('story_menu=true', 1, true))
fixture.throw_method = 'isBusyMenuStory'; fixture:step(30)
assert(fixture.logs[#fixture.logs]:find('story_menu=unavailable', 1, true))
fixture.throw_method, fixture.no_gui = nil, true; fixture:step(30)
assert(fixture.logs[#fixture.logs]:find('title_menu=unavailable', 1, true))
fixture.no_flow = true; fixture:step(30)
assert(fixture.logs[#fixture.logs]:find('sample flow unavailable', 1, true))
fixture.fail_log = true; fixture:invoke(setter, sentinel, {[3] = 29}); fixture:step(30)
fixture.fail_log = false
for _ = 1, 1000 do fixture:invoke(setter, sentinel, {[3] = 29}) end
local after = #fixture.logs
for _ = 1, 100 do fixture:invoke(setter, sentinel, {[3] = 29}) end
assert(#fixture.logs == after, 'call logging was not bounded')
local events = 0
for _, line in ipairs(fixture.logs) do
    if line:find(' enter ', 1, true) or line:find(' leave ', 1, true) then events = events + 1 end
end
assert(events <= 128 and fixture.forbidden == 0)
fixture = install({missing = 'app.ropeway.gui.TitleRBehavior'})
count = 0; for _ in pairs(fixture.hooks) do count = count + 1 end
assert(count == 13 and fixture.update, 'missing optional hooks aborted the remaining trace')
fixture = install({tdb = 71}); assert(next(fixture.hooks) == nil and not fixture.update)
fixture = install({game = 're3'}); assert(next(fixture.hooks) == nil and not fixture.update)
print('Title trace: pass-through hooks, no getter re-entry, bounded logs, failures and build gates passed')
