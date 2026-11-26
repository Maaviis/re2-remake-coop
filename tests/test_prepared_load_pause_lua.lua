local M = dofile('reframework/autorun/re2_coop/prepared_load_pause.lua')
local id = string.rep('d', 32)
local function fixture()
    local f = {now = 100}
    f.reference = {mode=1, slot_id=4, timestamp='639300365010000000', scenario=1}
    f.scope = {game_pid=10, role='H', session_id='lobby', revision=5, attempt_id=string.rep('c',32),
        save_digest=string.rep('f',64), guard_run_id='native-H',
        membership={session_id=string.rep('a',32), revision=7}}
    f.guard = {active=true, hook_count=26, denied_loads=0, writes={},
        policy={mode=1, slot_id=4, timestamp=f.reference.timestamp, scenario=1}}
    f.protected = true
    f.guard.protection = {current={game_pid=10, run_id=string.rep('a',32)}}
    function f.guard.protection:ready() return f.protected end
    function f.guard.protection:matches(binding)
        return self:ready() and binding.game_pid == self.current.game_pid and binding.run_id == self.current.run_id
    end
    f.loader = {phase='reading_save', request_id=id, error=''}
    f.pause = {phase='idle', verified=false, request_id='', requests=0, returns=0, ready=false}
    function f.pause:poll()
        if f.poll_error then error('native state unreadable') end
        return self.verified
    end
    function f.pause:request(request)
        self.requests = self.requests + 1
        if not self.ready then return false, 'gameplay_not_ready' end
        self.phase, self.request_id = 'requesting', request
        return true
    end
    function f.pause:release(request)
        assert(request == self.request_id and self.phase == 'held')
        self.returns, self.phase, self.verified = self.returns + 1, 'returning', false
        return true
    end
    function f.pause:rehold(request)
        assert(request == self.request_id and self.phase == 'released')
        self.reholds = (self.reholds or 0) + 1
        if f.rehold_error then return false, f.rehold_error end
        self.phase, self.verified = 'requesting', false
        return true
    end
    f.status = {schema=1, written_at=100, connected=true, game_pid=10, role='H', steam_lobby='owned',
        steam_membership={session_id=string.rep('a',32), revision=7},
        lobby={version=1, type='lobby_state', session_id='lobby', data={connected=true,
            save_slot='scenario:4', save_ref={available=true, mode=1, slot_id=4, timestamp=f.reference.timestamp, scenario=1},
            load_check={phase='prepared', reason='', revision=5, attempt_id=string.rep('c',32), save_digest=string.rep('f',64)}}}}
    f.current_area = {scenario=1, map=42, area=8}
    f.hold = M.new(f.guard, f.loader, 'native-H', {pause=f.pause, clock=function() return f.now end,
        read_area=function() return f.current_area end, read_world=function() return f.world end,
        new_game=dofile('reframework/autorun/re2_coop/new_game.lua')})
    function f:arm() assert(self.hold:arm(id,self.scope,self.reference)) end
    function f:held()
        self:arm()
        self.loader.phase, self.pause.ready = 'loading', true
        assert(not self.hold:poll(self.status))
        assert(self.pause.requests == 1 and self.pause.request_id == id)
        self.pause.phase, self.pause.verified, self.loader.phase = 'held', true, 'scene_loaded'
        assert(self.hold:poll(self.status))
    end
    return f
end

local f = fixture(); f:arm()
assert(not f.hold:poll(f.status) and f.pause.requests == 0)
f.loader.phase = 'loading'
assert(not f.hold:poll(f.status) and f.pause.requests == 1)
f.pause.ready = true
assert(not f.hold:poll(f.status) and f.pause.requests == 2)
f.pause.phase, f.pause.verified = 'held', true
assert(not f.hold:poll(f.status), 'menu hold was confused with completed loading')
f.loader.phase = 'scene_loaded'
assert(f.hold:poll(f.status))
local snapshot = f.hold:snapshot()
assert(snapshot.load_request_id == id and snapshot.pause_id == id and snapshot.native_phase == 'held'
    and snapshot.scope == 'prepared_load_native_pause' and snapshot.available == true)
print('ok - asks for the native pause during loading, confirms it only after the matching scene load')

f = fixture(); f:arm()
f.status.connected = false
f.pause.ready, f.loader.phase = true, 'loading'
f.hold:poll(f.status)
assert(f.pause.requests == 1, 'a lost link left the newly loaded world running')
f.pause.phase, f.pause.verified, f.loader.phase = 'held', true, 'scene_loaded'
assert(not f.hold:poll(f.status) and f.pause.returns == 0)
f.status.connected = true
assert(f.hold:poll(f.status))
f.status.steam_membership.revision = 8
assert(not f.hold:poll(f.status) and f.pause.phase == 'held' and f.pause.returns == 0)
print('ok - link or membership loss invalidates evidence while retaining the owned native pause')

for _, reason in ipairs({'selection_changed','local_source_unavailable','guest_source_unavailable','guest_ack_expired'}) do
    f=fixture(); f:held()
    f.status.lobby.data.load_check.phase, f.status.lobby.data.load_check.reason='failed',reason
    f.status.lobby.data.save_ref={available=false}
    assert(f.hold:poll(f.status), 'same admitted load was lost during a permitted catalog transition')
    f.status.lobby.data.load_check.attempt_id=string.rep('e',32)
    assert(not f.hold:poll(f.status) and f.pause.returns == 0)
end
print('ok - catalog transition keeps only the exact admitted attempt')

f=fixture(); f:held()
f.now=104
assert(not f.hold:poll(f.status), 'expired Steam state retained pause evidence')
f.now=99
assert(not f.hold:poll(f.status), 'future Steam state retained pause evidence')
f.now=100; f.guard.policy.timestamp='639300365010000001'
assert(not f.hold:poll(f.status))
f.guard.policy.timestamp=f.reference.timestamp; f.guard.writes.autosave=1
assert(not f.hold:poll(f.status) and f.pause.returns == 0)
print('ok - stale state, changed native policy or save attempt removes evidence without resuming')

for _, fault in ipairs({'lost', 'other_process', 'other_run'}) do
    f=fixture(); f:held()
    if fault == 'lost' then f.protected = false
    elseif fault == 'other_process' then f.guard.protection.current.game_pid = 11
    else f.guard.protection.current.run_id = string.rep('b',32) end
    assert(not f.hold:poll(f.status), 'changed protection retained native pause evidence: ' .. fault)
    assert(f.pause.phase == 'held' and f.pause.returns == 0)
end
print('ok - lost or replaced save protection removes evidence while retaining the pause')

f=fixture(); f:held()
f.loader.request_id=string.rep('e',32)
assert(not f.hold:poll(f.status) and f.hold.reason == 'native_load_changed')
assert(not f.hold:arm(string.rep('e',32),f.scope,f.reference))
assert(f.pause.returns == 0)
f=fixture(); f:held(); f.pause.phase='lost'; f.pause.reason='pause_ended_externally'
assert(not f.hold:poll(f.status) and f.hold.phase == 'lost')
print('ok - changed load or manually ended pause never yields a held report')

f=fixture(); f:arm()
f.scope.game_pid, f.scope.membership.revision, f.reference.slot_id=999,99,7
f.loader.phase,f.pause.ready='loading',true
f.hold:poll(f.status)
f.loader.phase,f.pause.phase,f.pause.verified='scene_loaded','held',true
assert(f.hold:poll(f.status), 'caller mutation changed an admitted binding')
f.poll_error=true
assert(not f.hold:poll(f.status) and f.hold.reason == 'native_pause_poll_failed')
assert(f.pause.returns == 0)
print('ok - copied admission and unreadable native pause do not permit aliasing or release')

f=fixture(); f:arm(); assert(f.hold:cancel(id))
assert(not f.hold:arm(id,f.scope,f.reference), 'retired admission replayed')
assert(f.hold:arm(string.rep('e',32),f.scope,f.reference))
f=fixture(); f:held(); assert(not f.hold:cancel(id) and f.pause.returns == 0)
print('ok - failed pre-load admission can cancel, an owned active pause cannot be silently cancelled')

local function campaign()
    local f = fixture()
    f:held()
    f.status.lobby.data.load_check.campaign_start = true
    f.peer = {schema=1, at=f.now, game_pid=10, role='H', revision=7, snapshot_epoch=string.rep('a', 16)}
    f.resume = {schema=1, at=f.now, load_request_id=id, lobby_load=f.scope, snapshot_epoch=f.peer.snapshot_epoch,
        release_id=string.rep('e', 32)}
    f.evidence = {schema=1, at=f.now, game_pid=10, load_request_id=id, snapshot_epoch=f.peer.snapshot_epoch,
        release_id=f.resume.release_id}
    return f
end

f = campaign()
assert(f.hold:resume(f.status, f.resume, f.peer))
assert(f.pause.returns == 1 and f.hold:snapshot().phase == 'releasing')
assert(f.hold:snapshot().campaign == nil, 'release request does not authorize playback')
assert(not f.hold:resume(f.status, f.resume, f.peer) and f.pause.returns == 1)
f.hold:poll(f.status, f.peer)
assert(f.hold:snapshot().phase == 'releasing')
f.pause.phase, f.pause.verified = 'released', true
f.pause.released_player, f.pause.released_scene = '31', '32'
f.hold:poll(f.status, f.peer)
assert(f.hold:snapshot().phase == 'released')
assert(f.hold:snapshot().release.id == f.resume.release_id)
assert(f.hold:snapshot().campaign == nil, 'local native release alone authorized playback')
f.hold:poll(f.status, f.peer, f.evidence)
local playback = assert(f.hold:snapshot().campaign)
assert(playback.session_id == f.scope.session_id and playback.snapshot_epoch == f.peer.snapshot_epoch)
assert(playback.game_pid == f.scope.game_pid and playback.role == f.scope.role and playback.revision == 7)
assert(playback.local_player == '31' and playback.local_scene == '32')
assert(playback.attempt_id == f.scope.attempt_id)
assert(playback.scenario == f.reference.scenario)
assert(playback.protection_run_id == f.guard.protection.current.run_id)
playback.revision = 99
assert(f.hold:snapshot().campaign.revision == 7, 'published binding aliases the admitted scope')
assert(not f.hold:resume(f.status, f.resume, f.peer) and f.pause.returns == 1)
print('ok - publishes campaign playback only after both native releases')

for _, stale in ipairs({
    function(e) e.at = e.at - 1 end,
    function(e) e.at = e.at + 1 end,
    function(e) e.game_pid = 11 end,
    function(e) e.load_request_id = string.rep('a', 32) end,
    function(e) e.snapshot_epoch = string.rep('b', 16) end,
    function(e) e.release_id = string.rep('c', 32) end,
}) do
    local missing = campaign()
    assert(missing.hold:resume(missing.status, missing.resume, missing.peer))
    missing.pause.phase, missing.pause.verified = 'released', true
    stale(missing.evidence)
    missing.hold:poll(missing.status, missing.peer, missing.evidence)
    assert(missing.hold:snapshot().campaign == nil, 'foreign or stale proof authorized playback')
    for second = 1, 9 do
        missing.now, missing.peer.at = 100 + second, 100 + second
        missing.hold:poll(missing.status, missing.peer)
        assert(missing.hold:snapshot().phase == 'released')
    end
    missing.now, missing.peer.at = 110, 110
    missing.evidence = {schema=1, at=110, game_pid=10, load_request_id=id,
        snapshot_epoch=missing.resume.snapshot_epoch, release_id=missing.resume.release_id}
    missing.hold:poll(missing.status, missing.peer, missing.evidence)
    assert(missing.hold:snapshot().phase == 'reholding')
    assert(missing.hold:snapshot().release == nil and missing.hold:snapshot().campaign == nil)
    assert(missing.hold:snapshot().reason == 'campaign_peer_release_unconfirmed')
    missing.pause.phase, missing.pause.verified = 'held', true
    missing.hold:poll(missing.status, missing.peer, missing.evidence)
    assert(missing.hold:snapshot().phase == 'interrupted')
end
print('ok - missing peer release reacquires native pause even while the Steam link remains healthy')

local ongoing = campaign()
assert(ongoing.hold:resume(ongoing.status, ongoing.resume, ongoing.peer))
ongoing.pause.phase, ongoing.pause.verified = 'released', true
ongoing.hold:poll(ongoing.status, ongoing.peer, ongoing.evidence)
ongoing.now, ongoing.peer.at, ongoing.evidence.at = 103, 103, 103
ongoing.hold:poll(ongoing.status, ongoing.peer, ongoing.evidence)
assert(ongoing.hold:snapshot().campaign and ongoing.pause.reholds == nil)
for second = 104, 107 do
    ongoing.now, ongoing.peer.at = second, second
    ongoing.hold:poll(ongoing.status, ongoing.peer, ongoing.evidence)
end
assert(ongoing.hold:snapshot().phase == 'reholding' and ongoing.hold:snapshot().campaign == nil)
assert(ongoing.hold:snapshot().reason == 'campaign_peer_release_unconfirmed')
print('ok - the last valid peer release cannot keep campaign playback active indefinitely')

f.peer.snapshot_epoch = string.rep('b', 16)
f.hold:poll(f.status, f.peer)
assert(f.hold:snapshot().campaign == nil, 'the prior connection still authorizes campaign playback')
assert(f.pause.reholds == 1 and f.hold:snapshot().phase == 'reholding')
f.pause.phase, f.pause.verified = 'held', true
f.peer.snapshot_epoch = f.resume.snapshot_epoch
f.hold:poll(f.status, f.peer)
assert(f.hold:snapshot().phase == 'interrupted' and not f.hold:snapshot().available)
local interrupted = assert(f.hold:snapshot().interruption)
f.guard.writes.autosave = 1
assert(f.hold:snapshot().interruption, 'a blocked gameplay autosave hid the interrupted pause proof')
f.guard.writes.autosave = nil
assert(interrupted.at == f.now and interrupted.game_pid == f.scope.game_pid and interrupted.role == f.scope.role)
assert(interrupted.session_id == f.scope.session_id and interrupted.attempt_id == f.scope.attempt_id)
assert(interrupted.release_id == f.resume.release_id and interrupted.area.map == 42 and interrupted.area.area == 8)
interrupted.area.map = 9
assert(f.hold:snapshot().interruption.area.map == 42)
f.current_area.scenario = 2
assert(not f.hold:snapshot().interruption, 'an unrelated scenario supplied interruption evidence')
f.current_area.scenario, f.protected = 1, false
assert(not f.hold:snapshot().interruption, 'proof survived save protection loss')
f.protected = true
assert(not f.hold:resume(f.status, f.resume, f.peer) and f.pause.returns == 1, 'old command replayed after rehold')
f.pause.phase, f.pause.verified = 'lost', false
f.hold:poll(f.status, f.peer)
assert(f.hold:snapshot().phase == 'rehold_failed' and f.pause.reholds == 1)
assert(f.hold:snapshot().release_loss_reason == 'campaign_peer_lost',
    'final native pause loss erased the cause that first withdrew the campaign')
assert(not f.hold:snapshot().interruption)

f = campaign()
assert(f.hold:resume(f.status, f.resume, f.peer))
f.hold:poll(f.status, nil)
assert(f.hold:snapshot().phase == 'releasing' and f.pause.reholds == nil)
f.pause.phase, f.pause.verified = 'released', true
f.hold:poll(f.status, f.peer)
assert(f.hold:snapshot().phase == 'reholding' and f.hold:snapshot().campaign == nil,
    'link loss while returning was forgotten when the connection recovered')

f = campaign()
assert(f.hold:resume(f.status, f.resume, f.peer))
f.pause.phase, f.pause.verified = 'released', true
f.now = 102
f.rehold_error = 'gameplay_not_ready'
f.hold:poll(f.status, f.peer)
assert(f.hold:snapshot().phase == 'rehold_pending' and f.pause.reholds == 1)
f.now = 105
f.hold:poll(f.status, f.peer)
assert(f.hold:snapshot().phase == 'rehold_failed' and f.hold:snapshot().reason == 'campaign_rehold_timeout')
assert(f.pause.reholds == 1 and f.hold:snapshot().campaign == nil)
print('ok - stale or changed links revoke playback, rehold once and forbid resume replay')

local rejected = {
    function(f) f.resume.at = f.now - 4 end,
    function(f) f.resume.at = f.now + 1 end,
    function(f) f.resume.load_request_id = string.rep('e', 32) end,
    function(f) f.resume.release_id = nil end,
    function(f) f.resume.lobby_load.attempt_id = string.rep('e', 32) end,
    function(f) f.resume.lobby_load.guard_run_id = 'old-guard' end,
    function(f) f.resume.lobby_load.membership.revision = 8 end,
    function(f) f.peer.at = f.now - 2 end,
    function(f) f.peer.snapshot_epoch = string.rep('b', 16) end,
    function(f) f.peer.snapshot_epoch = '' end,
    function(f) f.peer.game_pid = 11 end,
    function(f) f.peer = nil end,
    function(f) f.status.lobby.data.load_check.campaign_start = nil end,
    function(f) f.status.lobby.data.load_check.phase, f.status.lobby.data.load_check.reason = 'failed', 'cancelled' end,
    function(f) f.status.connected = false end,
    function(f) f.pause.phase = 'lost' end,
    function(f) f.protected = false end,
}
for _, reject in ipairs(rejected) do
    f = campaign()
    reject(f)
    assert(not f.hold:resume(f.status, f.resume, f.peer) and f.pause.returns == 0)
end
print('ok - stale, foreign, manual, disconnected and cancelled attempts never resume')
print('Prepared native pause tests passed')

f = fixture()
local selection = {scenario='CLAIRE_A',difficulty='EASY'}
f.guard.policy, f.guard.allowed_load_calls, f.loader.new_game = nil, 0, selection
local data = f.status.lobby.data
data.new_game, data.save_ref, data.save_slot, data.load_check.campaign_start = selection, nil, nil, true
data.host_id,data.guest_id,data.ready,data.revision='host','guest',{host=true,guest=true},f.scope.revision
data.load_check.phase,data.load_check.start='starting',{H=id}
assert(not f.hold:arm(id,f.scope,f.reference,selection))
assert(f.hold:arm(id,f.scope,nil,selection))
f.loader.phase, f.pause.ready = 'loading', true
assert(not f.hold:poll(f.status))
f.loader.phase, f.pause.phase, f.pause.verified = 'scene_loaded','held',true
assert(f.hold:poll(f.status))
data.new_game = {scenario='CLAIRE_A',difficulty='NORMAL'}
assert(not f.hold:poll(f.status) and f.pause.returns==0)
data.new_game = selection
f.guard.policy = f.reference
assert(not f.hold:poll(f.status))
f.guard.policy, f.guard.allowed_load_calls = nil, 1
assert(not f.hold:poll(f.status) and f.pause.returns==0)
print('Fresh campaign holds bind native selection, Steam membership and zero-load protection')

f.guard.allowed_load_calls = 0
f.world={request_id=id,scenario=1,difficulty=0,map=42,area=3}
local epoch=string.rep('a',16)
local peer={schema=1,at=f.now,game_pid=10,role='H',revision=7,snapshot_epoch=epoch}
local resume={schema=1,at=f.now,load_request_id=id,lobby_load=f.scope,snapshot_epoch=epoch,release_id=string.rep('e',32)}
assert(not f.hold:resume(f.status,resume,peer))
resume.new_game_world={scenario=1,difficulty=0,map=42,area=2}
assert(not f.hold:resume(f.status,resume,peer))
resume.new_game_world.area,resume.new_game_world.difficulty=3,1
assert(not f.hold:resume(f.status,resume,peer))
resume.new_game_world.difficulty=0
f.world.request_id=string.rep('8',32)
assert(not f.hold:resume(f.status,resume,peer))
f.world.request_id=id
assert(f.hold:resume(f.status,resume,peer) and f.pause.returns==1)
print('Fresh release requires native scenario, difficulty, map and area at release time')

f=fixture()
f.guard.policy,f.guard.allowed_load_calls,f.loader.new_game=nil,0,selection
assert(f.hold:arm(id,f.scope,nil,selection))
f.loader.phase,f.protected='failed',false
assert(not f.hold:poll(nil))
f.pause.ready=true
assert(not f.hold:poll(nil) and f.pause.request_id==id)
f.pause.phase,f.pause.verified='held',true
assert(not f.hold:poll(nil) and f.hold:snapshot().phase=='held' and not f.hold:snapshot().available)
assert(not f.hold:resume(f.status,resume,peer) and f.pause.returns==0)
print('Failed partial setup still catches an arriving player without releasing it')
