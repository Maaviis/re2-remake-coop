#include "storage_guard.h"
#include <windows.h>
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>

namespace {
std::atomic<int> original_writes{};
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
    std::puts("Synthetic Steam v014 writes blocked; reads, nesting-independent counters and restoration verified");
}
