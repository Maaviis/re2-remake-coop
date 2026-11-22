-- Observe active enemies and apply positive host HP during a released Steam campaign.
if reframework:get_game_name() ~= 're2' or sdk.get_tdb_version() ~= 70 then return end

local campaign = require('re2_coop.campaign_pose_scope')
local run_id = 'campaign-enemies-' .. os.time() .. '-' .. tostring({})
local sequence, frames = 0, 0
local active_attempt, last_sample_at
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
    if player and player:get_address() == context.player_address then return context end
end

local function authorize(receipt)
    local scope = campaign.read_release()
    if not scope or scope.role ~= 'G' or scope.request_id ~= receipt.load.request_id
        or scope.session_id ~= receipt.session_id or scope.attempt_id ~= receipt.campaign_attempt
        or not campaign.peer_matches(scope) then return false end
    local context = current_context(scope)
    return context ~= nil and campaign.same_area(context.area, receipt.view.campaign_area)
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
    if not before then return nil, 'campaign_context_unavailable' end
    local state, reason = reader.capture()
    if not state then return nil, reason end
    local current = campaign.read_release()
    if not current or current.attempt_id ~= scope.attempt_id or current.request_id ~= scope.request_id
        or current.snapshot_epoch ~= scope.snapshot_epoch or not campaign.peer_matches(current) then
        return nil, 'campaign_scope_changed'
    end
    local after = current_context(current)
    if not after or before.scene_address ~= after.scene_address or before.player_address ~= after.player_address
        or not campaign.same_area(before.area, after.area) or state.checkpoint.scenario ~= after.area.scenario then
        return nil, 'campaign_context_changed'
    end
    state.campaign_area = after.area
    return state, 'ok'
end

-- Resolve REFramework modules and install callbacks during autorun initialization.
local guest_ok, guest_error = pcall(function()
    local hp = require('re2_coop.guest_enemy_hp').new({damage_only=true, authorize=authorize})
    require('re2_coop.guest_enemy_readback').install(hp, {campaign=true})
end)
if not guest_ok then log.info('RE2_COOP_CAMPAIGN_ENEMIES guest HP unavailable: ' .. tostring(guest_error)) end

re.on_pre_application_entry('UpdateBehavior', function()
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local scope = campaign.read_release()
    if not scope or not campaign.peer_matches(scope) then
        if active_attempt then publish(nil, 'campaign_scope_unavailable') end
        active_attempt, last_sample_at = nil, nil
        return
    end
    if active_attempt ~= scope.attempt_id then
        publish(nil, 'campaign_scope_changed')
        active_attempt, last_sample_at = scope.attempt_id, nil
    end
    local now = os.time()
    if now == last_sample_at then return end
    last_sample_at = now
    local ok, state, reason = pcall(observe, scope)
    if not ok then state, reason = nil, 'campaign_enemy_read_failed' end
    publish(state, reason)
end)

re.on_script_reset(function()
    if active_attempt then publish(nil, 'script_reset') end
end)
