local callback, frame, report, now, gui_present = nil, nil, nil, 100, true
local hooks, in_hook, forbidden_reads = {}, false, 0
local function check_read()
    if in_hook then forbidden_reads = forbidden_reads + 1; error('game query inside diagnostic hook') end
end
local ui = {isTitleMenuOpened = true, isBusyMenuMain = false, isBusyMenuStory = false, isBusyLoad = false}
local guard = {active = true, hook_count = 26, writes = {}, events = {}, allowed_load_calls = 0, denied_loads = 0,
    allow = function(self, ref) self.policy = {slot_id = ref.slot_id} end}
local binding = {game_pid = 45, run_id = string.rep('a', 32)}
local protected = true
function guard:activate() return protected end
guard.protection = {current = binding, reason = 'ok',
    requested = true,
    poll = function() check_read(); return protected end,
    ready = function() return protected end,
    matches = function(_, value) return protected and type(value) == 'table'
        and value.game_pid == binding.game_pid and value.run_id == binding.run_id end}
package.preload['re2_coop.save_protection'] = function() return {new = function() return guard.protection end} end
local loader = {phase = 'idle', error = '', starts = 0, poll = function() end,
    ready = function() return true end,
    is_in_progress = function(self)
        return self.phase == 'reading_save' or self.phase == 'closing_menu' or self.phase == 'loading'
    end,
    start = function(self, reference, id)
        if self:is_in_progress() then return false, 'load_in_progress' end
        self.starts = self.starts + 1
        guard:allow(reference)
        self.phase, self.request_id = 'reading_save', id
        return true
    end}
package.preload['re2_coop.save_guard'] = function() return {new = function() return guard end} end
package.preload['re2_coop.readonly_loader'] = function()
    return {new = function(g) assert(g == guard); return loader end}
end
local hold, hold_unavailable
package.preload['re2_coop.gameplay_pause'] = function() return {new=function() return {} end} end
package.preload['re2_coop.prepared_load_pause'] = function()
    return {new = function(g, l, run_id)
        assert(g == guard and l == loader)
        if hold_unavailable then error('native pause API unavailable') end
        hold = {active=false, phase='idle', available=false}
        function hold:in_progress() return self.active end
        function hold:arm(id)
            assert(loader.starts == 1, 'pause was armed after the load call')
            self.active, self.id = true, id
            return true
        end
        function hold:cancel(id) assert(id == self.id); self.active=false end
        function hold:poll()
            check_read()
            self.available = self.active and loader.phase == 'scene_loaded'
            self.phase = self.available and 'held' or 'waiting_for_scene'
        end
        function hold:resume(status, command, peer)
            assert(self.available and command.load_request_id == self.id and status.connected == true)
            self.resume_command = command
            self.resume_peer = peer
        end
        function hold:snapshot()
            return {schema=1, scope='prepared_load_native_pause', observed_at=now,
                available=self.available, phase=self.phase, guard_run_id=run_id}
        end
        return hold
    end}
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
local policy_file = 're2_coop_save_policy.json'
local command, published_lobby, campaign_resume, native_peer
fs = {glob = function(pattern)
    return command and pattern:find('save_policy', 1, true) and {policy_file} or {}
end}
json = {dump_file = function(path, value) assert(path == 're2_coop_save_guard.json'); report = value end,
    load_file = function(path)
        if path == 're2_coop_lobby.json' then return published_lobby end
        if path == 're2_coop_campaign_resume.json' then return campaign_resume end
        if path == 're2_coop_native_peer.json' then return native_peer end
        assert(path == policy_file); return command
    end}
log = {error = function(message) error(message) end, info = function() end}
re = {on_pre_application_entry = function(entry, fn) assert(entry == 'UpdateBehavior'); callback = fn end,
    on_frame = function(fn) frame = fn end}
guard.protection.requested = false
dofile('reframework/diagnostics/re2_coop_readonly_save_probe.lua')
assert(callback == nil and frame == nil and next(hooks) == nil, 'stock launch registered the guarded probe')
guard.protection.requested = true
dofile('reframework/diagnostics/re2_coop_readonly_save_probe.lua')
now, protected = 99, false
callback()
assert(report == nil and next(hooks) == nil, 'stale protected token enabled Lua hooks')
now, protected = 100, true
callback()
frame()
callback()
assert(report == nil, 'Lua reported ready before REFramework completed hook installation')
frame()
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
local function submit(id, slot, load, protection)
    now = now + 1
    local proof
    if protection ~= false then proof = protection or binding end
    command = {schema = 1, id = id, at = now, reference = {slot_id = slot}, load = load, protection = proof}
    callback()
end

submit('first', 4, true)
assert(guard.policy.slot_id == 4 and loader.phase == 'reading_save')
for _, phase in ipairs({'reading_save', 'closing_menu', 'loading'}) do
    loader.phase = phase
    submit(phase .. '-start', 7, true)
    assert(guard.policy.slot_id == 4, 'a rejected load replaced the in-flight policy')
    assert(report.command_id == phase .. '-start' and report.command_error == 'load_in_progress')
    submit(phase .. '-arm', 7, false)
    assert(guard.policy.slot_id == 4, 'an arm-only command replaced the in-flight policy')
    assert(report.command_id == phase .. '-arm' and report.command_error == 'load_in_progress')
    assert(report.policy_id == 'first' and report.load_request_id == 'first')
end
loader.phase = 'scene_loaded'
now = now + 1
callback()
assert(guard.policy.slot_id == 4, 'the declined command retried on the next update')
submit('new-arm', 7, false)
assert(report.policy_id == 'new-arm' and report.command_error == '' and report.load_request_id == 'first')
loader.phase = 'idle'
for index, proof in ipairs({false, {game_pid = 46, run_id = binding.run_id},
        {game_pid = 45, run_id = string.rep('b', 32)}}) do
    submit('foreign-' .. index, 4, true, proof)
    assert(report.command_error == 'protected_launch_required' and guard.policy.slot_id == 7
        and loader.phase == 'idle', 'foreign or missing launch binding reached the native loader')
end
protected = false
submit('lost-protection', 4, true)
assert(report.command_error == 'protected_launch_required' and report.protection_active == false
    and report.protection == nil and guard.policy.slot_id == 7)
protected = true

local function stage_prepared(id, attempt)
    now = now + 1
    local digest = string.rep('b', 64)
    local reference = {mode = 1, slot_id = 4, timestamp = '123', scenario = 1}
    published_lobby = {schema = 1, written_at = now, role = 'G', connected = true, game_pid = 45,
        steam_lobby = 'joined', steam_membership = {session_id = string.rep('7', 32), revision = 20},
        lobby = {version = 1, type = 'lobby_state', session_id = 'lobby', data = {
            revision = 5, connected = true, host_id = 'leon', guest_id = 'claire', save_slot = 'scenario:4',
            ready = {leon = true, claire = true},
            load_check = {phase = 'prepared', reason = '', revision = 5, attempt_id = attempt, save_digest = digest,
                admission = 1},
            save_ref = {available = true, mode = 1, slot_id = 4, timestamp = '123', scenario = 1}}}}
    command = {schema = 3, id = id, at = now, load = true, reference = reference, protection = binding,
        lobby_load = {guard_run_id = report.guard_run_id, game_pid = 45, role = 'G',
            membership = {session_id = string.rep('7', 32), revision = 20},
            session_id = 'lobby', revision = 5, attempt_id = attempt, save_digest = digest}}
end

local attempt = string.rep('a', 32)
local faults = {
    expired = function() published_lobby.written_at = now - 4 end,
    other_guard = function() command.lobby_load.guard_run_id = 'old-run' end,
    other_process = function() published_lobby.game_pid = 46 end,
    foreign_protected_process = function()
        published_lobby.game_pid, command.lobby_load.game_pid = 46, 46
    end,
    leaving = function() published_lobby.steam_lobby = 'leaving' end,
    new_membership = function() published_lobby.steam_membership.revision = 21 end,
    new_session = function() published_lobby.lobby.session_id = 'other-lobby' end,
    readiness_withdrawn = function() published_lobby.lobby.data.ready.claire = false end,
    cancel = function() published_lobby.lobby.data.load_check.phase = 'failed' end,
    different_digest = function() published_lobby.lobby.data.load_check.save_digest = string.rep('c', 64) end,
    different_reference = function() published_lobby.lobby.data.save_ref.timestamp = '124' end,
    wrong_schema = function() command.schema = 1 end,
    missing_scope = function() command.lobby_load = nil end,
}
for fault, apply_fault in pairs(faults) do
    stage_prepared(fault, attempt)
    apply_fault()
    callback()
    assert(report.command_id == fault and report.command_error == 'lobby_load_no_longer_prepared', fault)
    assert(loader.starts == 1 and guard.policy.slot_id == 7 and report.prepared_load == nil, fault)
end
local prepared_id = string.rep('e', 32)
local function grant(id, permit)
    now = now + 1
    published_lobby.written_at = now
    published_lobby.prepared_start = permit and {id=id, before=now+3} or nil
    local check = published_lobby.lobby.data.load_check
    check.phase, check.start = 'starting', {H = string.rep('8', 32), G = id}
end
stage_prepared(string.rep('d', 32), attempt)
command.schema = 2
callback()
assert(loader.starts == 1 and report.command_error == 'prepared_load_requires_staging')

stage_prepared(string.rep('c', 32), attempt)
grant(command.id, true)
callback()
assert(loader.starts == 1 and report.command_error == 'prepared_load_not_staged')

stage_prepared(string.rep('b', 32), attempt)
callback()
assert(report.staged_load and loader.starts == 1)
grant(command.id, true)
protected = false; callback(); protected = true
assert(loader.starts == 1 and report.command_error == 'protected_launch_required')

stage_prepared(prepared_id, attempt)
callback()
assert(report.staged_load.id == prepared_id and loader.starts == 1 and guard.policy.slot_id == 7)
grant(prepared_id, false); callback()
assert(report.staged_load.id == prepared_id and loader.starts == 1)
grant(prepared_id, true); published_lobby.prepared_start.before = now; callback()
assert(report.staged_load.id == prepared_id and loader.starts == 1)
grant(prepared_id, true); callback()
assert(loader.starts == 2 and report.command_error == '' and report.load_request_id == prepared_id)
assert(report.prepared_load.scope.attempt_id == attempt and report.prepared_load.reference.available)
assert(report.prepared_load.reference.slot_id == 4)
loader.phase = 'scene_loaded'
submit('intervening-arm', 7, false)
assert(report.command_error == 'load_pause_in_progress' and report.prepared_load ~= nil)
assert(report.load_hold.available == true and report.load_hold.phase == 'held')
stage_prepared(prepared_id, attempt)
callback()
assert(loader.starts == 2 and report.command_error == 'load_pause_in_progress')
stage_prepared(string.rep('f', 32), string.rep('d', 32))
callback()
assert(loader.starts == 2 and report.command_error == 'load_pause_in_progress')
assert(report.prepared_load.scope.attempt_id == attempt)
loader.phase = 'scene_loaded'
submit('manual-native-load', 4, true)
assert(loader.starts == 2 and report.command_error == 'load_pause_in_progress')
campaign_resume = {schema=1, load_request_id=prepared_id, at=now, lobby_load=report.prepared_load.scope}
native_peer = {schema=1, game_pid=45}
now = now + 1
callback()
assert(hold.resume_command == campaign_resume, 'native loader did not consume the campaign resume permit')
assert(hold.resume_peer == native_peer, 'native loader did not check the native peer report')
local polls = 0
hold.poll = function() check_read(); polls = polls + 1 end
callback(); callback()
assert(polls == 2, 'native hold was throttled to one poll per second')
hold_unavailable = true
dofile('reframework/diagnostics/re2_coop_readonly_save_probe.lua')
now = now + 1; command=nil; callback()
frame(); frame(); callback()
stage_prepared(string.rep('f',32),string.rep('d',32)); callback()
assert(loader.starts == 2 and report.command_error == 'native_load_pause_unavailable')
print('Read-only probe: UI, pass-through hooks, prepared identity, held-load exclusion and native pause availability passed')
