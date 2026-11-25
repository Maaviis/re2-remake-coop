local M = dofile('reframework/autorun/re2_coop/new_game.lua')
local flow_name = 'app.ropeway.gamemastering.MainFlowManager'
local title_name = 'app.ropeway.gamemastering.TitleFlow'
local gui_name = 'app.ropeway.gui.GUIMaster'
local names = {ScenarioType={LEON_A=0,CLAIRE_A=1}, Difficulty={EASY=0,NORMAL=1,HARD=2}, State={FINALIZE=29}}
local args = {setupNewGame=flow_name..'.ScenarioType',setDifficulty=flow_name..'.Difficulty',
    set_StateValue=title_name..'.State',closeMenuMain='System.Action',closeTitleMenu='System.Action'}
local returns = {get_CurrentDifficulty=flow_name..'.Difficulty',get_CurrentScenarioType=flow_name..'.ScenarioType',
    get_StateValue=title_name..'.State',goResetGameToTitle='System.Void',
    get_Title=title_name,get_CurrentPlayer='via.GameObject'}
local now, state, calls, guard, loader, controller, title, flow, gui, player, binding
os.time = function() return now end
reframework = {get_game_name=function() return 're2' end}
local function type_of(name) return {get_full_name=function() return name end} end
local function reflect(name)
    local t = type_of(name)
    function t:get_method(method)
        return {is_static=function() return false end,
            get_return_type=function() return type_of(returns[method] or (args[method] and 'System.Void' or 'System.Boolean')) end,
            get_param_types=function() return args[method] and {type_of(args[method])} or {} end,
            call=function(_,obj,...) return obj:call(method,...) end}
    end
    function t:get_field(member)
        local v = names[name:match('([^.]+)$')][member]
        return v and {is_static=function() return true end,get_data=function() return v end}
    end
    return t
end
local function fixture()
    now, calls, binding = 100, {}, {game_pid=10,run_id='r'}
    state = {get_IsInTitle=true,get_IsInLoadGameData=false,get_IsFinishedLoadScene=false,
        get_IsBusy=false,get_IsErrorBusy=false,isTitleMenuOpened=true,isBusyMenuMain=true,get_StateValue=100,
        isBusyMenuStory=false,isBusyMenuScenario=false,isBusySelectDifficulty=false,isBusyLoad=false}
    local function object(address)
        return {get_address=function() return address end,call=function(self, method, arg)
            if method == 'get_Title' then return title end
            if method == 'get_CurrentPlayer' then return player end
            if args[method] or method == 'goResetGameToTitle' then
                calls[#calls+1]={method,arg}
                if method == state.throws then error('native failure') end
                return
            end
            assert(state[method]~=nil,method)
            return state[method]
        end}
    end
    flow, gui, title, player = object(10), object(11), object(12), nil
    sdk={get_tdb_version=function() return 70 end,find_type_definition=reflect,
        get_managed_singleton=function(name)
            if name==flow_name then return flow elseif name==gui_name then return gui
            elseif name=='app.ropeway.PlayerManager' and state.player_manager_absent then return nil
            else return object(13) end
        end}
    guard={policy=nil,writes={},active=true,hook_count=26,denied_loads=0,allowed_load_calls=0,
        protection={current=binding, ready=function() return true end,
            matches=function(_,v) return binding and binding.game_pid==v.game_pid and binding.run_id==v.run_id end}}
    loader={phase='idle',error=''}
    controller=M.new(guard,loader)
end
local function selected() return {scenario='CLAIRE_A',difficulty='HARD'} end
local function start() assert(controller:start(selected(), 'attempt', binding)) end
local function poll() controller:poll(true,function() return true end) end
fixture()
assert(controller:ready(selected(),binding))
start()
assert(calls[1][1]=='setDifficulty' and calls[1][2]==2)
assert(calls[2][1]=='setupNewGame' and calls[2][2]==1 and calls[3][1]=='closeTitleMenu' and calls[4][1]=='closeMenuMain')
assert(not controller:start(selected(),'duplicate',binding))
poll(); assert(#calls==4 and loader.phase=='closing_menu')
state.isTitleMenuOpened=false
poll(); assert(#calls==4)
state.isBusyMenuMain,state.isTitleMenuOpened=false,true
poll(); assert(#calls==4)
state.isTitleMenuOpened=false
poll()
assert(calls[5][1]=='set_StateValue' and calls[5][2]==29 and loader.phase=='loading')
state.get_IsInTitle,state.get_IsFinishedLoadScene,state.get_CurrentScenarioType,state.get_CurrentDifficulty=false,true,1,2
player={get_address=function() return 14 end}
poll(); assert(loader.phase=='scene_loaded')
assert(not controller:start(selected(),'duplicate',binding))
assert(controller:world(function() return {scenario=1,map=9,area=4} end).difficulty==2)
assert(not controller:world(function() return {scenario=1,map=0,area=0} end))
assert(not controller:world(function() return {scenario=1,map=435,area=2} end))
assert(not controller:world(function() return {scenario=1,map=9,area=6} end))
state.get_CurrentDifficulty=0
assert(not controller:world(function() return {scenario=1,map=9,area=4} end))

-- The native menu can finish its close animation after the lobby has gone away.
for _, already_closed in ipairs({false,true}) do
    fixture(); start()
    state.isTitleMenuOpened,state.isBusyMenuMain=not already_closed,not already_closed
    controller:poll(false,function() error('lost lobby must never finalize') end)
    assert(loader.phase=='failed' and loader.error=='new_game_lobby_changed')
    assert(#calls==5 and calls[5][1]=='goResetGameToTitle','lost lobby left the native title without a menu')
    poll(); assert(#calls==5,'recovery must be issued only once')
    assert(not controller:reset_failed(),'pending menu closure or a still-empty title must not admit a retry')
    state.isTitleMenuOpened,state.isBusyMenuMain=false,false
    assert(not controller:recoverable())
    state.isBusyMenuMain=true
    assert(controller:recoverable() and loader.phase=='failed' and loader.request_id=='attempt')
    assert(not controller:start(selected(),'unrequested',binding),'old request must stay consumed')
    assert(controller:reset_failed() and loader.phase=='idle' and loader.request_id==nil and loader.new_game==nil)
    assert(controller:start(selected(),'explicit-retry',binding) and loader.request_id=='explicit-retry')
end
fixture(); state.throws='setupNewGame'
assert(not controller:start(selected(),'attempt',binding) and #calls==2,'failure before closing must leave the native title alone')
fixture(); start(); state.get_StateValue=29
controller:poll(false,function() return false end); assert(#calls==4,'another title transition owns the screen')
fixture(); start(); state.get_IsInTitle=false
controller:poll(false,function() return false end); assert(#calls==4,'must never send gameplay back to the title')
fixture(); start(); guard.active=false
poll(); assert(loader.error=='new_game_protection_lost' and #calls==4,'title reset requires the native save hooks')
fixture(); start(); guard.allowed_load_calls=1
poll(); assert(loader.error=='new_game_protection_lost' and #calls==4,'must never reset over an admitted load')
fixture(); start(); title={get_address=function() return 99 end}
controller:poll(false,function() return false end); assert(#calls==4,'must never reset a replaced title')
fixture(); start(); state.isTitleMenuOpened,state.isBusyMenuMain=false,false
poll(); assert(loader.phase=='loading')
controller:poll(false,function() return false end)
assert(loader.phase=='failed' and #calls==5 and calls[5][2]==29,'finalization transfers title ownership to the game')
assert(not controller:reset_failed(),'post-finalize failure cannot be replayed')
fixture(); start(); state.throws='goResetGameToTitle'
controller:poll(false,function() return false end)
assert(loader.error=='new_game_lobby_changed' and not controller:reset_failed(),'a throwing native reset must not admit a retry')
fixture(); guard.policy={slot_id=4}; assert(not controller:ready(selected(),binding) and #calls==0)
fixture(); state.player_manager_absent=true; assert(controller:ready(selected(),binding))
fixture(); assert(not controller:ready({scenario='LEON_B',difficulty='NORMAL'},binding))
fixture(); start(); now=109; poll(); assert(loader.phase=='failed' and calls[5][1]=='goResetGameToTitle')
fixture(); start(); binding=nil; poll(); assert(loader.phase=='failed' and calls[5][1]=='goResetGameToTitle')
fixture(); start(); title={get_address=function() return 99 end}; poll(); assert(loader.phase=='failed')
fixture(); start(); state.isBusyMenuMain,state.isTitleMenuOpened=false,false
controller:poll(true,function() return false end); poll()
assert(loader.phase=='failed' and #calls==5 and calls[5][1]=='goResetGameToTitle' and not controller:start(selected(),'retry',binding))
print('Native fresh campaign validates selection, setup order, menu ownership, no replay and fresh world readback')
fixture()
local scope = string.rep('a',32)
binding.campaign_namespace = scope
guard.campaign_mode = true
local mounted = false
function guard:campaign_ready(receipt) return mounted and receipt.campaign_namespace == scope end
assert(not controller:ready(selected(),binding),'direct campaign started before readback')
mounted=true; start()
state.isBusyMenuMain,state.isTitleMenuOpened=false,false
poll()
assert(loader.phase=='loading','namespace was lost after stage')
mounted=false
poll()
assert(loader.phase=='failed' and loader.error=='new_game_protection_lost')
