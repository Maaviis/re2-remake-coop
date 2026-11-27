local replay=dofile('reframework/autorun/re2_coop/scene_replay.lua')
local model=dofile('reframework/autorun/re2_coop/cutscenes.lua')
local function state(phase,vote,decision)
    return {event='evt_20011',occurrence=1,phase=phase,vote=vote or 0,decision=decision or 'none'}
end
local wait,play,request,accept=state('waiting'),state('playing'),state('playing',1,'request'),state('playing',1,'accept')
local groups={
    {host=wait,duration=1000,steps={{ms=0,peer=false},{ms=300,peer=wait}}},
    {host=play,duration=5000,steps={{ms=0,peer=play}}},
    {host=request,duration=4000,steps={{ms=0,peer=play},{ms=400,peer=false},{ms=2300,peer=accept}}}}
local ms=0
local plan={event=wait.event,occurrence=1,groups=groups}
local player=assert(replay.new(plan,model.valid_peer,function() return ms end))
local machine=model.new(function() return 25 end)
local function connect(peer)
    machine:connect({schema=1,at=25,game_pid=72,role='H',attempt_id=string.rep('d',32),simulated=true,peer=peer})
end
connect(nil)
assert(not machine:admit(wait.event,'camera'))
connect(player:sample(machine:record()))
assert(not machine:admit(wait.event,'camera'))
ms=301
connect(player:sample(machine:record()))
assert(machine:admit(wait.event,'camera'))
connect(player:sample(machine:record()))
machine:request()
connect(player:sample(machine:record()))
assert(not machine:authorized())
ms=1100
local p,status=player:sample(machine:record())
assert(p==nil and status=='recorded_gap')
connect(p); assert(not machine:authorized())
ms=2650
connect(player:sample(machine:record())); assert(machine:authorized())
ms=5000
p,status=player:sample(machine:record()); assert(p==nil and status=='finished')
groups[3].steps[2].ms=-1
assert(not replay.new(plan,model.valid_peer,function() return 0 end))
print('Recorded guest arrival, skip request, missing confirmation, subsequent approval and trace end passed')
