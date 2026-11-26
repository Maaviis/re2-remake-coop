local area = {scenario=1, map=4, area=5}
local other_area = {scenario=1, map=4, area=6}
local id = '00000001-abcd-ffff-0001-020304050607'
local names = {source='re2_coop_campaign_guest_hits.json', target='re2_coop_campaign_incoming_hits.json',
    applied='re2_coop_campaign_hit_application.json'}
local documents, now, writes, watched = {}, 100, 0, nil
local owner = {get_address=function() return 77 end}
local player = owner
local scope = {role='G', attempt_id='attempt', request_id='local-load', snapshot_epoch='steam'}
local context = {player=player, player_address=15, scene_address=20, area=area, visit='room-1'}
local active = {id=id, kind_id=4, live={active=true, is_live=true, is_dead=false, default_hp=770, inherit_id=-1}}
local observer = {sequence=0, events={}}
function observer:set_local_player(value) watched=value end
function observer:snapshot() return {sequence=self.sequence, events=self.events} end
function observer:stop() self.stopped=true end

local modules = {
    ['re2_coop.guest_enemy_readback']={fresh=function(at, time)
        return type(at)=='number' and at <= time and time - at <= 3
    end},
    ['re2_coop.campaign_pose_scope']={same_area=function(a,b)
        return a and b and a.scenario==b.scenario and a.map==b.map and a.area==b.area
    end},
}
local env = setmetatable({
    require=function(name) return assert(modules[name]) end,
    os={time=function() return now end},
    fs={read=function(name) if documents[name] then return name end end},
    json={load_string=function(name) return documents[name] end,
        dump_file=function(name,data) documents[name]=data end},
}, {__index=_G})
local hit_module = assert(loadfile('reframework/autorun/re2_coop/campaign_hits.lua', 't', env))()
local hits = hit_module.new(observer, function() return {campaign_area=context.area, entries={active}} end,
    function(hit, receipt)
        assert(receipt.request_id==scope.request_id and hit.id==id and hit.damage==33)
        writes=writes+1
        return {before_hp=500, after_hp=467}
    end)

local function event(before, after, owner_type)
    observer.sequence = observer.sequence + 1
    observer.events[#observer.events+1] = {id=id, at=now, sequence=observer.sequence,
        hp_on_entry=before, hp_on_exit=after, before={attacker=owner_type},
        after={attacker=owner_type, Damage=33}}
end

hits.update()
assert(watched==nil and documents[names.source]==nil)
hits.update(scope, context)
assert(watched==owner and #documents[names.source].hits==0)
event(770,737,'other')
event(737,737,'local_player')
event(33,0,'local_player')
event(700,667,'local_player')
hits.update(scope, context)
local sample = documents[names.source]
assert(#sample.hits==1 and sample.hits[1].sequence==4 and sample.hits[1].damage==33)
context.area, context.visit = other_area, 'room-2'
hits.update(scope, context)
assert(#documents[names.source].hits==0)
hits.update()
assert(watched==nil and documents[names.source].attempt_id==nil)

scope.role = 'H'
context.area, context.visit = area, 'room-3'
documents[names.target] = {schema=1, at=now, attempt_id='old', request_id='local-load',
    area=area, hits=sample.hits, host_visit='room-3'}
hits.update(scope, context)
assert(writes==0)
documents[names.target].attempt_id = scope.attempt_id
hits.update(scope, context)
hits.update(scope, context)
assert(writes==1 and documents[names.applied].after_hp==467)
sample.hits[1].sequence=5
context.area = other_area
hits.update(scope, context)
context.area = area
hits.update(scope, context)
assert(writes==1, 'old room hit replayed after returning')
hits.update()
context.visit = 'room-4'
sample.hits[1].sequence = 6
hits.update(scope, context)
assert(writes==1, 'an old receipt survived the gap in native context')
local reload_writes = 0
documents[names.target].host_visit = context.visit
local reloaded = hit_module.new(nil, nil, function() reload_writes=reload_writes+1 end)
reloaded.update(scope, context)
assert(reload_writes==0, 'consumed hit replayed after script reload')
hits.reset()
assert(observer.stopped)
print('Campaign hits: positive attributed source, scope, confirmed host result and replay suppression passed')
