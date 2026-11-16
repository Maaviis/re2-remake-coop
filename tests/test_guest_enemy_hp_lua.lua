local root = 'app.ropeway.'
local point_name, base = root .. 'EnemyHitPointController', root .. 'HitPointController'
local controller_name = root .. 'EnemyController'
local list_name = 'System.Collections.Generic.List`1<' .. controller_name .. '>'
local id = '00000001-ffff-abcd-f0f1-f2f3f4f5f6f7'
local id2 = '00000002-ffff-abcd-f0f1-f2f3f4f5f6f7'

local function fixture()
    local f = {writes=0, hp=70, default_hp=100, kind=4, inherit_id=-1, alive=true, active=true, dead=false}
    local definitions = {}
    local function definition(name, parent)
        local def = definitions[name] or {methods={}}
        function def:get_full_name() return name end
        function def:get_parent_type() return parent end
        function def:get_method(key) return self.methods[key] end
        definitions[name] = def
        return def
    end
    local function method(owner, name, result, argument, call)
        local result_type = definition(result)
        definition(owner).methods[name] = {
            get_param_types=function()
                if argument then return {definition(f.bad_setter or argument)} end
                return {}
            end,
            get_return_type=function() return result_type end,
            is_static=function() return false end,
            call=call,
        }
    end
    local function object(name, parent)
        local def = definition(name, parent)
        return {get_type_definition=function() return def end}
    end
    local guid = object('System.Guid')
    function guid:get_field(name)
        if name=='mData1' then return 1 end
        if name=='mData2' then return 0xffff end
        if name=='mData3' then return 0xabcd end
        return 0xf0+tonumber(name:sub(-1))
    end
    local point = object(point_name, definition(base))
    local controller = object(controller_name)
    function controller:get_field(name)
        if name=='<ContextGUID>k__BackingField' then return guid end
        if name=='<HitPoint>k__BackingField' then return point end
        error(name)
    end
    function controller:call(name)
        if name=='get_IsActiveEnemy' then return f.active end
        if name=='get_IsLive' then return f.alive end
        if name=='get_KindID' then return f.kind end
        if name=='get_InheritID' then return f.inherit_id end
        error(name)
    end
    local point2 = object(point_name, definition(base))
    local guid2 = object('System.Guid')
    function guid2:get_field(name) return name=='mData1' and 2 or guid:get_field(name) end
    local controller2 = object(controller_name)
    function controller2:get_field(name)
        if name=='<ContextGUID>k__BackingField' then return guid2 end
        if name=='<HitPoint>k__BackingField' then return point2 end
        error(name)
    end
    controller2.call=controller.call
    f.hp2=70
    local list = object(list_name)
    local manager = object(root .. 'EnemyManager')
    method(base, 'set_CurrentHitPoint(System.Int32)', 'System.Void', 'System.Int32', function(_, target, hp)
        assert(target==point or target==point2)
        if not f.ignore_write then
            if target==point2 then f.hp2=hp else f.hp=hp end
        end
        f.writes=f.writes+1
    end)
    method(base, 'get_CurrentHitPoint', 'System.Int32', nil, function(_,target) return target==point2 and f.hp2 or f.hp end)
    method(base, 'get_DefaultHitPoint', 'System.Int32', nil, function() return f.default_hp end)
    method(base, 'get_IsDead', 'System.Boolean', nil, function() return f.dead end)
    method(controller_name, 'get_NoDamage', 'System.Boolean', nil, function() return f.invulnerable==true end)
    method(root .. 'EnemyManager', 'get_ActiveEnemyList', list_name, nil, function() return list end)
    method(list_name, 'get_Count', 'System.Int32', nil, function() return (f.duplicate or f.second_active) and 2 or 1 end)
    method(list_name, 'get_Item(System.Int32)', controller_name, 'System.Int32', function(_,_,index) return f.second_active and index==1 and controller2 or controller end)
    local checkpoint = {game_guid='ffffffff-ffff-abcd-f0f1-f2f3f4f5f6f7',
        save_guid='00000002-ffff-abcd-f0f1-f2f3f4f5f6f7', scenario=1, location=16}
    f.receipt = {generation=100, load={checkpoint=checkpoint}, view={observer_sequence=10, enemies={
        [id]={kind_id=4, inherit_id=-1, hp=37, default_hp=100, is_live=true, is_dead=false},
    }}}
    f.state = {eligible=1, enemies={[id]={}}}
    local env = setmetatable({
        reframework={get_game_name=function() return 're2' end},
        sdk={get_tdb_version=function() return 70 end, find_type_definition=function(name) return definitions[name] end,
            get_managed_singleton=function(name) assert(name==root .. 'EnemyManager'); return manager end},
    }, {__index=_G})
    function env.require(name)
        if name=='re2_coop.guest_enemy_readback' then
            return assert(loadfile('reframework/autorun/re2_coop/guest_enemy_readback.lua', 't', env))()
        end
        assert(name=='re2_coop.enemy_state')
        return {new=function() return {capture=function()
            if f.lost then return nil end
            local entries={{id=id, kind_id=4,
                live={present=true, active=true, is_live=true, is_dead=false, hp=f.captured_hp or f.hp,
                    default_hp=100, inherit_id=-1}}}
            if f.second_active then
                entries[#entries+1]={id=id2,kind_id=4,live={present=true,active=true,is_live=true,
                    is_dead=false,hp=f.hp2,default_hp=100,inherit_id=-1}}
            end
            return {checkpoint=f.different_checkpoint and {} or checkpoint,
                active_count=(f.duplicate or f.second_active) and 2 or 1, entries=entries}
        end} end}
    end
    f.module = assert(loadfile('reframework/autorun/re2_coop/guest_enemy_hp.lua', 't', env))()
    return f
end

do
    local f = fixture()
    local apply = f.module.new()
    assert(apply(f.state, f.receipt).applied==1 and f.hp==37 and f.writes==1)
    assert(apply(f.state, f.receipt).reason=='already_seen' and f.writes==1)
    f.receipt.view.observer_sequence=11
    assert(apply(f.state, f.receipt).identical==1 and f.writes==1)
    f.receipt.view.observer_sequence=12
    f.receipt.view.enemies[id].hp=0
    assert(apply(f.state, f.receipt).reason=='no_positive_candidates' and f.writes==1)
end

for _, name in ipairs({'lost', 'different_checkpoint', 'duplicate', 'invulnerable', 'dead',
        'changed_identity', 'changed_hp', 'changed_default_hp', 'host_dead'}) do
    local f=fixture()
    if name=='changed_identity' then f.inherit_id=-2
    elseif name=='changed_hp' then f.captured_hp=69
    elseif name=='changed_default_hp' then f.default_hp=101
    elseif name=='host_dead' then f.receipt.view.enemies[id].is_dead=true
    else f[name]=true end
    local result=f.module.new()(f.state, f.receipt)
    assert(result.applied==0 and f.writes==0, name)
end

do
    local f=fixture()
    f.bad_setter='System.Single'
    assert(not pcall(f.module.new) and f.writes==0)
    f.bad_setter=nil
    f.ignore_write=true
    local apply=f.module.new()
    assert(not pcall(apply, f.state, f.receipt) and f.writes==1)
    assert(apply(f.state, f.receipt).reason=='already_seen')
end

-- A fresh unchanged Host view remains actionable after a transient local miss.
for _, transient in ipairs({'lost', 'different_checkpoint', 'duplicate', 'invulnerable',
        'dead', 'changed_hp', 'changed_default_hp', 'inactive_guest'}) do
    local f=fixture()
    local apply=f.module.new()
    if transient=='changed_hp' then f.captured_hp=69
    elseif transient=='changed_default_hp' then f.default_hp=101
    elseif transient=='inactive_guest' then f.state={eligible=0, enemies={}}
    else f[transient]=true end
    assert(apply(f.state,f.receipt).applied==0 and f.writes==0, transient..': initial skip')
    f[transient]=false;f.captured_hp=nil;f.default_hp=100
    f.state={eligible=1,enemies={[id]={}}}
    assert(apply(f.state,f.receipt).applied==1 and f.hp==37 and f.writes==1,
        transient..': unchanged observation lost after recovery')
    f.hp=60
    assert(apply(f.state,f.receipt).reason=='already_seen' and f.writes==1,
        transient..': successful observation must not be reapplied')
end

-- One applied enemy must not consume another enemy that becomes eligible later.
do
    local f=fixture()
    f.receipt.view.enemies[id2]={kind_id=4,inherit_id=-1,hp=29,default_hp=100,is_live=true,is_dead=false}
    local apply=f.module.new()
    assert(apply(f.state,f.receipt).applied==1 and f.writes==1 and f.hp==37 and f.hp2==70)
    f.hp=60;f.second_active=true
    f.state={eligible=2,enemies={[id]={},[id2]={}}}
    assert(apply(f.state,f.receipt).applied==1 and f.writes==2 and f.hp==60 and f.hp2==29)
    assert(apply(f.state,f.receipt).reason=='already_seen' and f.writes==2)
end

-- Seeing a newer view advances replay protection even before it can be applied.
do
    local f=fixture()
    local apply=f.module.new()
    f.lost=true;f.receipt.view.observer_sequence=11
    assert(apply(f.state,f.receipt).applied==0 and f.writes==0)
    f.lost=false;f.receipt.view.observer_sequence=10
    assert(apply(f.state,f.receipt).reason=='already_seen' and f.writes==0)
    f.receipt.view.observer_sequence=11
    assert(apply(f.state,f.receipt).applied==1 and f.writes==1)
    f.receipt.generation=101;f.receipt.view.observer_sequence=1;f.hp=70
    assert(apply(f.state,f.receipt).applied==1 and f.writes==2)
    f.receipt.generation=100;f.receipt.view.observer_sequence=12;f.hp=70
    assert(apply(f.state,f.receipt).reason=='already_seen' and f.writes==2)
end

print('Guest HP: native identity, positive write/readback, protected actors, unchanged sample, write failure, transient recovery and per-enemy deduplication passed')
