-- Run the installed autorun entry point with two distinct game VMs and scoped mailbox files.
local empty = 'E1,8,0,-1,-1,-1,0,0,0'
local host_kit = 'E1,8,1,0,1,0,1,0,15,9,0,0,0,1,-1,0,1,0,1,0,0'
local function runtime(role, initial)
    local f={now=200, equipped=initial, writes=0, epoch='0000000000000001', active=true}
    local scope={request_id=('a'):rep(32),attempt_id=('b'):rep(32),session_id='session',revision=2,game_pid=42,
        role=role,equipment_namespace=('c'):rep(32),release_id=('3'):rep(32),snapshot_epoch=f.epoch}
    local function address() return 17 end
    local campaign={read_release=function() if f.active then return scope end end,peer_matches=function() return true end,
        observed_context=function() return {player_address=17,scene_address=13,area={}} end,scene_address=function() return 13 end,
        read_area=function() return {} end,same_area=function() return true end}
    local backend=dofile('reframework/autorun/re2_coop/guest_equipment.lua')
    backend.new=function() return {capture=function() return f.equipped end,
        apply=function(s) f.writes=f.writes+1
            if f.layout_pending then return false,'equipment_layout_requires_campaign_load' end
            f.equipped=s; return true end} end
    local env=setmetatable({require=function(name) if name=='re2_coop.guest_equipment' then return backend end; return campaign end,
        os={clock=function() return f.now end,time=function() return math.floor(f.now) end},
        reframework={get_game_name=function() return 're2' end},log={info=function() end},
        sdk={get_tdb_version=function() return 70 end,typeof=function(n) return n end,get_managed_singleton=function(n)
            local inventory={get_address=address}
            local player={get_address=address,call=function() return inventory end}
            return {call=function(_,name)
                if name=='get_CurrentPlayer' then return player end
                if name=='get_CurrentInventory' then return inventory end
                if name=='get_IsInGameNotPause' then return true end
                if name=='get_InCameraEvent' then return f.in_event==true end
                return false
            end}
        end},
        re={on_pre_application_entry=function(_,tick) f.tick=tick end},
        fs={read=function() return 'command' end},json={load_string=function() return f.command end,
            dump_file=function(path,doc)
                if path=='re2_coop_equipment_local.json' then f.sample=doc
                else
                    assert(path=='re2_coop_equipment_pending_'..('c'):rep(32)..'.json')
                    f.journal=doc
                end
                return true
            end}}, {__index=_G})
    f.reload=function() assert(loadfile('reframework/autorun/re2_coop_guest_equipment.lua','t',env))() end
    f.reload()
    f.advance=function() f.now=f.now+.5;f.tick() end
    f.offer=function(value,lease)
        f.command={schema=1,role=role,pid=42,request=scope.request_id,attempt=scope.attempt_id,session='session',
            namespace=scope.equipment_namespace,release_id=scope.release_id,snapshot_epoch=scope.snapshot_epoch,revision=2,at=math.floor(f.now),
            equipment=value,lease=lease,reader_run=f.sample.reader_run,profile=('c'):rep(32),writer=('e'):rep(32)}
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
g.offer(h.sample.equipment,lease);g.command.release_id=('f'):rep(32);g.advance();assert(g.writes==0)
g.offer(h.sample.equipment,lease);g.active=false;g.advance();assert(g.writes==0)
g.active=true;g.advance();assert(g.writes==1 and g.sample.lease==lease and g.equipped==host_kit)
g.equipped=empty;g.advance();assert(g.writes==1 and g.sample.equipment==empty and h.equipped==host_kit)
-- The preceding restore command is still fresh when the guest reloads the script.
g.reload();g.advance()
assert(g.writes==1 and g.sample.lease==nil and g.equipped==empty, 'replayed initial kit after script reload')
g.offer(empty,lease);g.advance()
assert(g.writes==2 and g.sample.lease==lease and g.equipped==empty)
local other=runtime('G',host_kit)
other.advance()
other.offer(g.sample.equipment,('e'):rep(32));other.advance()
assert(other.writes==1 and other.equipped==empty and h.equipped==host_kit)
local staging=runtime('G',empty)
staging.advance()
staging.layout_pending=true
staging.offer(host_kit,lease); staging.advance(); staging.advance()
assert(staging.writes==1 and staging.sample.lease==nil)
staging.layout_pending=false
staging.equipped=host_kit
staging.offer(host_kit,lease); staging.advance()
assert(staging.writes==2 and staging.sample.lease==lease,'native slot initialization must unblock a pending lease')
local loading=runtime('G',empty)
loading.advance(); loading.offer(host_kit,lease); loading.in_event=true; loading.advance()
assert(loading.writes==0 and loading.sample.available==false)
loading.in_event=false; loading.advance()
assert(loading.writes==1 and loading.sample.equipment==host_kit)
local ten=host_kit:gsub(',15,9,',',15,10,')
local sudden=runtime('G',empty)
sudden.advance(); sudden.offer(ten,lease); sudden.advance()
assert(sudden.journal and sudden.journal.equipment==ten and sudden.journal.lease==lease)
-- Fire after the last periodic capture. Lose the release before the next tick.
sudden.equipped=host_kit; sudden.active=false; sudden.advance()
assert(sudden.journal.equipment==host_kit and sudden.journal.writer==('e'):rep(32))
assert(sudden.sample.available==false and sudden.writes==1 and h.journal==nil)
sudden.equipped=empty; sudden.advance()
assert(sudden.journal.equipment==host_kit,'unbound changes leaked into an old attachment')
print('Guest inventory autorun: paired release, lease, first join, empty return, host and guest isolation passed')
