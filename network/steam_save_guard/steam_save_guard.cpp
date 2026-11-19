#include <windows.h>
#include <reframework/API.h>
#include "storage_guard.h"
#include "storage_reads.h"
#include <chrono>
#include <cctype>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <string>
#include <charconv>
#include <sstream>

namespace {
const REFrameworkPluginFunctions* ref{};
coop::StorageGuard guard;
coop::StorageReadObserver read_observer;
bool observe_reads{};
bool private_source_requested{};
std::filesystem::path directory;
std::string run_id;
using Clock = std::chrono::steady_clock;
Clock::time_point next_report{};
constexpr std::uint32_t app_id = 883710;
constexpr std::int32_t build_id = 11636119;
const char* last_reason = "";

template<typename Integer> bool decimal(const std::string& text,Integer& value) {
    const auto result=std::from_chars(text.data(),text.data()+text.size(),value);
    return !text.empty() && result.ec==std::errc{} && result.ptr==text.data()+text.size();
}
void renew_private_source(bool healthy) {
    if(!private_source_requested) return;
    const auto now=static_cast<std::uint64_t>(std::time(nullptr));
    auto refuse=[&]{coop::renew_storage_private_source("","",0,0,now,false);};
    try {
        std::ifstream input(directory/L"re2_coop_private_source_lease.txt",std::ios::binary);
        std::array<char,512> buffer{};
        input.read(buffer.data(),buffer.size());
        const auto count=input.gcount();
        if(count<=0 || count==static_cast<std::streamsize>(buffer.size())) { refuse();return; }
        std::istringstream text(std::string(buffer.data(),static_cast<std::size_t>(count)));
        std::array<std::string,7> fields;
        for(auto& field:fields) if(!std::getline(text,field)) { refuse();return; }
        std::string extra;
        std::uint32_t pid{}; std::uint64_t issued{};
        if(std::getline(text,extra) || fields[0]!="RE2_PRIVATE_SOURCE_LEASE_V1" || fields[5]!="639300365010000000"
            || fields[6]!="1:4:1" || !decimal(fields[3],pid) || !decimal(fields[4],issued)) { refuse();return; }
        coop::renew_storage_private_source(fields[1],fields[2],pid,issued,now,healthy);
    } catch(...) { refuse(); }
}

void configure_private_source() {
    wchar_t path[32768]{}; char hash[65]{},request[33]{};
    const auto length=GetEnvironmentVariableW(L"RE2_COOP_PRIVATE_READ_FILE",path,static_cast<DWORD>(std::size(path)));
    if(!observe_reads || run_id.empty() || !length || length>=std::size(path)
        || GetEnvironmentVariableA("RE2_COOP_PRIVATE_READ_SHA256",hash,sizeof(hash))!=64
        || GetEnvironmentVariableA("RE2_COOP_PRIVATE_READ_REQUEST",request,sizeof(request))!=32) return;
    std::array<unsigned char,32> expected{};
    auto digit=[](char value)->int { return value>='0'&&value<='9'?value-'0':value>='a'&&value<='f'?value-'a'+10:-1; };
    for(std::size_t n=0;n<expected.size();++n) {
        const auto a=digit(hash[n*2]),b=digit(hash[n*2+1]);
        if(a<0||b<0) return;
        expected[n]=static_cast<unsigned char>(a*16+b);
    }
    private_source_requested=true;
    coop::configure_storage_private_source(std::filesystem::path(path),expected,run_id,request,GetCurrentProcessId());
}

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
        file << "{\"schema\":4,\"source\":\"steam_storage_reads\",\"scope\":\"remote_storage_014_reads\",\"at\":" << std::time(nullptr)
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
        const auto& source=counts.private_source;
        file << "]},\"private_source\":{\"enabled\":" << (source.enabled?"true":"false")
             << ",\"prepared\":" << (source.prepared?"true":"false") << ",\"armed\":" << (source.armed?"true":"false")
             << ",\"available\":" << (source.available?"true":"false") << ",\"source_bytes\":" << source.source_bytes
             << ",\"request_id\":\"" << source.request_id.data() << "\",\"ignored\":" << source.ignored
             << ",\"rejected\":" << source.rejected << ",\"bookkeeping_errors\":" << source.bookkeeping_errors
             << ",\"reason\":\"" << coop::private_read_reason_name(source.reason) << "\",\"records\":[";
        for(std::size_t n=0;n<source.count;++n) {
            const auto& value=source.records[n]; const auto& completion=value.completion;
            if(n) file << ',';
            file << "{\"read_request_id\":" << completion.request_id << ",\"completion_event_sequence\":" << completion.event_sequence
                 << ",\"file\":\"./win64_save/data004Slot.bin\",\"offset\":" << completion.offset
                 << ",\"requested_size\":" << completion.requested_size << ",\"completion_size\":" << completion.completion_size
                 << ",\"in_progress\":" << (value.in_progress?"true":"false")
                 << ",\"before_matches\":" << (value.before_matches?"true":"false")
                 << ",\"after_matches\":" << (value.after_matches?"true":"false") << ",\"supplied\":" << (value.supplied?"true":"false")
                 << ",\"copied_bytes\":" << value.copied_bytes << ",\"reason\":\"" << coop::private_read_reason_name(value.reason) << "\"}";
        }
        file << "]}}";
        if (!file) return;
    }
    MoveFileExW(temp.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}

void publish(bool active, const char* reason) {
    renew_private_source(active);
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
    } catch (...) {
        ref->log_error("RE2_COOP_NATIVE_SAVE_GUARD status export failed");
    }
}

bool trusted_table(void* object) {
    const auto client = GetModuleHandleW(L"steamclient64.dll");
    const auto api = GetModuleHandleW(L"steam_api64.dll");
    if (!object || !client || !api) return false;
    const auto table = *reinterpret_cast<void***>(object);
    for (std::size_t index = 0; index != coop::storage_prefix_size; ++index) {
        HMODULE owner{};
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                reinterpret_cast<LPCWSTR>(table[index]), &owner) || (owner != client && owner != api)) return false;
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
    configure_private_source();
    tick();
    return ref->on_pre_application_entry("UpdateBehavior", tick);
}
