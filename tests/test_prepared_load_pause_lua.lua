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
    function f.pause:release() self.returns = self.returns + 1; return true end
    f.status = {schema=1, written_at=100, connected=true, game_pid=10, role='H', steam_lobby='owned',
        steam_membership={session_id=string.rep('a',32), revision=7},
        lobby={version=1, type='lobby_state', session_id='lobby', data={connected=true,
            save_slot='scenario:4', save_ref={available=true, mode=1, slot_id=4, timestamp=f.reference.timestamp, scenario=1},
            load_check={phase='prepared', reason='', revision=5, attempt_id=string.rep('c',32), save_digest=string.rep('f',64)}}}}
    f.hold = M.new(f.guard, f.loader, 'native-H', {pause=f.pause, clock=function() return f.now end})
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
print('Prepared native pause: 7 groups passed; no world-stillness or distributed release claim')
