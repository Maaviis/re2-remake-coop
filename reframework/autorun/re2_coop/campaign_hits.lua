-- Relay only attributable positive HP loss within one released campaign area.
local M = {}
local readback = require('re2_coop.guest_enemy_readback')
local campaign = require('re2_coop.campaign_pose_scope')
local guest_name = 're2_coop_campaign_guest_hits.json'
local incoming_name = 're2_coop_campaign_incoming_hits.json'
local applied_name = 're2_coop_campaign_hit_application.json'
local max_hits = 8

local function write_source(scope, area, hits, now)
    json.dump_file(guest_name, {schema=1, request_id=scope and scope.request_id,
        attempt_id=scope and scope.attempt_id, at=now, area=area, hits=hits})
end

local function positive_loss(event, now)
    return readback.fresh(event.at, now) and event.before.attacker == 'local_player'
        and event.after.attacker == 'local_player' and event.after.Damage > 0
        and event.hp_on_exit > 0 and event.hp_on_entry > event.hp_on_exit
end

local function read_scoped(name, scope)
    local raw = fs.read(name)
    if type(raw) ~= 'string' or #raw == 0 or #raw > 4096 then return nil end
    local decoded, receipt = pcall(json.load_string, raw)
    if decoded and type(receipt) == 'table' and receipt.schema == 1
        and receipt.attempt_id == scope.attempt_id and receipt.request_id == scope.request_id then return receipt end
end

function M.new(observer, observe, apply)
    local binding, queued, seen = nil, {}, 0
    local host_attempt, consumed, failed
    local function clear(now)
        if binding then
            binding, queued = nil, {}
            if observer then observer:set_local_player(nil) end
            write_source(nil, nil, queued, now)
        end
    end

    local function guest(scope, context, now)
        if not observer then return end
        local owner = context.player
        if binding ~= context.visit then
            seen, queued = observer.sequence, {}
            binding = context.visit
            observer:set_local_player(owner, binding)
            write_source(scope, context.area, queued, now)
            return
        end
        if seen >= observer.sequence then return end
        local snapshot = observer:snapshot()
        local candidates = {}
        for _, event in ipairs(snapshot.events) do
            if event.sequence > seen and positive_loss(event, now) then candidates[#candidates + 1] = event end
        end
        if #candidates == 0 then seen = snapshot.sequence; return end
        local state = observe(scope)
        if not state or not campaign.same_area(context.area, state.campaign_area) then return end
        local active, recent = {}, {}
        for _, row in ipairs(state.entries) do
            if row.live.active and row.live.is_live and not row.live.is_dead then active[row.id] = row end
        end
        for _, hit in ipairs(queued) do
            if readback.fresh(hit.at, now) then recent[#recent + 1] = hit end
        end
        for _, event in ipairs(candidates) do
            local row = active[event.id]
            if row and event.hp_on_entry <= row.live.default_hp then
                recent[#recent + 1] = {sequence=event.sequence, id=event.id, at=event.at, kind_id=row.kind_id,
                    inherit_id=row.live.inherit_id, default_hp=row.live.default_hp,
                    damage=event.hp_on_entry - event.hp_on_exit}
            end
        end
        while #recent > max_hits do table.remove(recent, 1) end
        write_source(scope, context.area, recent, now)
        seen, queued = snapshot.sequence, recent
    end

    local function host(scope, context, now)
        if not apply or failed then return end
        if host_attempt ~= scope.attempt_id then
            local previous = read_scoped(applied_name, scope)
            consumed = previous and math.type(previous.sequence) == 'integer' and previous.sequence or 0
            host_attempt = scope.attempt_id
        end
        local receipt = read_scoped(incoming_name, scope)
        if not receipt or not readback.fresh(receipt.at, now)
            or type(receipt.hits) ~= 'table' or #receipt.hits > max_hits then return end
        local same_visit = receipt.host_visit == context.visit and campaign.same_area(context.area, receipt.area)
        for _, hit in ipairs(receipt.hits) do
            if type(hit) == 'table' and math.type(hit.sequence) == 'integer' and hit.sequence > consumed then
                consumed = hit.sequence
                local record = {schema=1, at=now, attempt_id=scope.attempt_id, request_id=scope.request_id,
                    sequence=consumed, id=hit.id, phase='consumed'}
                json.dump_file(applied_name, record)
                if same_visit then
                    local ok, result = pcall(apply, hit, receipt)
                    if not ok then
                        failed = true
                        log.info('RE2_COOP_CAMPAIGN_HITS disabled after native application failure: ' .. tostring(result))
                        return
                    end
                    if result then
                        record.phase, record.before_hp, record.after_hp = 'applied', result.before_hp, result.after_hp
                        json.dump_file(applied_name, record)
                    end
                end
            end
        end
    end

    return {
        update=function(scope, context)
            local now = os.time()
            if scope and context and scope.role == 'G' then
                guest(scope, context, now)
            else
                clear(now)
                if scope and context and scope.role == 'H' then host(scope, context, now) end
            end
        end,
        reset=function()
            if observer then observer:stop() end
            clear(os.time())
        end,
    }
end

return M
