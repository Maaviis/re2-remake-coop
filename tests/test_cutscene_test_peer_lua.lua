local files, keys, starts, now = {}, {}, 0, 100
local token, run = string.rep('c',32), string.rep('a',32)
os.time = function() return now end
local tick=0
os.clock=function() tick=tick+0.5; return tick end
log={info=function() end}
reframework = {is_key_down=function(_,key) return keys[key] == true end}
fs = {read=function(name) return files[name] and name end}
json = {load_string=function(name) return files[name] end,
    dump_file=function(name, value) files[name] = value end}
local lobby = {schema=1,game_pid=18,role='H',connected=false,steam_lobby='owned',
    written_at=now,steam_membership={session_id='host-session',revision=3}}
local native = {schema=1,game_pid=18,at=now,revision=3,role='-',snapshot_epoch='',solo_host=true}
local binding = {game_pid=18,run_id=run,campaign_namespace=token}
local receipt = {schema=1,game_pid=18,at=now,active=true,runtime_protection=true,
    protection_active=true,protection=binding,campaign_mount_ready=token,guard_run_id='vm1'}
files['re2_coop_lobby.json'], files['re2_coop_native_peer.json'] = lobby, native
files['re2_coop_save_guard.json'] = receipt
local sim = dofile('reframework/autorun/re2_coop/cutscene_test_peer.lua')
local guard = {protection={current=binding},campaign_ready=function() return true end}
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
local peer=assert(sim.poll(false))
assert(peer.simulated and peer.peer==nil and peer.game_pid==18)
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
native.solo_host=false; launcher:update()
assert(not sim.active() and not launcher:admitted() and not sim.poll(false))
native.solo_host=true; launcher:update()
assert(not sim.active() and starts==1)
assert(files['re2_coop_campaign_peer_release.json']==nil and files['re2_coop_cutscene_peer.json']==nil)
print('Protected solo launch, distinct simulated arrival/votes and irreversible cancellation passed')
