local files, keys, starts, now = {}, {}, 0, 100
local token, run = string.rep('c',32), string.rep('a',32)
os.time = function() return now end
local tick=0
os.clock=function() tick=tick+0.5; return tick end
log={info=function() end}
reframework = {is_key_down=function(_,key) return keys[key] == true end}
local lobby_file='re2_coop_lobby.json'
local empty_bridge_read=false
local blank_reads=0
fs = {read=function(name)
    if name==lobby_file then
        if blank_reads>0 then blank_reads=blank_reads-1; return '' end
        if empty_bridge_read then return '' end
    end
    return files[name] and name
end}
json = {load_string=function(name) return files[name] end,
    dump_file=function(name, value) files[name] = value end}
local lobby = {schema=1,game_pid=18,role='H',connected=false,steam_lobby='owned',
    written_at=now,steam_membership={session_id='host-session',revision=3}}
local native = {schema=1,game_pid=18,at=now,revision=3,role='-',snapshot_epoch='',solo_host=true}
local binding = {game_pid=18,run_id=run,campaign_namespace=token,runtime=true}
local receipt = {schema=1,game_pid=18,at=now,active=true,runtime_protection=true,
    protection_active=true,protection=binding,campaign_mount_ready=token,guard_run_id='vm1'}
files['re2_coop_lobby.json'], files['re2_coop_native_peer.json'] = lobby, native
files['re2_coop_save_guard.json'] = receipt
local sim = dofile('reframework/autorun/re2_coop/cutscene_test_peer.lua')
local mounted=true
local guard = {active=true,protection={current=binding},campaign_ready=function(_,b) return mounted and b==binding end}
local loader = {phase='idle'}
local driver = {start=function(_,s,id,proof)
    assert(s.scenario=='LEON_A' and s.difficulty=='NORMAL' and proof==binding)
    starts=starts+1; loader.new_game=s; loader.request_id=id; loader.phase='closing_menu'; return true
end}
local launcher = sim.launcher(guard, driver, loader, 'vm1')
assert(not sim.active() and not sim.poll(false))
native.solo_host=false
assert(not sim.request_start(lobby))
native.solo_host=true
assert(sim.request_start(lobby))
launcher:update()
launcher:update()
assert(starts==1 and launcher:owns_start() and launcher:admitted())
-- The guard that owns the loader can validate the native mount even while
-- its periodic report is missing. An actual mount loss still revokes admission.
files['re2_coop_save_guard.json']=nil
assert(launcher:admitted(), 'loader rejected its own verified live guard during a report gap')
mounted=false; assert(not launcher:admitted()); mounted=true
files['re2_coop_save_guard.json']=receipt
local peer=assert(sim.poll(false))
assert(peer.simulated and peer.peer==nil and peer.game_pid==18)
assert(not sim.preview_ready(), 'the new-game load admitted preview before any intro evidence')
blank_reads=1
assert(launcher:admitted(), 'one empty bridge read followed by fresh matching evidence stopped title admission')
blank_reads=1
lobby.steam_membership.revision=4
assert(not launcher:admitted(), 'retrying an empty bridge read admitted a different lobby revision')
lobby.steam_membership.revision=3
empty_bridge_read=true
assert(not launcher:admitted(), 'protected title transition must require a current bridge read')
empty_bridge_read=false
loader.phase='loading'
launcher:update()
empty_bridge_read=true
launcher:update()
assert(launcher:admitted() and sim.poll(false),
    'a missing bridge read must not cancel the already committed native load')
empty_bridge_read=false
loader.phase='scene_loaded'
launcher:update()
empty_bridge_read=true
launcher:update()
assert(launcher:admitted() and sim.poll(false), 'an empty bridge read must not end a loaded solo run')
empty_bridge_read=false
local local_state={schema=1,game_pid=18,attempt_id=peer.attempt_id,at=now,event='movie_12',occurrence=1,phase='waiting',vote=0,decision='none'}
sim.publish(local_state)
keys[0x71]=true
assert(sim.poll(false).peer.phase=='waiting')
keys[0x71]=false
local_state.phase='playing'; local_state.vote=1; local_state.decision='request'
sim.publish(local_state); sim.poll(false)
keys[0x72]=true
assert(sim.poll(false).peer.decision=='decline')
keys[0x72]=false
local_state.vote=2; sim.publish(local_state); sim.poll(false)
keys[0x71]=true
assert(sim.poll(false).peer.decision=='accept')
local_state.occurrence=2; local_state.phase='waiting'; local_state.vote=0; local_state.decision='none'
sim.publish(local_state); assert(sim.poll(false).peer==nil)
keys[0x71]=false; sim.poll(false)
local status_file='re2_coop_solo_status.json'
local saved_status=files[status_file]
files[status_file]=nil
keys[0x71]=true
local missing, stopped=sim.poll(false)
assert(not missing and not stopped, 'an unreadable status must not confirm that the test ended')
files[status_file]={schema=1,game_pid=saved_status.game_pid,attempt_id=saved_status.attempt_id,
    guard_run_id=saved_status.guard_run_id,run_id=saved_status.run_id,revision=saved_status.revision,
    session_id=saved_status.session_id,request_id='older request',active=false,at=now}
missing,stopped=sim.poll(false)
assert(not missing and not stopped, 'an older request must not terminate the current test')
files[status_file]=saved_status
assert(sim.poll(false).peer==nil, 'a key held during the gap must not vote on reconnect')
keys[0x71]=false; sim.poll(false)
keys[0x71]=true
assert(sim.poll(false).peer.phase=='waiting', 'the held occurrence must accept a new arrival after recovery')
local model=dofile('reframework/autorun/re2_coop/cutscenes.lua').new()
local function sync()
    local record=model:record()
    if record then record.attempt_id=token; sim.publish(record) end
    model:connect(sim.poll(false))
end
keys={}
sync()
for number=1,3 do
    local event='evt_'..(20000+number)
    assert(not model:admit(event,'movie'))
    sync()
    assert(not model:admit(event,'movie'), 'a local start cannot stand in for the second arrival')
    assert(not sim.preview_ready(), 'waiting story event admitted the preview')
    keys[0x71]=true; sync()
    assert(model:admit(event,'movie'))
    keys[0x71]=false; sync()
    assert(not sim.preview_ready(), 'playing story event admitted the preview')
    model:request(); sync()
    keys[0x72]=true; sync()
    assert(not model:authorized())
    keys[0x72]=false; sync()
    model:request(); sync()
    keys[0x71]=true; sync()
    assert(model:authorized())
    model:finish('movie'); keys[0x71]=false; sync()
    assert(sim.preview_ready(), 'completed story event did not unlock explicit F5 admission')
end
empty_bridge_read=true
native.solo_host=false; launcher:update()
missing,stopped=sim.poll(false)
assert(not sim.active() and not launcher:admitted() and not missing and stopped,
    'the launcher terminal receipt must retire its matching simulator session')
assert(not sim.preview_ready(), 'departed solo attempt left the F5 action available')
empty_bridge_read=false
native.solo_host=true; launcher:update()
assert(not sim.active() and starts==1)
assert(files['re2_coop_campaign_peer_release.json']==nil and files['re2_coop_cutscene_peer.json']==nil)
-- An interrupted title transition may retry only on a fresh click after
-- the driver positively observes recovery. A stale request cannot relaunch.
local recovered=false
local resets=0
driver.recoverable=function() return recovered end
driver.reset_failed=function()
    if not recovered then return false end
    resets=resets+1; loader.new_game=nil; loader.phase='idle'
    return true
end
loader.phase='failed'; loader.error='new_game_lobby_changed'
launcher:update()
local old_request=files['re2_coop_solo_request.json']
recovered=true; launcher:update()
assert(starts==1 and resets==0)
local queued,new_id=sim.request_start(lobby)
assert(queued and type(new_id)=='string' and new_id~=old_request.request_id)
launcher:update(); launcher:update()
assert(starts==2 and resets==1 and launcher:admitted(), 'fresh click could not retry recovered solo start')
loader.phase='scene_loaded'
launcher:update()
empty_bridge_read=true
now=now+4
native.at,receipt.at=now,now
assert(not launcher:admitted(), 'a missing bridge record must expire at the original freshness bound')
print('Protected solo launch, distinct simulated arrival/votes and irreversible cancellation passed')
