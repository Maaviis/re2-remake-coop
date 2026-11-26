-- Run the installed autorun entry point with two distinct game VMs and scoped mailbox files.
local empty = 'E1,8,0,-1,-1,-1,0,0,0'
local host_kit = 'E1,8,1,0,1,0,1,0,15,9,0,0,0,1,-1,0,1,0,1,0,0'
local function runtime(role, initial)
    local f={now=200, equipped=initial, writes=0, epoch='0000000000000001', active=true}
    local scope={request_id=('a'):rep(32),attempt_id=('b'):rep(32),session_id='session',revision=2,game_pid=42,
        role=role,equipment_namespace=('c'):rep(32),snapshot_epoch=f.epoch}
    local function address() return 17 end
    local campaign={read_release=function() if f.active then return scope end end,peer_matches=function() return true end,
        observed_context=function() return {player_address=17,scene_address=13,area={}} end,scene_address=function() return 13 end,
        read_area=function() return {} end,same_area=function() return true end}
    local backend=dofile('reframework/autorun/re2_coop/guest_equipment.lua')
    backend.new=function() return {capture=function() return f.equipped end,
        apply=function(s) f.writes=f.writes+1; f.equipped=s; return true end} end
    local env=setmetatable({require=function(name) if name=='re2_coop.guest_equipment' then return backend end; return campaign end,
        os={clock=function() return f.now end,time=function() return math.floor(f.now) end},
        reframework={get_game_name=function() return 're2' end},log={info=function() end},
        sdk={get_tdb_version=function() return 70 end,get_managed_singleton=function()
            return {call=function() return {get_address=address} end} end},
        re={on_pre_application_entry=function(_,tick) f.tick=tick end},
        fs={read=function() return 'command' end},json={load_string=function() return f.command end,
            dump_file=function(_,doc) f.sample=doc; return true end}}, {__index=_G})
    assert(loadfile('reframework/autorun/re2_coop_guest_equipment.lua','t',env))()
    f.advance=function() f.now=f.now+.5;f.tick() end
    f.offer=function(value,lease)
        f.command={schema=1,role=role,pid=42,request=scope.request_id,attempt=scope.attempt_id,session='session',
            namespace=scope.equipment_namespace,snapshot_epoch=scope.snapshot_epoch,revision=2,at=math.floor(f.now),
            equipment=value,lease=lease}
    end
    return f
end
local h,g=runtime('H',host_kit),runtime('G',empty)
h.advance();g.advance()
assert(h.sample.equipment==host_kit and g.sample.equipment==empty and g.sample.lease==nil)
local lease=('d'):rep(32)
h.offer(empty,lease); h.advance()
assert(h.writes==0 and h.equipped==host_kit)
g.offer(h.sample.equipment,lease)
g.command.snapshot_epoch='other';g.advance();assert(g.writes==0)
g.offer(h.sample.equipment,lease);g.active=false;g.advance();assert(g.writes==0)
g.active=true;g.advance();assert(g.writes==1 and g.sample.lease==lease and g.equipped==host_kit)
g.equipped=empty;g.advance();assert(g.writes==1 and g.sample.equipment==empty and h.equipped==host_kit)
local other=runtime('G',host_kit)
other.offer(g.sample.equipment,('e'):rep(32));other.advance()
assert(other.writes==1 and other.equipped==empty and h.equipped==host_kit)
print('Guest inventory autorun: paired release, lease, first join, empty return, host and guest isolation passed')
