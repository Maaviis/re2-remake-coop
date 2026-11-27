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
local mount_ready
function guard:sync_campaign_mount() return mount_ready end
function guard:campaign_ready(v) return v and mount_ready and v.campaign_namespace==mount_ready end
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
local enemy_report, enemy_reads, after_enemy_capture = nil, 0, nil
local door_report, door_reads = nil, 0
local item_report, item_reads = nil, 0
package.preload['re2_coop.gameplay_pause'] = function() return {new=function() return {} end} end
package.preload['re2_coop.campaign_pose_scope'] = function() return {read_area=function() end} end
package.preload['re2_coop.enemy_state'] = function()
    return {new=function() return {capture=function()
        enemy_reads=enemy_reads+1
        if after_enemy_capture then after_enemy_capture() end
        return {checkpoint={scenario=1}}, 'ok'
    end} end}
end
package.preload['re2_coop.door_state'] = function()
    return {new=function() return {capture=function()
        door_reads=door_reads+1
        return {scenario=1,door_count=0,doors={}}, 'ok'
    end} end}
end
package.preload['re2_coop.world_item_state'] = function()
    return {new=function() return {capture=function()
        item_reads=item_reads+1
        return {scenario=1,unbound=0,groups={}}, 'ok'
    end} end}
end
package.preload['re2_coop.interrupted_state'] = function()
    return dofile('reframework/autorun/re2_coop/interrupted_state.lua')
end
package.preload['re2_coop.prepared_load_pause'] = function()
    return {new = function(g, l, run_id)
        assert(g == guard and l == loader)
        if hold_unavailable then error('native pause API unavailable') end
        hold = {active=false, phase='idle', available=false}
        function hold:in_progress() return self.active end
        function hold:new_game_admitted() return self.active end
        function hold:arm(id)
            assert(loader.starts == 1, 'pause was armed after the load call')
            self.active, self.id = true, id
            return true
        end
        function hold:cancel(id) assert(id == self.id); self.active=false end
        function hold:poll(_, peer, peer_release)
            check_read()
            self.observed_peer = peer
            self.observed_peer_release = peer_release
            self.available = not self.interruption and self.active and loader.phase == 'scene_loaded'
            self.phase = self.interruption and 'interrupted' or (self.available and 'held' or 'waiting_for_scene')
        end
        function hold:resume(status, command, peer)
            assert(self.available and command.load_request_id == self.id and status.connected == true)
            self.resume_command = command
            self.resume_peer = peer
        end
        function hold:snapshot()
            return {schema=1, scope='prepared_load_native_pause', observed_at=now,
                available=self.available, phase=self.phase, guard_run_id=run_id, load_request_id=self.id,
                native_phase=self.interruption and 'held', interruption=self.interruption}
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
local command, published_lobby, campaign_resume, native_peer, peer_release
fs = {glob = function(pattern)
    return command and pattern:find('save_policy', 1, true) and {policy_file} or {}
end}
json = {dump_file = function(path, value)
        if path == 're2_coop_interrupted_enemy_state.json' then enemy_report = value; return end
        if path == 're2_coop_interrupted_door_state.json' then door_report = value; return end
        if path == 're2_coop_interrupted_world_items.json' then item_report = value; return end
        assert(path == 're2_coop_save_guard.json'); report = value
    end,
    load_file = function(path)
        if path == 're2_coop_lobby.json' then return published_lobby end
        if path == 're2_coop_campaign_resume.json' then return campaign_resume end
        if path == 're2_coop_native_peer.json' then return native_peer end
        if path == 're2_coop_campaign_peer_release.json' then return peer_release end
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
guard.protection.current.runtime = true
submit('runtime-manual-load', 4, true)
assert(loader.starts == 1 and report.command_error == 'runtime_campaign_required')
stage_prepared(string.rep('9', 32), attempt)
callback()
assert(loader.starts == 1 and report.command_error == 'lobby_load_no_longer_prepared')
guard.protection.current.runtime = nil
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
assert(hold.observed_peer == native_peer, 'native pause polling did not receive the peer report')
hold.phase = 'released'
peer_release = {schema=1, game_pid=45, load_request_id=prepared_id}
now = now + 1
callback()
assert(hold.observed_peer_release == peer_release, 'native pause polling did not receive the peer release')
local previous_peer = native_peer
native_peer = nil
now = now + 1
callback()
assert(hold.observed_peer == previous_peer, 'a read gap discarded the peer report before its timestamp could expire')
native_peer = {schema=1, game_pid=45, role='-', snapshot_epoch=''}
now = now + 1
callback()
assert(hold.observed_peer == native_peer, 'native pause polling did not receive the connection loss')
assert(enemy_reads == 0 and enemy_report == nil and door_reads == 0 and door_report == nil)
assert(item_reads == 0 and item_report == nil)
hold.interruption = {session_id=published_lobby.lobby.session_id, attempt_id=attempt, release_id=string.rep('e',32),
    game_pid=45, role='H', protection_run_id=binding.run_id, at=now, area={scenario=1,map=350,area=0}}
local proof = hold.interruption
now = now + 1
callback()
assert(enemy_reads == 1 and enemy_report.available and enemy_report.observed_at == now)
assert(enemy_report.state.interruption.scope == proof and enemy_report.state.interruption.load_request_id == prepared_id)
assert(enemy_report.state.interruption.guard_run_id == report.guard_run_id)
assert(door_reads == 1 and door_report.available and door_report.observed_at == now)
assert(door_report.state.interruption.scope == proof and door_report.state.interruption.load_request_id == prepared_id)
local first_report, first_door_report = enemy_report, door_report
assert(item_reads == 1 and item_report.available and item_report.state.interruption.scope == proof)
local first_item_report = item_report
after_enemy_capture = function() hold.interruption = nil end
now = now + 1
callback()
assert(enemy_reads == 2 and enemy_report == first_report and not report.load_hold.interruption,
    'lost native pause renewed the interruption or enemy observation')
assert(door_reads == 1 and door_report == first_door_report, 'the door reader used a lost pause')
assert(item_reads == 1 and item_report == first_item_report, 'the item reader used a lost pause')
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

local fresh_calls, fresh_polls = 0, 0
package.loaded['re2_coop.campaign_pose_scope'].supports_area = function() return true end
package.preload['re2_coop.new_game'] = function()
    local m = dofile('reframework/autorun/re2_coop/new_game.lua')
    m.new = function()
        return {ready=function() return true end, start=function(_, selection, id)
            assert(guard.policy == nil and selection.difficulty=='HARD' and selection.scenario=='CLAIRE_A')
            fresh_calls = fresh_calls + 1
            loader.request_id, loader.new_game, loader.phase = id,selection,'closing_menu'
            return true
        end, poll=function()
            fresh_polls=fresh_polls+1
            loader.phase='loading'
        end, world=function()
            return {request_id=loader.request_id,observed_at=now,scenario=1,difficulty=2,map=23,area=4}
        end}
    end
    return m
end
loader.phase, loader.starts, loader.request_id, loader.new_game = 'idle',1,nil,nil
guard.policy, hold_unavailable, campaign_resume, command = nil,false,nil,nil
guard.protection.current.runtime = true
dofile('reframework/diagnostics/re2_coop_readonly_save_probe.lua')
now = now + 1; callback(); frame(); frame(); callback()
assert(report.new_game_supported)
local function prepare_new(id,attempt)
    stage_prepared(id,attempt)
    command.schema,command.reference,command.new_game = 4,nil,{scenario='CLAIRE_A',difficulty='HARD'}
    local data = published_lobby.lobby.data
    data.load_check.campaign_start, data.save_ref, data.save_slot = true,nil,nil
    data.new_game = {scenario='CLAIRE_A',difficulty='HARD'}
end
local invalid_count=0
local function invalid(change)
    invalid_count=invalid_count+1
    prepare_new(string.format('%032x',invalid_count),attempt)
    change(); callback()
    assert(fresh_calls==0 and not report.staged_load and guard.policy==nil)
    now=now+1
end
invalid(function() command.reference={slot_id=4} end)
invalid(function() published_lobby.lobby.data.save_slot='scenario:4' end)
invalid(function() published_lobby.lobby.data.load_check.campaign_start=false end)
invalid(function() published_lobby.lobby.data.new_game.difficulty='NORMAL' end)
prepare_new(string.rep('5',32),attempt); callback()
assert(report.staged_load)
grant(command.id,true)
command.new_game.scenario, published_lobby.lobby.data.new_game.scenario = 'LEON_A','LEON_A'
callback(); assert(report.command_error=='prepared_load_not_staged' and fresh_calls==0)
local valid_id = string.rep('2',32)
guard.campaign_mode=true
binding.campaign_namespace=string.rep('e',32)
prepare_new(string.rep('3',32),attempt); callback()
assert(not report.staged_load and not report.campaign_mount_ready and not report.new_game_supported,
    'published direct readiness before mount readback')
mount_ready=binding.campaign_namespace
prepare_new(valid_id,string.rep('4',32)); callback()
assert(report.campaign_mount_ready==mount_ready and report.protection.campaign_namespace==mount_ready)
assert(report.staged_load and not report.new_game_world)
grant(valid_id,true); callback()
assert(fresh_calls==1 and loader.starts==1 and guard.policy==nil and report.allowed_slot==-1)
assert(report.prepared_load.new_game.difficulty=='HARD' and not report.prepared_load.reference)
assert(not report.new_game_world and fresh_polls==0)
callback()
assert(fresh_polls==1,'same-second follow-up UpdateBehavior did not process the already admitted start')
loader.phase,now='scene_loaded',now+1
callback()
assert(report.new_game_world and report.new_game_world.request_id==valid_id and report.load_hold.available)
now=now+1; callback(); assert(fresh_calls==1)
print('Schema 4 validates both staged choices, forbids stale/slot admission, holds and emits a native world sample')

-- Schema 5 uses the real receipt validator and an explicit checkpoint loader
-- argument. The SDK/engine and native guard effects remain test doubles (E2).
local cp_admission=dofile('reframework/autorun/re2_coop/checkpoint_admission.lua')
package.preload['re2_coop.checkpoint_admission']=function() return cp_admission end
local cp_documents={}
local previous_read=json.load_file
json.load_file=function(path)
    if cp_documents[path] then return cp_documents[path] end
    return previous_read(path)
end
local cp_admissions=0
function guard:allow_checkpoint(reference,preparation,run)
    cp_admission.read(self,reference,preparation,run,now)
    cp_admissions=cp_admissions+1
    self.policy={mode=reference.mode,slot_id=reference.slot_id,timestamp=reference.timestamp,scenario=reference.scenario}
end
function guard:revoke_checkpoint() self.policy=nil end
loader.supports_checkpoint=true
loader.start=function(self,reference,id,checkpoint)
    assert(checkpoint and checkpoint.preparation_id==command.preparation_id
        and checkpoint.guard_run_id==command.lobby_load.guard_run_id,
        'schema 5 fell back to ordinary admission')
    guard:allow_checkpoint(reference,checkpoint.preparation_id,checkpoint.guard_run_id)
    self.starts,self.request_id,self.phase=self.starts+1,id,'reading_save'
    guard.allowed_load_calls=1
    return true
end
local function cp_reload()
    guard.policy,guard.allowed_load_calls=nil,0
    loader.phase,loader.new_game,loader.starts='idle',nil,1
    command,campaign_resume=nil,nil
    dofile('reframework/diagnostics/re2_coop_readonly_save_probe.lua')
    now=now+1;callback();frame();frame();callback()
    assert(report.checkpoint_supported)
end
local function cp_prepare(id,attempt)
    stage_prepared(id,attempt)
    command.schema,command.new_game,command.checkpoint,command.preparation_id=5,nil,
        {namespace=string.rep('6',32),digest=command.lobby_load.save_digest},string.rep('7',32)
    command.reference={mode=1,slot_id=0,timestamp='639001000000000000',scenario=1}
    command.lobby_load.session_id=string.rep('5',32)
    published_lobby.lobby.session_id=command.lobby_load.session_id
    local data=published_lobby.lobby.data
    data.save_ref,data.save_slot,data.new_game=nil,nil,nil
    data.settings={coop_checkpoint={namespace=command.checkpoint.namespace,digest=command.checkpoint.digest,
        scenario=1,difficulty=1,saved_at='2026-11-27 12:00:00'}}
    data.load_check.campaign_start,data.load_check.checkpoint_version=true,1
    local workspace={schema=1,at=now,phase='ready',request_id=command.preparation_id,game_pid=45,
        guard_run_id=command.lobby_load.guard_run_id,lobby_revision=data.revision,
        selection=command.checkpoint,native_reference=command.reference,
        protection={game_pid=45,run_id=binding.run_id,campaign_namespace=mount_ready},
        scope={game_pid=45,role='G',session_id=command.lobby_load.session_id,
            membership=command.lobby_load.membership},
        files={['data000.bin']=string.rep('f',64),['data021Slot.bin']=string.rep('f',64),['data00-1.bin']=string.rep('f',64)}}
    cp_documents['re2_coop_checkpoint_workspace.json']=workspace
    cp_documents['re2_coop_native_save_guard.json']={schema=1,at=now,active=true,reason='ok',
        source='steam_storage_guard',game_pid=45,run_id=binding.run_id,campaign_namespace=mount_ready,
        app_id=883710,build_id=11636119,interface='014',guarded_methods=10,
        checkpoint_import={request_id=command.preparation_id,workspace=mount_ready,
            archive_namespace=command.checkpoint.namespace,generation=command.checkpoint.digest,
            phase='ready',file_index=3,native_result=1}}
    cp_documents['re2_coop_checkpoint_catalog.json']={schema=1,at=now,phase='ready',
        request_id=command.preparation_id,game_pid=45,run_id=binding.run_id,
        guard_run_id=command.lobby_load.guard_run_id,workspace=mount_ready,
        archive_namespace=command.checkpoint.namespace,generation=command.checkpoint.digest,
        reference=command.reference}
end
local function cp_fresh()
    for _,receipt in pairs(cp_documents) do receipt.at=now end
end
cp_reload()
for i,change in ipairs({
    function() command.schema=3 end,
    function() command.new_game={scenario='CLAIRE_A',difficulty='NORMAL'} end,
    function() command.checkpoint={namespace=string.rep('6',32),digest=string.rep('0',64)} end,
    function() command.preparation_id=string.rep('0',32) end,
    function() published_lobby.lobby.data.load_check.checkpoint_version=nil end,
    function() cp_documents['re2_coop_checkpoint_catalog.json'].at=now-4 end}) do
    cp_prepare(string.format('%032x',i+100),string.rep('4',32));change();callback()
    assert(not report.staged_load and cp_admissions==0 and loader.starts==1,
        'invalid checkpoint request reached admission')
end
cp_prepare(string.rep('b',32),string.rep('4',32));callback()
assert(report.staged_load.preparation_id==command.preparation_id and cp_admissions==0)
assert(report.staged_load.reference.slot_id==0 and report.staged_load.checkpoint.digest==command.checkpoint.digest)
grant(command.id,true);cp_fresh()
-- Replacing every receipt and the policy is still forbidden in the same staged attempt.
command.preparation_id=string.rep('a',32)
cp_documents['re2_coop_checkpoint_workspace.json'].request_id=command.preparation_id
cp_documents['re2_coop_native_save_guard.json'].checkpoint_import.request_id=command.preparation_id
cp_documents['re2_coop_checkpoint_catalog.json'].request_id=command.preparation_id
callback()
assert(report.command_error=='prepared_load_not_staged' and cp_admissions==0 and loader.starts==1)
cp_reload();cp_prepare(string.rep('c',32),string.rep('4',32));callback()
grant(command.id,true);cp_fresh()
cp_documents['re2_coop_checkpoint_workspace.json'].at=now-4;callback()
assert(cp_admissions==0 and loader.starts==1 and report.command_error=='lobby_load_no_longer_prepared')
cp_fresh();now=now+1;callback()
assert(cp_admissions==0,'rejected checkpoint policy revived without a new attempt')
cp_reload();cp_prepare(string.rep('d',32),string.rep('4',32));callback()
assert(report.staged_load and cp_admissions==0)
grant(command.id,true);cp_fresh();callback()
assert(cp_admissions==1 and loader.starts==2 and report.command_error=='')
assert(report.prepared_load.checkpoint.digest==command.checkpoint.digest
    and report.prepared_load.preparation_id==command.preparation_id
    and report.prepared_load.reference.slot_id==0 and not report.prepared_load.new_game)
now=now+1;callback();assert(cp_admissions==1,'checkpoint load repeated')
print('Schema 5: fresh receipt staging, nonce pinning, loss, paired permit and explicit checkpoint load passed (E2)')
