-- Observe active enemies and apply positive host HP during a released Steam campaign.
if reframework:get_game_name() ~= 're2' or sdk.get_tdb_version() ~= 70 then return end

local campaign = require('re2_coop.campaign_pose_scope')
local run_id = 'campaign-enemies-' .. os.time() .. '-' .. tostring({})
local sequence, frames = 0, 0
local visit, visit_count, last_sample_at = nil, 0, nil
local ok, reader = pcall(function() return require('re2_coop.enemy_state').new() end)
if not ok then
    log.info('RE2_COOP_CAMPAIGN_ENEMIES observer unavailable: ' .. tostring(reader))
    return
end

local function current_context(scope)
    local context = campaign.observed_context(scope)
    if not context or not campaign.same_area(context.area, campaign.read_area())
        or campaign.scene_address() ~= context.scene_address then return nil end
    local manager = sdk.get_managed_singleton(sdk.game_namespace('PlayerManager'))
    local player = manager and manager:call('get_CurrentPlayer')
    if player and player:get_address() == context.player_address then
        context.player = player
        return context
    end
end

local function visit_matches(scope, context)
    return visit and context and visit.attempt == scope.attempt_id and visit.request == scope.request_id
        and visit.epoch == scope.snapshot_epoch and visit.player == context.player_address
        and visit.scene == context.scene_address and campaign.same_area(visit.area, context.area)
end

local function authorize(receipt)
    local scope = campaign.read_release()
    if not scope or scope.role ~= 'G' or scope.request_id ~= receipt.load.request_id
        or scope.session_id ~= receipt.session_id or scope.attempt_id ~= receipt.campaign_attempt
        or not campaign.peer_matches(scope) then return false end
    local context = current_context(scope)
    return context ~= nil and campaign.same_area(context.area, receipt.view.campaign_area)
end

local function authorize_hit(receipt)
    local scope = campaign.read_release()
    if not scope or scope.role ~= 'H' or scope.request_id ~= receipt.request_id
        or scope.attempt_id ~= receipt.attempt_id or not campaign.peer_matches(scope) then return false end
    local context = current_context(scope)
    return visit_matches(scope, context) and visit.token == receipt.host_visit
        and campaign.same_area(context.area, receipt.area)
end

local function publish(state, reason)
    sequence = sequence + 1
    pcall(json.dump_file, 're2_coop_campaign_enemy_state.json', {
        schema=1, source='re2', tdb=70, run_id=run_id, sequence=sequence, observed_at=os.time(),
        scope='registered_and_stored_enemy_contexts', available=state ~= nil, reason=reason, state=state,
    })
end

local function observe(scope)
    local before = current_context(scope)
    if not visit_matches(scope, before) then return nil, 'campaign_context_unavailable' end
    local state, reason = reader.capture()
    if not state then return nil, reason end
    local current = campaign.read_release()
    if not current or current.attempt_id ~= scope.attempt_id or current.request_id ~= scope.request_id
        or current.snapshot_epoch ~= scope.snapshot_epoch or not campaign.peer_matches(current) then
        return nil, 'campaign_scope_changed'
    end
    local after = current_context(current)
    if not visit_matches(current, after) or state.checkpoint.scenario ~= after.area.scenario then
        return nil, 'campaign_context_changed'
    end
    state.campaign_area, state.campaign_visit = after.area, visit.token
    return state, 'ok'
end

-- Resolve REFramework modules and install callbacks during autorun initialization.
local apply_hit
local guest_ok, guest_error = pcall(function()
    local hp, hit = require('re2_coop.guest_enemy_hp').new({
        damage_only=true, authorize=authorize, authorize_hit=authorize_hit,
    })
    apply_hit = hit
    require('re2_coop.guest_enemy_readback').install(hp, {campaign=true})
end)
if not guest_ok then log.info('RE2_COOP_CAMPAIGN_ENEMIES guest HP unavailable: ' .. tostring(guest_error)) end

local damage_ok, damage = pcall(function() return require('re2_coop.damage_observer').new({scoped=true}) end)
if not damage_ok then log.info('RE2_COOP_CAMPAIGN_ENEMIES guest hit observer unavailable: ' .. tostring(damage)) end
local hits = require('re2_coop.campaign_hits').new(damage_ok and damage or nil, observe, apply_hit)

re.on_pre_application_entry('UpdateBehavior', function()
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local scope = campaign.read_release()
    local context
    if scope and campaign.peer_matches(scope) then
        local resolved, observed = pcall(current_context, scope)
        if resolved then context = observed end
    end
    if not context then
        pcall(hits.update)
        if visit then publish(nil, 'campaign_scope_unavailable') end
        visit, last_sample_at = nil, nil
        return
    end
    if not visit_matches(scope, context) then
        visit_count = visit_count + 1
        visit = {token=run_id .. '-' .. visit_count, attempt=scope.attempt_id, request=scope.request_id,
            epoch=scope.snapshot_epoch, player=context.player_address, scene=context.scene_address, area=context.area}
        last_sample_at = nil
    end
    context.visit = visit.token
    pcall(hits.update, scope, context)
    local now = os.time()
    if now == last_sample_at then return end
    last_sample_at = now
    local ok, state, reason = pcall(observe, scope)
    if not ok then state, reason = nil, 'campaign_enemy_read_failed' end
    publish(state, reason)
end)

re.on_script_reset(function()
    pcall(hits.reset)
    if visit then publish(nil, 'script_reset') end
end)
