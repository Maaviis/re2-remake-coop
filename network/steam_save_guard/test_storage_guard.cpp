#include "storage_guard.h"
#include "checkpoint_import.h"
#include <windows.h>
#include <winioctl.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <thread>
#include <vector>

namespace {
std::atomic<int> original_writes{};
std::uint64_t async_result = 0x1234567812345678ull;
std::string last_key;
std::filesystem::path remote;
bool healthy = true;
struct Submission { std::string key, bytes; };
std::vector<Submission> submitted;
std::uint64_t original_async(void*, const char* key, const void* data, std::uint32_t size) {
    last_key = key;
    if (async_result) submitted.push_back({key, std::string(static_cast<const char*>(data), size)});
    return async_result;
}
bool finish_writes() {
    for (const auto& call : submitted) {
        const auto target = remote / call.key;
        const auto temporary = std::filesystem::path(target).concat(L".stmp");
        {
            std::ofstream file(temporary, std::ios::binary | std::ios::trunc);
            file << call.bytes;
            if (!file) return false;
        }
        if (!MoveFileExW(temporary.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
            return false;
    }
    submitted.clear();
    return true;
}
bool junction(const std::filesystem::path& path, const std::filesystem::path& target) {
    if (!std::filesystem::create_directory(path)) return false;
    const auto raw = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (raw == INVALID_HANDLE_VALUE) return false;
    coop::FileHandle handle(raw);
    const auto name = L"\\??\\" + std::filesystem::path(target).make_preferred().native();
    struct MountPoint {
        DWORD tag;
        WORD length, reserved, offset, size, print_offset, print_size;
        wchar_t names[8192];
    } content{};
    if (name.size() + 2 >= std::size(content.names)) return false;
    std::copy(name.begin(), name.end(), content.names);
    content.tag = IO_REPARSE_TAG_MOUNT_POINT;
    content.size = static_cast<WORD>(name.size() * sizeof(wchar_t));
    content.print_offset = content.size + sizeof(wchar_t);
    content.length = 8 + content.print_offset + sizeof(wchar_t);
    DWORD ignored{};
    return DeviceIoControl(raw, FSCTL_SET_REPARSE_POINT, &content, content.length + 8, nullptr, 0, &ignored, nullptr) != FALSE;
}
bool original_write(void*, const char*, const void*, std::int32_t) { ++original_writes; return true; }
int original_read(void*, const char*, void*, std::int32_t) { return 73; }
void check(bool value, const char* reason) { if (!value) { std::fprintf(stderr, "%s\n", reason); std::exit(1); } }
template<typename Function>
Function function(void* address) {
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(address);
}
} // namespace

int main() {
    using Write = bool(*)(void*, const char*, const void*, std::int32_t);
    using Read = int(*)(void*, const char*, void*, std::int32_t);
    using Async = std::uint64_t(*)(void*, const char*, const void*, std::uint32_t);
    using File = bool(*)(void*, const char*);
    using Share = std::uint64_t(*)(void*, const char*);
    using Platforms = bool(*)(void*, const char*, std::uint32_t);
    using Chunk = bool(*)(void*, std::uint64_t, const void*, std::int32_t);
    using Stream = bool(*)(void*, std::uint64_t);
    std::array<void*, coop::storage_prefix_size> table{};
    table.fill(reinterpret_cast<void*>(&original_write));
    table[1] = reinterpret_cast<void*>(&original_read);
    table[2] = reinterpret_cast<void*>(&original_async);
    const auto original = table;
    struct Interface { void** table; } object{table.data()};
    coop::StorageGuard guard;
    check(!guard.attach(nullptr), "invalid interface accepted");
    check(guard.attach(&object) && guard.intact(), "synthetic interface not guarded");
    check(function<Read>(table[1])(&object, "fixture", nullptr, 0) == 73, "read method changed");
    check(!function<Write>(table[0])(&object, "fixture", nullptr, 0), "FileWrite allowed");
    check(function<Async>(table[2])(&object, "fixture", nullptr, 0) == 0, "async write allowed");
    check(!function<File>(table[5])(&object, "fixture"), "forget allowed");
    check(!function<File>(table[6])(&object, "fixture"), "delete allowed");
    check(function<Share>(table[7])(&object, "fixture") == 0, "share allowed");
    check(!function<Platforms>(table[8])(&object, "fixture", 0), "sync platforms changed");
    check(function<Share>(table[9])(&object, "fixture") == UINT64_MAX, "stream opened");
    check(!function<Chunk>(table[10])(&object, 1, nullptr, 0), "stream chunk allowed");
    check(!function<Stream>(table[11])(&object, 1), "stream committed");
    check(!function<Stream>(table[12])(&object, 1), "stream cancel reached original");
    check(original_writes == 0, "original writer ran");
    const auto counts = coop::storage_counts();
    for (const auto count : counts) check(count == 1, "write counter mismatch");
    std::vector<std::thread> threads;
    for (int index = 0; index != 4; ++index) threads.emplace_back([&] {
        for (int n = 0; n != 1000; ++n) check(!function<Write>(table[0])(&object, "fixture", nullptr, 0), "concurrent write allowed");
    });
    for (auto& thread : threads) thread.join();
    check(coop::storage_counts()[0] == 4001 && original_writes == 0, "concurrent call accounting changed");
    // Flat Steam exports can share one generic thunk across unrelated interfaces.
    // Guarding one vtable must leave another table using the same address alone.
    auto separate_table = original;
    Interface separate{separate_table.data()};
    check(function<Write>(separate_table[0])(&separate, "fixture", nullptr, 0), "unrelated interface was changed");
    check(original_writes == 1, "unrelated original call missing");
    namespace fs = std::filesystem;
    // Hosted Windows runners may spell TEMP with a DOS short name. The
    // synthetic Steam registry location uses the physical long path.
    const auto root = fs::canonical(fs::temp_directory_path()) /
        (L"re2-campaign-guard-" + std::to_wstring(GetCurrentProcessId()));
    check(fs::create_directory(root), "fixture directory already exists");
    const auto userdata = root / L"userdata";
    remote = userdata / L"1234/883710/remote";
    const auto save = remote / L"win64_save";
    fs::create_directories(save);
    std::ofstream(save / "data000.bin") << "solo";
    const std::string token(32, 'a'), other(32, 'b');
    const auto prefix = "coop-save-" + token + "/";
    const auto campaign = remote / ("coop-save-" + token);
    const auto write = [&](const std::string& name) {
        return function<Async>(table[2])(&object, name.c_str(), "coop", 4);
    };
    check(guard.set_campaign(save, token.c_str(), userdata) && guard.campaign_namespace() == token, "campaign not active");
    for (const std::string& name : {"win64_save/data000.bin", "../win64_save/data000.bin", "/data000.bin",
            "data000.bin", "coop-save-other/data000.bin"}) check(!write(name), "foreign name allowed");
    for (const auto& leaf : {"../win64_save/data000.bin", "nested/data000.bin", "data000.bin:ads",
            "data000.bin.", "data000.bin ", "data000.bin/foo", "NUL", "DATA00~1.BIN", "data000.bin/..",
            "data000.bin.stmp"})
        check(!write(prefix + leaf), "unsafe leaf allowed");
    check(!write("coop-save-" + other + "/data000.bin"), "other campaign allowed");
    check(!function<Write>(table[0])(&object, (prefix + "data000.bin").c_str(), "coop", 4),
        "synchronous writer gained campaign rights");
    const auto allowed_key = prefix + "data000.bin";
    check(!function<File>(table[5])(&object, allowed_key.c_str()) &&
        !function<File>(table[6])(&object, allowed_key.c_str()) &&
        !function<Share>(table[7])(&object, allowed_key.c_str()) &&
        !function<Platforms>(table[8])(&object, allowed_key.c_str(), 0) &&
        function<Share>(table[9])(&object, allowed_key.c_str()) == UINT64_MAX &&
        !function<Chunk>(table[10])(&object, 73, "coop", 4) && !function<Stream>(table[11])(&object, 73) &&
        !function<Stream>(table[12])(&object, 73), "grant authorized another Steam operation or an old stream");
    check(!function<Async>(table[2])(&separate, (prefix + "data000.bin").c_str(), "coop", 4),
        "foreign interface gained campaign rights");
    check(last_key.empty(), "a rejected key reached Steam");
    check(CreateHardLinkW((campaign / "data002.bin").c_str(), (save / "data000.bin").c_str(), nullptr),
        "cannot create hardlink fixture");
    check(!write(prefix + "data002.bin") && last_key.empty(), "hardlinked target reached Steam");
    fs::remove(campaign / "data002.bin");
    const auto companion = campaign / "data000.bin.stmp";
    check(CreateHardLinkW(companion.c_str(), (save / "data000.bin").c_str(), nullptr),
        "cannot create linked staging fixture");
    check(!write(allowed_key) && last_key.empty(), "linked staging file reached Steam");
    fs::remove(companion);
    check(junction(companion, save), "cannot create staging reparse fixture");
    check(!write(allowed_key) && last_key.empty(), "staging reparse point reached Steam");
    fs::remove(companion);
    std::ofstream(companion) << "leftover";
    check(!write(allowed_key) && last_key.empty(), "pre-existing staging file reused");
    fs::remove(companion);
    check(function<Async>(table[2])(&object, allowed_key.c_str(), "previous", 8) == async_result && finish_writes(),
        "initial checkpoint could not commit");
    guard.retire_completed([](std::uint64_t call) { return call == async_result; });
    last_key.clear();
    const auto old_writer = CreateFileW((campaign / "data000.bin").c_str(), GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, 0, nullptr);
    check(old_writer != INVALID_HANDLE_VALUE && !write(allowed_key) && last_key.empty(),
        "existing writable checkpoint handle was admitted");
    CloseHandle(old_writer);
    check(write("./" + prefix + "data000.bin") == async_result && last_key == prefix + "data000.bin",
        "async result or canonical key lost");
    check(!write(allowed_key) && submitted.size() == 1 && fs::file_size(companion) == 0 &&
        fs::file_size(campaign / "data000.bin") == 8, "in-flight key was reused or target was truncated early");
    check(finish_writes(), "Steam-style temporary write and replacement of existing checkpoint failed");
    guard.retire_completed([](std::uint64_t call) { return call == async_result; });
    check(guard.campaign_namespace() == token && !fs::exists(companion), "verified rename revoked scope");
    check(write(allowed_key) == async_result, "identical checkpoint could not submit");
    submitted.clear(); // Steam may complete an identical write without replacing the file.
    guard.retire_completed([](std::uint64_t call) { return call == async_result; });
    check(guard.campaign_namespace() == token && !fs::exists(companion),
        "successful identical write revoked scope or left an empty reservation");
    check(write(prefix + "data00-1.bin") == async_result && write(prefix + "data021Slot.bin") == async_result,
        "system or slot checkpoint was rejected");
    check(fs::file_size(campaign / "data000.bin") == 4 && fs::file_size(save / "data000.bin") == 4,
        "wrong target size");
    std::string original_bytes, campaign_bytes;
    std::ifstream(save / "data000.bin") >> original_bytes;
    std::ifstream(campaign / "data000.bin") >> campaign_bytes;
    check(original_bytes == "solo" && campaign_bytes == "coop", "wrong target contents");
    check(guard.set_campaign({}, nullptr) && !write(prefix + "data000.bin"), "revoked campaign still granted");
    const auto moved = remote / L"moved-campaign";
    check(!MoveFileExW(campaign.c_str(), moved.c_str(), 0), "in-flight directory lost its pin on revoke");
    guard.retire_completed([](std::uint64_t) { return false; });
    check(!MoveFileExW(campaign.c_str(), moved.c_str(), 0), "incomplete call lost directory pin");
    check(finish_writes(), "admitted writes could not commit after revocation");
    guard.retire_completed([](std::uint64_t call) { return call == async_result; });
    check(MoveFileExW(campaign.c_str(), moved.c_str(), 0) && MoveFileExW(moved.c_str(), campaign.c_str(), 0),
        "completed call retained campaign directory");
    const auto directory_writer = CreateFileW(campaign.c_str(), FILE_ADD_FILE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr);
    check(directory_writer != INVALID_HANDLE_VALUE && !guard.set_campaign(save, token.c_str(), userdata),
        "directory writer predating campaign activation was admitted");
    CloseHandle(directory_writer);
    check(guard.set_campaign(save, other.c_str(), userdata) && !write(prefix + "data000.bin"), "stale key forwarded");
    const auto second = "coop-save-" + other + "/data000.bin";
    async_result = 0;
    check(!write(second) && last_key == second, "Steam's own failure was masked");
    check(!fs::exists(fs::path(remote / second).concat(L".stmp")), "immediate failure retained empty reservation");
    async_result = 123;
    check(write(second) == 123, "retry did not submit");
    std::ofstream(remote / second) << "coop";
    submitted.clear();
    guard.retire_completed([](std::uint64_t call) { return call == 123; });
    check(guard.campaign_namespace().empty() && !write(second), "wrong completed NTFS identity kept grant");
    check(guard.set_campaign(save, token.c_str(), userdata), "cannot reopen verified checkpoint");
    const std::string large(16387, 'x');
    check(function<Async>(table[2])(&object, allowed_key.c_str(), large.data(), static_cast<DWORD>(large.size()))
        == async_result && finish_writes(), "large checkpoint could not commit");
    guard.retire_completed([](std::uint64_t call) { return call == async_result; });
    check(function<Async>(table[2])(&object, allowed_key.c_str(), large.data(), static_cast<DWORD>(large.size()))
        == async_result, "large identical checkpoint could not submit");
    submitted.clear();
    guard.retire_completed([](std::uint64_t call) { return call == async_result; });
    check(guard.campaign_namespace() == token && !fs::exists(companion), "multi-block fingerprint failed");
    check(function<Async>(table[2])(&object, allowed_key.c_str(), large.data(), static_cast<DWORD>(large.size()))
        == async_result, "cannot submit content-mutation regression");
    submitted.clear();
    { std::fstream changed(campaign / "data000.bin", std::ios::binary | std::ios::in | std::ios::out);
      changed.seekp(8193); changed.put('z'); }
    guard.retire_completed([](std::uint64_t call) { return call == async_result; });
    check(guard.campaign_namespace().empty(), "same-identity content change kept grant");
    check(guard.set_campaign(save, token.c_str(), userdata), "cannot reopen after mutation test");
    check(write(allowed_key) == async_result && write(prefix + "data002.bin") == async_result && finish_writes(),
        "replacement-identity fixtures failed");
    guard.retire_completed([](std::uint64_t call) { return call == async_result; });
    check(write(allowed_key) == async_result, "cannot submit identity-mutation regression");
    submitted.clear();
    check(MoveFileExW((campaign / "data002.bin").c_str(), (campaign / "data000.bin").c_str(),
        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH), "cannot replace with identical private file");
    guard.retire_completed([](std::uint64_t call) { return call == async_result; });
    check(guard.campaign_namespace().empty(), "identical bytes with foreign NTFS identity kept grant");
    check(!guard.set_campaign(save, "AA") && guard.campaign_namespace().empty() && !write(second),
        "failed grant retained previous authority");
    // Native preparation uses the original guarded writer and immutable archive input.
    const std::string archive_namespace(32, 'd'), generation(64, 'e');
    const auto archived = save.parent_path().parent_path() / "re2-coop-checkpoints" / archive_namespace / generation;
    fs::create_directories(archived);
    const std::array<std::string, 3> archive_bytes{{"native autosave bytes", "native slot index bytes", "native system bytes"}};
    for (std::size_t file = 0; file < coop::checkpoint_files.size(); ++file)
        std::ofstream(archived / coop::checkpoint_files[file], std::ios::binary) << archive_bytes[file];
    const auto descriptor = token + ' ' + std::string(32,'a') + ' ' + archive_namespace + ' ' + generation +
        " 17f1dba9aa3bf90e70152f058a64d60f60b2d364dcd486c0a699e7a3dd5336e7 5bc0c45618c6c4dea3b13c7eff8a82a83df7f4e025fa319af73db0fec1246ad9 ec549d5b750290a10b85b9227f4d65fdbbe3087a85870a30917b704e3e01d69d";
    const auto selection = coop::parse_checkpoint_import(descriptor);
    check(selection.has_value() && selection->archive_namespace != selection->workspace, "archive/workspace identity lost");
    for (const auto& bad : {descriptor + " extra", descriptor + "\n", descriptor.substr(0, descriptor.size()-1),
            std::string(513,'a'), std::string("../") + descriptor})
        check(!coop::parse_checkpoint_import(bad), "malformed import descriptor accepted");
    check(guard.set_campaign(save, token.c_str(), userdata), "cannot prepare import scope");
    coop::CheckpointImport importer;
    check(!importer.start(*selection, guard, false, 1000) && submitted.empty(), "import started outside title");
    check(importer.start(*selection, guard, true, 1000), "native import did not start");
    const coop::CheckpointImportBackend backend{
        [](std::uint64_t call) { return call == async_result; }, [](std::uint64_t) { return 1; }};
    importer.tick(guard, backend, true, 1001);
    check(importer.active() && submitted.size()==1, "import did not submit exactly one file");
    auto other_request = *selection; other_request.request_id = std::string(32,'b');
    check(!importer.start(other_request, guard, true, 1002) && importer.start(*selection, guard, true, 1002),
        "active import replaced or replayed with additional writes");
    for (std::uint64_t step = 0; step < 3; ++step) {
        check(finish_writes(), "imported bytes could not commit");
        importer.tick(guard, backend, true, 1003+step);
    }
    check(std::string(importer.phase())=="ready" && !importer.active() && importer.file_index()==3,
        "native import did not verify all three files");
    for (std::size_t file = 0; file < coop::checkpoint_files.size(); ++file) {
        std::ifstream input(campaign / coop::checkpoint_files[file], std::ios::binary);
        const std::string bytes((std::istreambuf_iterator<char>(input)),std::istreambuf_iterator<char>());
        check(bytes == archive_bytes[file], "working copy differs from selected archive");
    }
    check(importer.start(other_request, guard, true, 2000), "cannot prepare failed result fixture");
    importer.tick(guard, backend, true, 2001);
    check(finish_writes(), "failed-result fixture could not finish its original call");
    importer.tick(guard, {backend.completed, [](std::uint64_t) { return 2; }}, true, 2002);
    check(std::string(importer.phase())=="failed" && importer.file_index()==0 && submitted.empty(),
        "failed Steam result published readiness or started another file");
    other_request.request_id = std::string(32,'c');
    check(importer.start(other_request, guard, true, 3000), "cannot prepare rebound fixture");
    importer.tick(guard, backend, true, 3001);
    check(finish_writes() && guard.set_campaign(save, token.c_str(), userdata), "cannot rebind the same namespace");
    importer.tick(guard, backend, true, 3002);
    check(std::string(importer.phase())=="failed" && std::string(importer.error())=="checkpoint_campaign_changed",
        "import followed a new grant with the same namespace");
    other_request.request_id = std::string(32,'f');
    check(importer.start(other_request, guard, true, 4000), "cannot prepare lost-title fixture");
    importer.tick(guard, backend, true, 4001);
    const coop::CheckpointImportBackend pending{[](std::uint64_t) { return false; }, backend.result};
    importer.tick(guard, pending, false, 4002);
    check(std::string(importer.phase())=="failed" && importer.active(), "pending buffer not retained after title loss");
    check(finish_writes(), "accepted import could not finish after title loss");
    importer.tick(guard, backend, false, 4003);
    check(!importer.active() && submitted.empty(), "cancelled import started another write");
    other_request.request_id = std::string(32,'9');
    check(importer.start(other_request, guard, true, 5000), "cannot prepare timeout fixture");
    importer.tick(guard, backend, true, 5001);
    importer.tick(guard, pending, true, 50000);
    check(std::string(importer.error())=="checkpoint_import_timeout" && importer.active(), "import deadline not enforced");
    check(finish_writes(), "timed-out write fixture failed");
    importer.tick(guard, backend, true, 50001);
    check(!importer.active() && std::string(importer.phase())=="failed", "late callback resurrected expired import");
    other_request.request_id = std::string(32,'7');
    check(importer.start(other_request, guard, true, 50500), "cannot prepare cancelled fixture");
    importer.tick(guard, backend, true, 50501);
    check(!importer.cancel(std::string(32,'6')) && importer.cancel(other_request.request_id) && importer.active(),
        "cancellation lost its request binding or released pending memory");
    check(finish_writes(), "cancelled write fixture failed");
    importer.tick(guard, backend, true, 50502);
    check(!importer.active() && std::string(importer.error())=="checkpoint_import_cancelled" && submitted.empty(),
        "cancelled import was revived by completion");
    std::ofstream(archived / "data000.bin", std::ios::binary | std::ios::trunc) << "corrupt archive";
    other_request.request_id = std::string(32,'8');
    check(importer.start(other_request, guard, true, 51000), "cannot prepare corrupt archive fixture");
    importer.tick(guard, backend, true, 51001);
    check(std::string(importer.error())=="checkpoint_archive_invalid" && submitted.empty(), "corrupt source reached Steam");
    std::ofstream(archived / "data000.bin", std::ios::binary | std::ios::trunc) << archive_bytes[0];
    for (std::size_t file = 0; file < coop::checkpoint_files.size(); ++file) {
        std::ifstream input(archived / coop::checkpoint_files[file], std::ios::binary);
        const std::string bytes((std::istreambuf_iterator<char>(input)),std::istreambuf_iterator<char>());
        check(bytes == archive_bytes[file], "archived bytes changed during preparation");
    }
    last_key.clear();
    check(guard.set_campaign(save, token.c_str(), userdata, [] { return healthy; }), "healthy grant failed");
    healthy = false;
    check(!write(allowed_key) && guard.campaign_namespace().empty() && last_key.empty(),
        "loss of protection did not revoke before forwarding");
    const auto linked_campaign = remote / ("coop-save-" + std::string(32, 'c'));
    check(junction(linked_campaign, save), "cannot create junction fixture");
    check(!guard.set_campaign(save, std::string(32, 'c').c_str(), userdata), "reparse campaign directory accepted");
    fs::remove(linked_campaign);
    fs::create_directory(linked_campaign);
    check(!guard.set_campaign(save, std::string(32, 'c').c_str(), userdata), "public inherited namespace accepted");
    fs::remove(linked_campaign);
    const auto physical = root / L"InstallationUserData";
    fs::rename(userdata, physical);
    check(junction(userdata, physical), "registered junction fixture failed");
    check(guard.set_campaign(save, token.c_str(), userdata), "registered logical Steam userdata was rejected");
    const auto canonical_save = physical / L"1234/883710/remote/win64_save";
    check(guard.set_campaign(canonical_save, token.c_str(), userdata), "registered physical Steam userdata was rejected");
    const auto other_root = root / "fake" / "userdata";
    fs::create_directories(other_root);
    check(!guard.set_campaign(canonical_save, other.c_str(), other_root), "unregistered userdata accepted");
    fs::remove(userdata);
    fs::remove_all(root);
    table[0] = original[0];
    check(!guard.intact(), "changed vtable remained healthy");
    table[0] = coop::storage_methods()[0].replacement;
    guard.detach();
    check(table == original, "original table not restored");
    check(function<Write>(table[0])(&object, "fixture", nullptr, 0) && original_writes == 2, "detach damaged original writer");
    auto** readonly = static_cast<void**>(VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    check(readonly != nullptr, "fixture allocation failed");
    for (std::size_t i = 0; i != original.size(); ++i) readonly[i] = original[i];
    DWORD previous{};
    check(VirtualProtect(readonly, 4096, PAGE_READONLY, &previous) != 0, "read-only fixture setup failed");
    Interface readonly_object{readonly};
    coop::StorageGuard readonly_guard;
    check(readonly_guard.attach(&readonly_object) && readonly_guard.intact(), "read-only vtable not guarded");
    MEMORY_BASIC_INFORMATION protection{};
    VirtualQuery(readonly, &protection, sizeof(protection));
    check(protection.Protect == PAGE_READONLY, "vtable left writable");
    readonly_guard.detach();
    for (std::size_t i = 0; i != original.size(); ++i) check(readonly[i] == original[i], "read-only table not restored");
    VirtualQuery(readonly, &protection, sizeof(protection));
    check(protection.Protect == PAGE_READONLY, "detach left table writable");
    VirtualFree(readonly, 0, MEM_RELEASE);
    std::puts("Verified delayed Steam .stmp writes, atomic replacement, NTFS identity, revocation and legacy write denial");
}
