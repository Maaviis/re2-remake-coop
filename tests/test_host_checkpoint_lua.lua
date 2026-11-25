local make = dofile('reframework/autorun/re2_coop/host_checkpoint.lua').new
local stamp, requests, busy, reject = nil, 0, false, false
local detail = {call=function(_, name)
    if name == 'get_LastUpdateTimeStamp' then return stamp end
    if name == 'get_Slot' then return 0 end
    return false
end}
local manager = {call=function(_, name)
    if name == 'get_IsBusy' then return busy end
    if name == 'get_IsErrorBusy' then return false end
    if name == 'get_IsEnableAccessSaveFileDetailTbl' then return true end
    if name == 'getSaveFileDetail' then return stamp and detail end
    if name == 'getScenarioTypeFromDetailString' then return 0 end
    if name == 'requestSaveGameDataAuto' then requests=requests+1; return not reject end
    error(name)
end}
local flow = {call=function(_, name) return name == 'get_CurrentDifficulty' and 1 or 0 end}
sdk = {find_type_definition=function() return {get_method=function(_, name)
    return {call=function() if name == 'get_LastSaveFailed' then return false end; return 0 end}
end} end}
local ns = string.rep('a',32)
local req = {namespace=ns, id=string.rep('b',32), at=100, game_pid=12, release_id='release',
             load_request_id='load', snapshot_epoch='epoch'}
local campaign = {role='H', scenario=0, game_pid=12, protection_run_id='run', snapshot_epoch='epoch'}
local hold = {campaign=campaign, phase='released', native_phase='released', load_request_id='load',
              pause_id='load', release={id='release',snapshot_epoch='epoch'}}
local state = {active=true, hooks=26, protection_active=true, runtime_protection=true, in_title=false,
               loading_flow=false, scene_finished=true, has_player=true, load_hold=hold, campaign_mount_ready=ns,
               protection={game_pid=12, run_id='run', campaign_namespace=ns}}
local tick = make()
campaign.role='G'; assert(not tick(req,state,manager,flow,100) and requests == 0)
campaign.role='H'; hold.campaign=nil; assert(not tick(req,state,manager,flow,100) and requests == 0)
hold.campaign=campaign; state.campaign_mount_ready=nil; assert(not tick(req,state,manager,flow,100))
state.campaign_mount_ready=ns; stamp='639000000000000000'
assert(tick(req,state,manager,flow,100).phase=='saving' and requests==1)
assert(tick(req,state,manager,flow,101).phase=='saving')
busy=true; stamp='639000000100000000'; assert(tick(req,state,manager,flow,102).phase=='saving')
busy=false; local done=tick(req,state,manager,flow,103)
assert(done.phase=='complete' and done.timestamp==stamp and done.slot==0 and done.difficulty==1 and requests==1)
stamp='639000000200000000'; assert(tick(req,state,manager,flow,104).reason=='slot_changed_after_save')
assert(tick(req,state,manager,flow,104).phase=='failed' and requests==1)
tick=make(); reject=true
assert(tick(req,state,manager,flow,100).reason=='requestSaveGameDataAuto_rejected')
tick=make(); reject=false; tick(req,state,manager,flow,100); hold.phase='interrupted'
assert(tick(req,state,manager,flow,101).reason=='checkpoint_release_lost')
