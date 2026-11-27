package.path = 'reframework/autorun/?.lua;' .. package.path
local module = require('re2_coop.checkpoint_catalog')
local function copy(t)
    if type(t) ~= 'table' then return t end
    local result = {}; for k,v in pairs(t) do result[k]=copy(v) end; return result
end
local native = {schema=1,source='steam_storage_guard',active=true,reason='ok',app_id=883710,build_id=11636119,
    guarded_methods=10,interface='014',at=100,game_pid=42,run_id=string.rep('a',32),campaign_namespace=string.rep('b',32),
    checkpoint_import={request_id=string.rep('c',32),workspace=string.rep('b',32),archive_namespace=string.rep('d',32),
        generation=string.rep('e',64),phase='ready',file_index=3,native_result=1}}
local state = {active=true,hooks=26,protection_active=true,runtime_protection=true,
    protection={game_pid=42,run_id=string.rep('a',32),campaign_namespace=string.rep('b',32)},
    campaign_mount_ready=string.rep('b',32),guard_run_id='vm',in_title=true,has_player=false,
    loading_flow=false,busy=false,allowed_load_calls=0,denied_loads=0,writes={},title_open=true}
local writes,pending,accessible,stamp,scenario,metadata,player = 0,false,true,639001000000000000,0,true,nil
local update = {
    is_static=function() return metadata end,
    get_param_types=function() return {{get_full_name=function() return 'via.UserIndex' end}} end,
    get_return_type=function() return {get_full_name=function() return 'System.Void' end} end,
    call=function(_,self,index) assert(self==nil and index==0);writes=writes+1 end}
local request = {
    is_static=function() return true end,get_param_types=function() return {} end,
    get_return_type=function() return {get_full_name=function() return 'System.Boolean' end} end,
    call=function() return pending end}
local detail = {call=function(_,name)
    return ({get_EmptyData=false,get_Slot=0,get_LastUpdateTimeStamp=stamp})[name]
end}
local manager = {call=function(_,name,mode,slot)
    if name=='getSaveFileDetail' then assert(mode==1 and slot==0);return detail end
    if name=='getScenarioTypeFromDetailString' then assert(mode==detail);return scenario end
    if name=='get_IsEnableAccessSaveFileDetailTbl' then return accessible end
    assert(name=='get_IsBusy' or name=='get_IsErrorBusy');return false
end}
local flow = {call=function(_,name) assert(name=='get_IsInTitle' or name=='get_IsInLoadGameData');return name=='get_IsInTitle' end}
local gui = {call=function(_,name) assert(({isBusyLoad=true,isBusyMenuStory=true,isTitleMenuOpened=true,isBusyMenuMain=true})[name]);return name=='isTitleMenuOpened' end}
reframework={get_game_name=function() return 're2' end}
sdk={get_tdb_version=function() return 70 end,
    get_managed_singleton=function(name) assert(name=='app.ropeway.PlayerManager');return player end,
    find_type_definition=function(name)
        assert(name=='via.storage.saveService.SaveService')
        return {get_method=function(_,method)
            assert(method=='updateSaveFileDetailTbl' or method=='get_SaveFileDetailUpdateRequest')
            return method=='updateSaveFileDetailTbl' and update or request
        end}
    end}
local function tick(catalog,n,s,now)
    n.at=now;return catalog(n,s,manager,flow,gui,now)
end
local catalog=module.new()
assert(tick(catalog,native,state,100).phase=='refreshing' and writes==1)
assert(tick(catalog,native,state,101).phase=='refreshing')
local proof=tick(catalog,native,state,102)
assert(proof.phase=='ready' and proof.reference.timestamp==tostring(stamp) and writes==1)
assert(tick(catalog,native,state,103).phase=='ready' and writes==1, 'duplicate import repeated native update')
stamp=stamp+10000000
assert(tick(catalog,native,state,104).phase=='failed' and proof.phase=='ready', 'changed reference retained confirmation or mutated old proof')
stamp=stamp-10000000
assert(tick(catalog,native,state,105).phase=='failed', 'failed job revived')

for _,change in ipairs({function(n) n.checkpoint_import.native_result=2 end,function(n) n.checkpoint_import.file_index=2 end,
    function(n) n.game_pid=43 end,function(n) n.run_id=string.rep('f',32) end,
    function(n,s) s.has_player=true end,function(n,s) s.protection.campaign_namespace=string.rep('f',32) end}) do
    local n,s=copy(native),copy(state);change(n,s)
    local before=writes;assert(tick(module.new(),n,s,100)==nil and writes==before,'invalid import reached native update')
end
catalog=module.new();tick(catalog,native,state,100);pending=true
assert(tick(catalog,native,state,109).phase=='failed','refresh deadline ignored')
pending=false;assert(tick(catalog,native,state,110).phase=='failed','late update revived timeout')
catalog=module.new();tick(catalog,native,state,100)
local lost=copy(state);lost.protection_active=false
assert(tick(catalog,native,lost,101).phase=='failed')
assert(tick(catalog,native,state,102).phase=='failed')
metadata=false
local before=writes;assert(tick(module.new(),native,state,100).phase=='failed' and writes==before)
metadata=true;player={call=function() return {} end}
before=writes;assert(tick(module.new(),native,state,100)==nil and writes==before)
player=nil
catalog=module.new();tick(catalog,native,state,100)
stamp=stamp+10000000;tick(catalog,native,state,101)
stamp=stamp+10000000;assert(tick(catalog,native,state,102).phase=='refreshing')
assert(tick(catalog,native,state,103).phase=='ready','stable refreshed reference not confirmed')
print('Checkpoint catalog: verified import, exact native update, stable local reference, scope loss and no load/save calls passed')
