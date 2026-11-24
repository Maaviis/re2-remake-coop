-- One story occurrence per paired campaign. Native update callbacks retry admission in place.
local M = {}
local function integer(x, min)
    return type(x) == 'number' and x % 1 == 0 and x >= min and x <= 0x7fffffff
end
local phases = {waiting=true, playing=true, ended=true}
local decisions = {none=true, request=true, accept=true, decline=true}
function M.document(d, now, simulated)
    return type(d)=='table' and d.schema==1 and integer(d.game_pid,1)
        and (d.role=='H' or d.role=='G') and type(d.attempt_id)=='string'
        and #d.attempt_id==32 and d.attempt_id:match('^[0-9a-f]+$') ~= nil
        and (d.simulated==true)==simulated and type(d.at)=='number' and d.at%1==0
        and now>=d.at and now-d.at<=2
end

local function valid_peer(p)
    return type(p)=='table' and type(p.event)=='string' and #p.event<=32 and p.event:match('^evt_%d+$')
        and integer(p.occurrence,1) and phases[p.phase] and decisions[p.decision] and integer(p.vote,0)
        and ((p.vote==0)==(p.decision=='none'))
end
function M.new(clock)
    clock=clock or os.time
    local self = {counts={}, owners={}, deferred={}}
    function self:clear()
        self.scope,self.link,self.scene,self.applied=nil,nil,nil,nil
        self.counts,self.owners,self.deferred={},{},{}
    end
    function self:connect(doc)
        local old=self.scope
        if doc and old and (doc.attempt_id~=old.attempt_id or doc.game_pid~=old.game_pid
                or doc.role~=old.role or doc.simulated~=old.simulated) then self:clear() end
        if not doc and old and old.simulated then self:clear() end
        if doc then self.scope=doc end
        self.link=doc
        local s,p=self.scene,self:peer()
        if s and p and s.decision=='request' and p.vote==s.vote and p.decision=='decline' then
            s.decision='decline'
        end
    end
    function self:peer()
        local p=self.link and self.link.peer
        local s=self.scene
        if valid_peer(p) and s and p.event==s.event and p.occurrence==s.occurrence
            and M.document(self.link,clock(),self.link.simulated==true) then return p end
    end
    function self:record()
        local s=self.scene
        if not s then return nil end
        return {event=s.event,occurrence=s.occurrence,phase=s.phase,vote=s.vote,decision=s.decision}
    end
    function self:admit(event,owner)
        local linked=self.link and M.document(self.link,clock(),self.link.simulated==true)
        if not linked and not self.owners[owner] then return not self.deferred[owner] end
        local s=self.scene
        if s and s.phase=='waiting' and s.event~=event then
            local p=linked and self.link.peer
            if self.scope.role=='G' and valid_peer(p) and p.event==event
                and p.occurrence==(self.counts[event] or 0)+1 then
                -- Two distinct receivers may tick in opposite orders. The guest
                -- can select the host's occurrence only after reaching it locally.
                for k in pairs(self.owners) do self.deferred[k]=true end
                self.owners={}
                self.counts[s.event]=s.occurrence-1
                s=nil
            end
        end
        if s and s.phase=='ended' and s.admitted then
            -- Keep the last decision advertised until both finished. If the other
            -- player already advanced, its next arrival also acknowledges this end.
            local p=self:peer()
            if not linked or not valid_peer(self.link.peer) or p and p.phase~='ended' then
                self.deferred[owner]=true
                return false
            end
        end
        if not s or s.phase=='ended' then
            self.counts[event]=(self.counts[event] or 0)+1
            s={event=event,occurrence=self.counts[event],phase='waiting',vote=0,decision='none'}
            self.scene,self.applied=s,false
        end
        if s.event~=event then self.deferred[owner]=true; return false end
        self.deferred[owner]=nil
        self.owners[owner]=true
        local p=self:peer()
        if s.phase=='waiting' and p then s.phase,s.admitted='playing',true end
        return s.phase=='playing'
    end
    function self:finish(owner)
        self.deferred[owner]=nil
        if not self.owners[owner] then return end
        self.owners[owner]=nil
        if not next(self.owners) then self.scene.phase='ended' end
    end
    function self:incoming()
        local p,s=self:peer(),self.scene
        if not p or s.phase~='playing' or p.phase~='playing' or p.decision~='request' then return false end
        return p.vote>s.vote or (p.vote==s.vote and s.decision=='request' and self.scope.role=='G')
    end
    function self:authorized()
        local p,s=self:peer(),self.scene
        return p~=nil and s.phase=='playing' and (p.phase=='playing' or p.phase=='ended') and s.vote==p.vote
            and (s.decision=='request' and p.decision=='accept' or s.decision=='accept' and p.decision=='request')
    end
    function self:request()
        local p,s=self:peer(),self.scene
        if not p or p.phase~='playing' or s.phase~='playing' or self.applied or self:incoming() or self:authorized() then return end
        if s.decision=='request' and (p.decision~='decline' or p.vote~=s.vote) then return end
        s.vote,s.decision=math.max(s.vote,p.vote)+1,'request'
    end
    function self:answer(yes)
        if self:incoming() then
            self.scene.vote,self.scene.decision=self:peer().vote,yes and 'accept' or 'decline'
        end
    end
    return self
end
return M
