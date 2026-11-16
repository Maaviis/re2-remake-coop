local root = 'app.ropeway.'
local point_name, base = root .. 'EnemyHitPointController', root .. 'HitPointController'
local controller_name = root .. 'EnemyController'
local list_name = 'System.Collections.Generic.List`1<' .. controller_name .. '>'
local id = '00000001-ffff-abcd-f0f1-f2f3f4f5f6f7'

local function fixture()
    local f = {writes=0, hp=70, default_hp=100, kind=4, inherit_id=-1, alive=true, active=true, dead=false, now=100}
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
    local list = object(list_name)
    local manager = object(root .. 'EnemyManager')
    method(base, 'set_CurrentHitPoint(System.Int32)', 'System.Void', 'System.Int32', function(_, target, hp)
        assert(target==point)
        if not f.ignore_write then f.hp=hp end
        f.writes=f.writes+1
    end)
    method(base, 'get_CurrentHitPoint', 'System.Int32', nil, function() return f.hp end)
    method(base, 'get_DefaultHitPoint', 'System.Int32', nil, function() return f.default_hp end)
    method(base, 'get_IsDead', 'System.Boolean', nil, function() return f.dead end)
    method(controller_name, 'get_NoDamage', 'System.Boolean', nil, function() return f.invulnerable==true end)
    method(root .. 'EnemyManager', 'get_ActiveEnemyList', list_name, nil, function() return list end)
    method(list_name, 'get_Count', 'System.Int32', nil, function() return f.duplicate and 2 or 1 end)
    method(list_name, 'get_Item(System.Int32)', controller_name, 'System.Int32', function() return controller end)
    local checkpoint = {game_guid='ffffffff-ffff-abcd-f0f1-f2f3f4f5f6f7',
        save_guid='00000002-ffff-abcd-f0f1-f2f3f4f5f6f7', scenario=1, location=16}
    f.receipt = {generation=100, received_at=100, load={checkpoint=checkpoint}, view={observer_sequence=10, enemies={
        [id]={kind_id=4, inherit_id=-1, hp=37, default_hp=100, is_live=true, is_dead=false},
    }}}
    f.state = {eligible=1, enemies={[id]={}}}
    local env = setmetatable({
        os={time=function() return f.now end},
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
            return {checkpoint=f.different_checkpoint and {} or checkpoint,
                active_count=f.duplicate and 2 or 1, entries={{id=id, kind_id=4,
                    live={present=true, active=true, is_live=true, is_dead=false, hp=f.captured_hp or f.hp,
                        default_hp=100, inherit_id=-1}}}}
        end} end}
    end
    f.module = assert(loadfile('reframework/autorun/re2_coop/guest_enemy_hp.lua', 't', env))()
    return f
end

do
    local f = fixture()
    local apply = f.module.new()
    local written
    assert(apply(f.state, f.receipt, function(guid, values)
        assert(guid==id)
        written=values
    end).applied==1 and f.hp==37 and f.writes==1)
    assert(written.before_hp==70 and written.after_hp==37 and written.is_dead==false)
    assert(written.kind_id==4 and written.inherit_id==-1)
    assert(apply(f.state, f.receipt).reason=='already_seen' and f.writes==1)
    f.receipt.view.observer_sequence=11
    assert(apply(f.state, f.receipt).identical==1 and f.writes==1)
    f.receipt.view.observer_sequence=12
    f.receipt.view.enemies[id].hp=0
    assert(apply(f.state, f.receipt).reason=='no_positive_candidates' and f.writes==1)
end

do
    local f=fixture()
    f.now=104
    local result=f.module.new()(f.state, f.receipt, function() error('expired write recorded') end)
    assert(result.reason=='receipt_expired' and result.applied==0 and f.writes==0)
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
    local recorded = false
    assert(not pcall(apply, f.state, f.receipt, function() recorded = true end) and f.writes==1)
    assert(not recorded)
    assert(apply(f.state, f.receipt).reason=='already_seen')
end

print('Guest HP: native identity, positive write/readback, protected actors, unchanged sample and write failure passed')
