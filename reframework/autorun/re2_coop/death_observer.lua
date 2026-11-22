-- Passive onDead callback evidence for one verified native class, not complete death synchronization.
local M = {}
local think_name = 'app.ropeway.enemy.EnemyThinkBehavior'
local callback_owner = 'app.ropeway.enemy.em0000.Em0000ThinkBase'
local concrete_type = 'app.ropeway.enemy.em0000.Em0000Think'
local controller_name = 'app.ropeway.EnemyController'
local callback_name = callback_owner .. '.onDead'
local flow_name='app.ropeway.gamemastering.MainFlowManager'
local save_name='app.ropeway.gamemastering.SaveDataManager'
local capacity = 128

local function integer(value, low, high)
    assert(math.type(value)=='integer' and value>=low and value<=high, 'invalid_death_integer')
    return value
end
local function clone(value)
    if type(value)~='table' then return value end
    local output={};for key,item in pairs(value) do output[key]=clone(item) end
    return output
end
function M.new(options)
    local scoped = options and options.scoped == true
    assert(reframework:get_game_name()=='re2' and sdk.get_tdb_version()==70, 'unsupported_death_build')
    local function definition(name) return assert(sdk.find_type_definition(name), 'missing_death_type:' .. name) end
    local function field(owner,name,kind)
        local member=assert(definition(owner):get_field(name), 'missing_death_field:' .. name)
        assert(not member:is_static() and member:get_type():get_full_name()==kind, 'unsupported_death_field:' .. name)
    end
    for owner,names in pairs({[flow_name]={'get_IsInTitle','get_IsInLoadGameData','get_IsFinishedLoadScene'},
        [save_name]={'get_IsBusy'}}) do
        for _,name in ipairs(names) do
            local member=assert(definition(owner):get_method(name),'missing_death_readiness_method:' .. name)
            assert(not member:is_static() and #member:get_param_types()==0
                and member:get_return_type():get_full_name()=='System.Boolean','unsupported_death_readiness_method:' .. name)
        end
    end
    local method=assert(definition(callback_owner):get_method('onDead'), 'missing_death_callback')
    assert(not method:is_static() and method:get_return_type():get_full_name()=='System.Void'
        and #method:get_param_types()==0, 'unsupported_death_callback')
    local resolved=assert(definition(concrete_type):get_method('onDead'),'missing_concrete_death_callback')
    local address=sdk.to_int64(method:get_function())
    assert(address~=0 and sdk.to_int64(resolved:get_function())==address
        and method:get_declaring_type():get_full_name()==callback_owner
        and resolved:get_declaring_type():get_full_name()==callback_owner,'unsupported_death_dispatch')
    field(think_name,'<Controller>k__BackingField',controller_name)
    field(controller_name,'<ContextGUID>k__BackingField','System.Guid')
    field(controller_name,'<HitPoint>k__BackingField','app.ropeway.EnemyHitPointController')
    field('app.ropeway.HitPointController','<CurrentHitPoint>k__BackingField','System.Int32')
    for name,kind in pairs({mData1='System.UInt32',mData2='System.UInt16',mData3='System.UInt16'}) do field('System.Guid',name,kind) end
    for index=0,7 do field('System.Guid','mData4_' .. index,'System.Byte') end
    assert(thread and type(thread.get_hook_storage)=='function', 'death_hook_storage_unavailable')
    local self={enabled=true,started=false,sequence=0,discarded=0,read_errors=0,events={}}
    local scope, generation, storage_key = nil, 0, {}
    function self:set_scope(value)
        if scoped and value ~= scope then
            scope, generation, self.events = value, generation + 1, {}
        end
    end
    local function guid(value)
        local bytes={}
        for index=0,7 do bytes[index+1]=integer(value:get_field('mData4_' .. index),0,255) end
        local result=('%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x'):format(
            integer(value:get_field('mData1'),0,0xffffffff),integer(value:get_field('mData2'),0,0xffff),
            integer(value:get_field('mData3'),0,0xffff),table.unpack(bytes))
        assert(result~='00000000-0000-0000-0000-000000000000', 'unassigned_death_guid')
        return result
    end
    local function install_hook()
        sdk.hook(method,function(args)
            local storage=thread.get_hook_storage()
            storage[storage_key]=nil
            if self.enabled and (not scoped or scope) then
                local ok,pending=pcall(function()
                    local think=assert(sdk.to_managed_object(args[2]), 'death_receiver_unavailable')
                    local controller=assert(think:get_field('<Controller>k__BackingField'), 'death_controller_unavailable')
                    local id=guid(assert(controller:get_field('<ContextGUID>k__BackingField'), 'death_guid_unavailable'))
                    local point=controller:get_field('<HitPoint>k__BackingField')
                    return {id=id,at=os.time(),hp_present=point~=nil,generation=generation,
                        hp_on_entry=point and integer(point:get_field('<CurrentHitPoint>k__BackingField'),-0x80000000,0x7fffffff) or nil}
                end)
                if ok then storage[storage_key]=pending else self.read_errors=self.read_errors+1 end
            end
            return sdk.PreHookResult.CALL_ORIGINAL
        end,function(retval)
            local storage=thread.get_hook_storage()
            local pending=storage[storage_key]
            storage[storage_key]=nil
            if pending and self.enabled and pending.generation == generation then
                -- onDead may dispose its objects. Keep no native references and do
                -- no post-call native reads; the scene observer measures later state.
                self.sequence=self.sequence+1
                pending.generation = nil
                pending.sequence,pending.callback,pending.phase=self.sequence,callback_name,'returned'
                self.events[#self.events+1]=pending
                if #self.events>capacity then table.remove(self.events,1);self.discarded=self.discarded+1 end
            end
            return retval
        end)
    end
    function self:start()
        if not self.enabled then return false,'observer_stopped' end
        if self.started then return true end
        -- Registration belongs to an already loaded scene, outside a death
        -- callback. Do not patch this gameplay method during asynchronous load.
        local ok,ready=pcall(function()
            local flow,save=sdk.get_managed_singleton(flow_name),sdk.get_managed_singleton(save_name)
            return flow~=nil and save~=nil and flow:call('get_IsInTitle')==false
                and flow:call('get_IsInLoadGameData')==false and flow:call('get_IsFinishedLoadScene')==true
                and save:call('get_IsBusy')==false
        end)
        if not ok or not ready then return false,'gameplay_not_ready' end
        if not pcall(install_hook) then self.enabled=false;return false,'hook_registration_failed' end
        self.started=true
        return true
    end
    function self:snapshot()
        return {callback=callback_name,concrete_type=concrete_type,dispatch_matches_concrete=true,
            started=self.started,sequence=self.sequence,discarded=self.discarded,read_errors=self.read_errors,events=clone(self.events)}
    end
    function self:stop() self.enabled=false end
    return self
end
return M
