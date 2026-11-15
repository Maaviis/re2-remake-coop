local callback, report, now, gui_present = nil, nil, 100, true
local ui = {isTitleMenuOpened = true, isBusyMenuMain = false, isBusyMenuStory = false, isBusyLoad = false}
local guard = {active = true, hook_count = 26, writes = {}, events = {}, allowed_load_calls = 0, denied_loads = 0}
package.preload['re2_coop.save_guard'] = function() return {new = function() return guard end} end
package.preload['re2_coop.readonly_loader'] = function()
    return {new = function(g) assert(g == guard); return {phase = 'idle', error = '', poll = function() end} end}
end
os.time = function() return now end
reframework = {get_game_name = function() return 're2' end}
local manager = {call = function(_, name)
    if name == 'get_LoadGameDataIndex' then return 4 end
    assert(name == 'get_IsBusy' or name == 'get_IsExistLoadedGameData'); return false
end}
local flow = {call = function(_, name)
    if name == 'get_IsInTitle' or name == 'get_IsTitleSceneEnvironmentLoaded' then return true end
    assert(name == 'get_IsFinishedLoadScene' or name == 'get_IsInLoadGameData'); return false
end}
local gui = {call = function(_, name) assert(ui[name] ~= nil); return ui[name] end}
sdk = {find_type_definition = function() return nil end, get_managed_singleton = function(name)
    if name == 'app.ropeway.gamemastering.SaveDataManager' then return manager end
    if name == 'app.ropeway.gamemastering.MainFlowManager' then return flow end
    assert(name == 'app.ropeway.gui.GUIMaster'); return gui_present and gui or nil
end}
fs = {glob = function() return {} end}
json = {dump_file = function(path, value) assert(path == 're2_coop_save_guard.json'); report = value end}
log = {error = function(message) error(message) end}
re = {on_pre_application_entry = function(entry, fn) assert(entry == 'UpdateBehavior'); callback = fn end}
dofile('reframework/diagnostics/re2_coop_readonly_save_probe.lua')
callback()
assert(report.gui_available and report.title_open == true and report.main_menu_busy == false
    and report.story_menu_busy == false and report.load_menu_busy == false,
    'native GUI state was replaced by a missing or shadowed reporter variable')
now = 101; ui.isTitleMenuOpened = false; ui.isBusyMenuStory = true; ui.isBusyLoad = true
callback()
assert(report.title_open == false and report.story_menu_busy == true and report.load_menu_busy == true)
now = 102; gui_present = false; callback()
assert(report.gui_available == false and report.title_open == nil and report.story_menu_busy == nil,
    'unavailable GUI was reported as closed')
print('Read-only probe: actual menu queries, changed UI state and unavailable GUI reporting passed')
