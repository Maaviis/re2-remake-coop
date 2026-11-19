#include <windows.h>
#include <reframework/API.h>
#include "storage_guard.h"
#include "storage_reads.h"
#include "storage_metadata.h"
#include <chrono>
#include <cctype>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <string>

namespace {
const REFrameworkPluginFunctions* ref{};
coop::StorageGuard guard;
coop::StorageReadObserver read_observer;
coop::StorageMetadataObserver metadata_observer;
bool observe_reads{};
bool observe_metadata{};
const char* metadata_reason="not_attached";
std::filesystem::path directory;
std::string run_id;
using Clock = std::chrono::steady_clock;
Clock::time_point next_report{};
constexpr std::uint32_t app_id = 883710;
constexpr std::int32_t build_id = 11636119;
const char* last_reason = "";

template<typename Function>
Function resolve(HMODULE module, const char* name) {
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(GetProcAddress(module, name));
}

void publish_reads(bool guard_active, const char* guard_reason) {
    if (!observe_reads) return;
    const bool active = guard_active && read_observer.intact();
    const auto reason = !guard_active ? guard_reason : active ? "ok"
        : read_observer.table() ? "read_table_changed" : read_observer.error();
    const auto counts = coop::storage_read_observation();
    const auto temp = directory / L"re2_coop_storage_reads.json.tmp";
    const auto target = directory / L"re2_coop_storage_reads.json";
    {
        std::ofstream file(temp, std::ios::binary | std::ios::trunc);
        file << "{\"schema\":3,\"source\":\"steam_storage_reads\",\"scope\":\"remote_storage_014_reads\",\"at\":" << std::time(nullptr)
             << ",\"game_pid\":" << GetCurrentProcessId() << ",\"run_id\":\"" << run_id
             << "\",\"app_id\":" << app_id << ",\"build_id\":" << build_id
             << ",\"active\":" << (active ? "true" : "false") << ",\"reason\":\""
             << reason << "\",\"counters\":{";
        for (std::size_t i = 0; i != counts.calls.size(); ++i) {
            if (i) file << ',';
            file << '"' << coop::storage_read_methods()[i].name << "\":" << counts.calls[i];
        }
        const auto& trace = counts.trace;
        file << "},\"sync_reported_bytes\":" << counts.sync_reported_bytes
             << ",\"classification_errors\":" << counts.classification_errors
             << ",\"trace_available\":" << (trace.available ? "true" : "false")
             << ",\"ledger\":{\"capacity\":" << coop::read_ticket_capacity
             << ",\"retained_keys\":" << trace.retained_keys << ",\"pending\":" << trace.pending
             << ",\"ambiguous_pending\":" << trace.ambiguous_pending
             << ",\"collisions\":" << trace.collisions << ",\"overflows\":" << trace.overflows
             << ",\"unmatched_completions\":" << trace.unmatched_completions
             << ",\"ambiguous_completions\":" << trace.ambiguous_completions
             << ",\"bookkeeping_errors\":" << trace.bookkeeping_errors << "},\"targets\":[";
        bool comma = false;
        for (std::size_t index = 0; index != trace.targets.size(); ++index) {
            const auto& value = trace.targets[index];
            if (!value.sync_calls && !value.async_requests && !value.completion_attempts) continue;
            if (comma) file << ',';
            comma = true;
            file << "{\"file\":";
            if (const auto name = coop::known_read_target(index)) file << '"' << name << '"';
            else file << "null";
            file << ",\"sync_calls\":" << value.sync_calls << ",\"sync_reported_bytes\":" << value.sync_reported_bytes
                 << ",\"async_requests\":" << value.async_requests << ",\"invalid_handles\":" << value.invalid_handles
                 << ",\"requested_bytes\":" << value.requested_bytes << ",\"last_offset\":" << value.last_offset
                 << ",\"last_requested_size\":" << value.last_requested_size
                 << ",\"completion_attempts\":" << value.completion_attempts
                 << ",\"completion_successes\":" << value.completion_successes
                 << ",\"completion_failures\":" << value.completion_failures
                 << ",\"successful_completion_bytes\":" << value.successful_completion_bytes
                 << ",\"oversized_completions\":" << value.oversized_completions;
            if (value.completion_attempts) file << ",\"last_completion_size\":" << value.last_completion_size
                << ",\"last_completion_ok\":" << (value.last_completion_ok ? "true" : "false");
            file << '}';
        }
        file << "],\"event_sequence\":" << trace.event_sequence
             << ",\"discarded_events\":" << trace.discarded_events << ",\"events\":[";
        for (std::size_t index = 0; index != trace.event_count; ++index) {
            const auto& event = trace.events[index];
            if (index) file << ',';
            file << "{\"sequence\":" << event.sequence << ",\"request_id\":" << event.request_id
                 << ",\"phase\":\"" << coop::read_phase_name(event.phase) << "\",\"file\":";
            if (const auto name = coop::known_read_target(event.target)) file << '"' << name << '"';
            else file << "null";
            file << ",\"offset\":" << event.offset << ",\"requested_size\":" << event.requested_size;
            if (event.phase == coop::ReadPhase::completed || event.phase == coop::ReadPhase::unmatched_completion
                || event.phase == coop::ReadPhase::ambiguous_completion)
                file << ",\"completion_size\":" << event.completion_size << ",\"result\":" << (event.result ? "true" : "false");
            else file << ",\"handle_valid\":" << (event.result ? "true" : "false");
            file << '}';
        }
        const auto& digests = counts.digests;
        file << "],\"buffer_digests\":{\"enabled\":" << (counts.digest_enabled ? "true" : "false")
             << ",\"available\":" << (digests.available ? "true" : "false")
             << ",\"capacity\":" << coop::digest_record_capacity << ",\"skipped\":" << digests.skipped
             << ",\"overflows\":" << digests.overflows << ",\"bookkeeping_errors\":" << digests.bookkeeping_errors
             << ",\"records\":[";
        constexpr char hex[] = "0123456789abcdef";
        for (std::size_t index = 0; index != digests.count; ++index) {
            const auto& value = digests.records[index];
            const auto& completion = value.completion;
            if (index) file << ',';
            file << "{\"request_id\":" << completion.request_id << ",\"completion_event_sequence\":" << completion.event_sequence
                 << ",\"file\":\"" << coop::known_read_target(completion.target) << "\",\"offset\":" << completion.offset
                 << ",\"requested_size\":" << completion.requested_size << ",\"completion_size\":" << completion.completion_size
                 << ",\"in_progress\":" << (value.in_progress ? "true" : "false")
                 << ",\"ok\":" << (value.digest.ok ? "true" : "false")
                 << ",\"reason\":\"" << coop::digest_reason_name(value.digest.reason) << '"';
            if (value.digest.ok) {
                file << ",\"sha256\":\"";
                for (const auto byte : value.digest.bytes) file << hex[byte >> 4] << hex[byte & 15];
                file << '"';
            }
            file << '}';
        }
        file << "]}}";
        if (!file) return;
    }
    MoveFileExW(temp.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}

void publish_metadata(bool guard_active) {
    if(!observe_metadata) return;
    const auto state=coop::storage_metadata_observation();
    const bool active=guard_active&&metadata_observer.intact();
    const auto temp=directory/L"re2_coop_storage_metadata.json.tmp";
    const auto target=directory/L"re2_coop_storage_metadata.json";
    {
        std::ofstream file(temp,std::ios::binary|std::ios::trunc);
        file << "{\"schema\":1,\"source\":\"steam_storage_metadata\",\"interface\":\"014\",\"at\":" << std::time(nullptr)
             << ",\"game_pid\":" << GetCurrentProcessId() << ",\"run_id\":\"" << run_id
             << "\",\"app_id\":" << app_id << ",\"build_id\":" << build_id
             << ",\"active\":" << (active?"true":"false") << ",\"reason\":\""
             << (active?"ok":!guard_active?"writer_guard_unavailable":metadata_observer.table()?"metadata_integrity_failed":metadata_reason)
             << "\",\"available\":" << (state.available?"true":"false")
             << ",\"event_sequence\":" << state.event_sequence << ",\"discarded_events\":" << state.discarded_events
             << ",\"observation_errors\":" << state.observation_errors << ",\"bookkeeping_errors\":" << state.bookkeeping_errors
             << ",\"calls\":{";
        for(std::size_t n=0;n<coop::metadata_methods;++n) {
            if(n) file << ',';
            file << '"' << coop::storage_metadata_methods()[n].name << "\":" << state.calls[n];
        }
        file << "},\"targets\":[";
        bool first=true;
        for(std::size_t t=0;t<coop::metadata_target_count;++t) {
            bool seen=false;for(const auto value:state.targets[t]) if(value) seen=true;
            if(!seen) continue;
            if(!first) file << ',';first=false;
            const auto* const name=t==coop::global_metadata_target?"global":coop::known_read_target(t);
            file << "{\"file\":\"" << (name?name:"unknown") << "\",\"calls\":{";
            for(std::size_t m=0;m<coop::metadata_methods;++m) {
                if(m) file << ',';
                file << '"' << coop::storage_metadata_methods()[m].name << "\":" << state.targets[t][m];
            }
            file << "}}";
        }
        file << "],\"events\":[";
        for(std::size_t n=0;n<state.event_count;++n) {
            if(n) file << ',';
            const auto& e=state.events[n];
            const auto* const name=e.target==coop::global_metadata_target?"global":coop::known_read_target(e.target);
            file << "{\"sequence\":" << e.sequence << ",\"method\":\"" << coop::storage_metadata_methods()[e.method].name
                 << "\",\"file\":\"" << (name?name:"unknown") << "\",\"index\":" << e.index
                 << ",\"name_returned\":" << (e.name_returned?"true":"false")
                 << ",\"has_value\":" << (e.has_value?"true":"false") << ",\"value\":" << e.value
                 << ",\"has_unsigned_value\":" << (e.has_unsigned_value?"true":"false") << ",\"unsigned_value\":" << e.unsigned_value
                 << ",\"has_secondary\":" << (e.has_secondary?"true":"false") << ",\"secondary\":" << e.secondary << '}';
        }
        file << "]}";if(!file) return;
    }
    MoveFileExW(temp.c_str(),target.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
}

void publish(bool active, const char* reason) {
    if (std::string(reason) != last_reason) {
        ref->log_info("RE2_COOP_NATIVE_SAVE_GUARD active=%d reason=%s", active ? 1 : 0, reason);
        last_reason = reason;
    }
    try {
        std::filesystem::create_directories(directory);
        const auto temp = directory / L"re2_coop_native_save_guard.json.tmp";
        const auto target = directory / L"re2_coop_native_save_guard.json";
        const auto counts = coop::storage_counts();
        std::uint64_t total{};
        for (const auto count : counts) total += count;
        {
            std::ofstream file(temp, std::ios::binary | std::ios::trunc);
            file << "{\"schema\":1,\"source\":\"steam_storage_guard\",\"at\":" << std::time(nullptr)
                 << ",\"game_pid\":" << GetCurrentProcessId() << ",\"run_id\":\"" << run_id
                 << "\",\"app_id\":" << app_id
                 << ",\"build_id\":" << build_id << ",\"interface\":\"014\",\"active\":"
                 << (active ? "true" : "false") << ",\"reason\":\"" << reason
                 << "\",\"guarded_methods\":" << coop::guarded_methods
                 << ",\"blocked_calls\":" << total << ",\"counters\":{";
            for (std::size_t i = 0; i != counts.size(); ++i) {
                if (i) file << ',';
                file << '"' << coop::storage_methods()[i].name << "\":" << counts[i];
            }
            file << "}}";
            if (!file) return;
        }
        MoveFileExW(temp.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
        publish_reads(active, reason);
        publish_metadata(active);
    } catch (...) {
        ref->log_error("RE2_COOP_NATIVE_SAVE_GUARD status export failed");
    }
}

bool trusted_table(void* object,std::size_t first=0,std::size_t end=coop::storage_prefix_size) {
    const auto client = GetModuleHandleW(L"steamclient64.dll");
    const auto api = GetModuleHandleW(L"steam_api64.dll");
    if (!object || !client || !api) return false;
    void** table{};SIZE_T bytes{};
    if(!ReadProcessMemory(GetCurrentProcess(),object,&table,sizeof(table),&bytes)||bytes!=sizeof(table)) return false;
    for (std::size_t index = first; index != end; ++index) {
        void* method{};
        if(!ReadProcessMemory(GetCurrentProcess(),table+index,&method,sizeof(method),&bytes)||bytes!=sizeof(method)) return false;
        HMODULE owner{};
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                reinterpret_cast<LPCWSTR>(method), &owner) || (owner != client && owner != api)) return false;
    }
    return true;
}

void tick() {
    const auto now = Clock::now();
    if (now < next_report) return;
    next_report = now + std::chrono::seconds(1);
    const auto module = GetModuleHandleW(L"steam_api64.dll");
    if (!module) { publish(false, "waiting_for_steam"); return; }
    using GetHandle = int(*)();
    using GetInterface = void*(*)();
    using FindInterface = void*(*)(int, const char*);
    using GetApp = std::uint32_t(*)(void*);
    using GetBuild = std::int32_t(*)(void*);
    const auto user = resolve<GetHandle>(module, "SteamAPI_GetHSteamUser");
    const auto storage = resolve<GetInterface>(module, "SteamAPI_SteamRemoteStorage_v014");
    const auto find = resolve<FindInterface>(module, "SteamInternal_FindOrCreateUserInterface");
    const auto utils = resolve<GetInterface>(module, "SteamAPI_SteamUtils_v010");
    const auto apps = resolve<GetInterface>(module, "SteamAPI_SteamApps_v008");
    const auto app = resolve<GetApp>(module, "SteamAPI_ISteamUtils_GetAppID");
    const auto build = resolve<GetBuild>(module, "SteamAPI_ISteamApps_GetAppBuildId");
    if (!user || !storage || !find || !utils || !apps || !app || !build || !user()) {
        publish(false, "waiting_for_steam"); return;
    }
    auto* const utilities = utils();
    auto* const application = apps();
    if (!utilities || !application) { publish(false, "waiting_for_steam"); return; }
    if (app(utilities) != app_id || build(application) != build_id) {
        publish(false, "unsupported_game_build"); return;
    }
    auto* const current = storage();
    auto* const direct = find(user(), "STEAMREMOTESTORAGE_INTERFACE_VERSION014");
    if (!current || current != direct) { publish(false, "storage_context_mismatch"); return; }
    if (!guard.table()) {
        if (!trusted_table(current)) { publish(false, "untrusted_storage_table"); return; }
        if (!guard.attach(current)) { publish(false, guard.error()); return; }
    }
    if (*reinterpret_cast<void***>(current) != guard.table() || !guard.intact()) {
        publish(false, "storage_table_changed"); return;
    }
    if (observe_reads && !read_observer.table()) read_observer.attach(current);
    if(observe_metadata&&!metadata_observer.table()) {
        if(!trusted_table(current,13,coop::metadata_prefix_size)) metadata_reason="untrusted_metadata_table";
        else {metadata_observer.attach(current);metadata_reason=metadata_observer.error();}
    }
    publish(!run_id.empty(), run_id.empty() ? "protected_launch_required" : "ok");
}
} // namespace

extern "C" __declspec(dllexport) void reframework_plugin_required_version(REFrameworkPluginVersion* version) {
    *version = {REFRAMEWORK_PLUGIN_VERSION_MAJOR, REFRAMEWORK_PLUGIN_VERSION_MINOR,
                REFRAMEWORK_PLUGIN_VERSION_PATCH, nullptr};
}

extern "C" __declspec(dllexport) bool reframework_plugin_initialize(const REFrameworkPluginInitializeParam* param) {
    ref = param->functions;
    wchar_t path[32768]{};
    const auto length = GetModuleFileNameW(nullptr, path, static_cast<DWORD>(std::size(path)));
    if (!length || length >= std::size(path)) return false;
    const std::filesystem::path executable(path);
    if (_wcsicmp(executable.filename().c_str(), L"re2.exe") != 0) return false;
    directory = executable.parent_path() / L"reframework" / L"data";
    char read_mode[2]{};
    observe_reads = GetEnvironmentVariableA("RE2_COOP_STORAGE_READ_TRACE", read_mode, sizeof(read_mode)) == 1
        && read_mode[0] == '1';
    char metadata_mode[2]{};
    observe_metadata=GetEnvironmentVariableA("RE2_COOP_STORAGE_METADATA",metadata_mode,sizeof(metadata_mode))==1
        && metadata_mode[0]=='1';
    char digest_mode[2]{};
    coop::configure_storage_buffer_digests(observe_reads
        && GetEnvironmentVariableA("RE2_COOP_STORAGE_READ_DIGEST",digest_mode,sizeof(digest_mode)) == 1 && digest_mode[0] == '1');
    char token[33]{};
    if (GetEnvironmentVariableA("RE2_COOP_SAVE_GUARD_RUN_ID", token, sizeof(token)) == 32) {
        bool valid = true;
        for (std::size_t index = 0; index != 32; ++index) {
            if (!std::isxdigit(static_cast<unsigned char>(token[index]))) valid = false;
        }
        if (valid) run_id = token;
    }
    tick();
    return ref->on_pre_application_entry("UpdateBehavior", tick);
}
