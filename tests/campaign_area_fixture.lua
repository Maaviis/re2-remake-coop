return function(sdk, fixture)
    local root = 'app.ropeway.'
    local flow_name = root .. 'gamemastering.MainFlowManager'
    local enemy_name = root .. 'EnemyManager'
    local find_type_definition = sdk.find_type_definition
    local get_managed_singleton = sdk.get_managed_singleton
    local flow = {}
    local getters = {
        get_IsInTitle = {'System.Boolean', 'title'},
        get_IsInLoadGameData = {'System.Boolean', 'loading'},
        get_IsFinishedLoadScene = {'System.Boolean', 'finished'},
        get_CurrentScenarioType = {flow_name .. '.ScenarioType', 'scenario'},
        get_LastPlayerStaySceneID = {root .. 'gamemastering.Map.ID', 'map'},
        get_LastPlayerStaySceneArea = {root .. 'gamemastering.Map.Area', 'area'},
    }
    sdk.find_type_definition = function(name)
        if name ~= flow_name and name ~= enemy_name then return find_type_definition(name) end
        return {get_method = function(_, method)
            local spec = assert(getters[method])
            return {
                is_static = function() return name == enemy_name end,
                get_param_types = function() return {} end,
                get_return_type = function() return {get_full_name = function() return spec[1] end} end,
                call = function(_, receiver)
                    assert(receiver == (name == flow_name and flow or nil))
                    if spec[2] == 'title' then return false end
                    if spec[2] == 'loading' then return fixture.loading == true end
                    if spec[2] == 'finished' then return fixture.finished ~= false end
                    return fixture.native_area and fixture.native_area[spec[2]]
                end,
            }
        end}
    end
    sdk.get_managed_singleton = function(name)
        if name == flow_name then return flow end
        return get_managed_singleton(name)
    end
end
