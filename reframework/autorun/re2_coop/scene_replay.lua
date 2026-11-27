-- One host-observed occurrence. Each new host state starts its own monotonic clock.
local M = {}
local function same(a,b)
    return a and b and a.event==b.event and a.occurrence==b.occurrence and a.phase==b.phase
        and a.vote==b.vote and a.decision==b.decision
end
local function milliseconds(v)
    return math.type(v)=='integer' and v>=0 and v<=600000
end
function M.new(plan, valid, clock)
    if type(plan.groups)~='table' or #plan.groups<1 or #plan.groups>180 then return end
    local count=0
    for _,group in ipairs(plan.groups) do
        if type(group)~='table' or not valid(group.host) or group.host.event~=plan.event
            or group.host.occurrence~=plan.occurrence or not milliseconds(group.duration)
            or type(group.steps)~='table' or #group.steps==0 then return end
        local last=-1
        for i,step in ipairs(group.steps) do
            if type(step)~='table' or not milliseconds(step.ms) or step.ms<last
                or step.ms>group.duration or (i==1 and step.ms~=0)
                or (step.peer~=false and not valid(step.peer)) then return end
            count=count+1
            if count>180 then return end
            last=step.ms
        end
    end
    if not clock then
        local method=assert(sdk.find_type_definition('via.Application'):get_method('get_UpTimeSecond'))
        clock=function() return method:call(nil)*1000 end
    end
    local index,started=1,nil
    local player={}
    function player:sample(host)
        local group=plan.groups[index]
        if not host or host.event~=plan.event or host.occurrence~=plan.occurrence then return nil,'other_scene' end
        local now=clock()
        if started and plan.groups[index+1] and same(host,plan.groups[index+1].host) then
            index,started=index+1,now
            group=plan.groups[index]
        end
        if not same(host,group.host) then return nil,started and 'host_mismatch' or 'seek_host' end
        started=started or now
        local elapsed=now-started
        if elapsed>group.duration then
            return nil,index==#plan.groups and 'finished' or 'waiting_host'
        end
        local step=group.steps[1]
        for i=2,#group.steps do
            if elapsed<group.steps[i].ms then break end
            step=group.steps[i]
        end
        if not step.peer then return nil,'recorded_gap' end
        return step.peer,'playing'
    end
    return player
end
return M
