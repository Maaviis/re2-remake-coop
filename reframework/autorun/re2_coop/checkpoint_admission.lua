-- Local read admission only. The caller still owns the paired load barrier.
local M = {}
local function hex(value, size)
    return type(value) == 'string' and #value == size and value:match('^[0-9a-f]+$') ~= nil
end
local function ref_equal(a,b)
    return type(a)=='table' and type(b)=='table' and a.mode==b.mode and a.slot_id==b.slot_id
        and a.scenario==b.scenario and a.timestamp==b.timestamp
end
function M.read(guard, reference, id, guard_run_id, now)
    assert(hex(id,32) and type(guard_run_id)=='string' and #guard_run_id>0 and #guard_run_id<=128,
        'checkpoint_admission_identity_invalid')
    local binding=guard.protection.current
    assert(binding and binding.runtime==true and hex(binding.campaign_namespace,32)
        and guard:campaign_ready(binding), 'checkpoint_admission_mount_unavailable')
    local function fresh(name,field)
        local value=json.load_file(name)
        local at=type(value)=='table' and value[field or 'at']
        assert(type(value)=='table' and value.schema==1 and math.type(at)=='integer'
            and now>=at and now-at<=3, 'checkpoint_admission_receipt_expired')
        return value
    end
    local workspace=fresh('re2_coop_checkpoint_workspace.json')
    local native=fresh('re2_coop_native_save_guard.json')
    local catalog=fresh('re2_coop_checkpoint_catalog.json')
    local lobby=fresh('re2_coop_lobby.json','written_at')
    local selected=workspace.selection or {}
    local protected=workspace.protection or {}
    local scope=workspace.scope or {}
    local member=scope.membership or {}
    local native_job=native.checkpoint_import or {}
    assert(workspace.phase=='ready' and workspace.request_id==id and workspace.game_pid==binding.game_pid
        and protected.game_pid==binding.game_pid and protected.run_id==binding.run_id
        and protected.campaign_namespace==binding.campaign_namespace
        and workspace.guard_run_id==guard_run_id and ref_equal(workspace.native_reference,reference)
        and hex(selected.namespace,32) and hex(selected.digest,64), 'checkpoint_admission_workspace_changed')
    assert(native.active==true and native.source=='steam_storage_guard' and native.reason=='ok'
        and native.game_pid==binding.game_pid and native.run_id==binding.run_id
        and native.campaign_namespace==binding.campaign_namespace
        and native.app_id==883710 and native.build_id==11636119 and native.interface=='014' and native.guarded_methods==10
        and native_job.request_id==id and native_job.workspace==binding.campaign_namespace
        and native_job.archive_namespace==selected.namespace and native_job.generation==selected.digest
        and native_job.phase=='ready' and native_job.file_index==3 and native_job.native_result==1,
        'checkpoint_admission_native_import_changed')
    assert(catalog.phase=='ready' and catalog.request_id==id and catalog.game_pid==binding.game_pid
        and catalog.run_id==binding.run_id and catalog.guard_run_id==guard_run_id
        and catalog.workspace==binding.campaign_namespace and catalog.archive_namespace==selected.namespace
        and catalog.generation==selected.digest and ref_equal(catalog.reference,reference),
        'checkpoint_admission_catalog_changed')
    local files,count=workspace.files or {},0
    for name,digest in pairs(files) do
        assert((name=='data000.bin' or name=='data021Slot.bin' or name=='data00-1.bin') and hex(digest,64),
            'checkpoint_admission_files_invalid')
        count=count+1
    end
    assert(count==3,'checkpoint_admission_files_invalid')
    local data=(lobby.lobby or {}).data or {}
    local choice=(data.settings or {}).coop_checkpoint or {}
    local live_member=lobby.steam_membership or {}
    assert(scope.game_pid==binding.game_pid and hex(scope.session_id,32)
        and hex(member.session_id,32) and math.type(member.revision)=='integer' and member.revision>0
        and math.type(workspace.lobby_revision)=='integer' and workspace.lobby_revision>=0
        and lobby.game_pid==binding.game_pid and lobby.role==scope.role and lobby.connected==true
        and (scope.role=='H' and lobby.steam_lobby=='owned' or scope.role=='G' and lobby.steam_lobby=='joined')
        and live_member.session_id==member.session_id and live_member.revision==member.revision
        and lobby.lobby.session_id==scope.session_id and data.connected==true and data.revision==workspace.lobby_revision
        and data.new_game==nil and data.save_ref==nil and data.save_slot==nil
        and choice.namespace==selected.namespace and choice.digest==selected.digest and choice.scenario==reference.scenario,
        'checkpoint_admission_lobby_changed')
    return {game_pid=binding.game_pid,run_id=binding.run_id,campaign_namespace=binding.campaign_namespace}
end
return M
