local callback, report, now, gui_present = nil, nil, 100, true
local hooks, in_hook, forbidden_reads = {}, false, 0
local function check_read()
    if in_hook then forbidden_reads = forbidden_reads + 1; error('game query inside diagnostic hook') end
end
local ui = {isTitleMenuOpened = true, isBusyMenuMain = false, isBusyMenuStory = false, isBusyLoad = false}
local guard = {active = true, hook_count = 26, writes = {}, events = {}, allowed_load_calls = 0, denied_loads = 0}
package.preload['re2_coop.save_guard'] = function() return {new = function() return guard end} end
package.preload['re2_coop.readonly_loader'] = function()
    return {new = function(g) assert(g == guard); return {phase = 'idle', error = '', poll = function() end} end}
end
os.time = function() return now end
reframework = {get_game_name = function() return 're2' end}
local manager = {call = function(_, name)
    check_read()
    if name == 'get_LoadGameDataIndex' then return 4 end
    assert(name == 'get_IsBusy' or name == 'get_IsExistLoadedGameData'); return false
end}
local flow = {call = function(_, name)
    check_read()
    if name == 'get_IsInTitle' or name == 'get_IsTitleSceneEnvironmentLoaded' then return true end
    assert(name == 'get_IsFinishedLoadScene' or name == 'get_IsInLoadGameData'); return false
end}
local gui = {call = function(_, name) check_read(); assert(ui[name] ~= nil); return ui[name] end}
sdk = {PreHookResult = {CALL_ORIGINAL = 123},
    find_type_definition = function(name)
        return {get_method = function(_, method) return name .. '.' .. method end}
    end,
    hook = function(name, pre, post) hooks[name] = {pre = pre, post = post} end,
    get_managed_singleton = function(name)
    check_read()
    if name == 'app.ropeway.gamemastering.SaveDataManager' then return manager end
    if name == 'app.ropeway.gamemastering.MainFlowManager' then return flow end
    assert(name == 'app.ropeway.gui.GUIMaster'); return gui_present and gui or nil
end}
fs = {glob = function() return {} end}
json = {dump_file = function(path, value) assert(path == 're2_coop_save_guard.json'); report = value end}
log = {error = function(message) error(message) end}
re = {on_pre_application_entry = function(entry, fn) assert(entry == 'UpdateBehavior'); callback = fn end}
dofile('reframework/diagnostics/re2_coop_readonly_save_probe.lua')
local function invoke(hook, retval)
    in_hook = true
    assert(hook.pre() == sdk.PreHookResult.CALL_ORIGINAL)
    assert(hook.post(retval) == retval, 'diagnostic hook changed the native return value')
    in_hook = false
end
local count = 0
for _, hook in pairs(hooks) do count = count + 1; invoke(hook, nil) end
assert(count == 7 and forbidden_reads == 0)
callback()
assert(#report.trace == 14 and report.trace[1].cached == nil,
    'pre-sample hook data was presented as an exact native state')
assert(report.gui_available and report.title_open == true and report.main_menu_busy == false
    and report.story_menu_busy == false and report.load_menu_busy == false,
    'native GUI state was replaced by a missing or shadowed reporter variable')
now = 101; ui.isTitleMenuOpened = false; ui.isBusyMenuStory = true; ui.isBusyLoad = true
local hook = assert(hooks['app.ropeway.gamemastering.SaveDataManager.requestLoadGameData'])
local sentinel = {}
invoke(hook, sentinel)
callback()
local earlier = report.trace[#report.trace].cached
assert(earlier.at == 100 and earlier.busy == false and earlier.buffer == false
    and earlier.loading_flow == false and earlier.load_phase == 'idle')
assert(report.title_open == false and report.story_menu_busy == true and report.load_menu_busy == true)
now = 102; gui_present = false; callback()
assert(report.gui_available == false and report.title_open == nil and report.story_menu_busy == nil,
    'unavailable GUI was reported as closed')
assert(earlier.at == 100, 'a later update changed the cached snapshot of an earlier hook')
for _ = 1, 100 do invoke(hook, false) end
now = 103; callback()
assert(#report.trace == 64 and forbidden_reads == 0, 'unbounded trace or diagnostic getter re-entry')
local clock = os.clock
os.clock = function() error('trace clock unavailable') end
invoke(hook, sentinel)
os.clock = clock
assert(forbidden_reads == 0)
print('Read-only probe: actual UI state, pass-through hooks, no getter re-entry and bounded cached trace passed')
