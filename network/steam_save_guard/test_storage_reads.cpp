#include "storage_reads.h"
#include <windows.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <vector>

namespace {
struct Interface { void** table; };
void* expected_self{};
std::atomic<std::uint64_t> actual_reads{};
std::atomic<std::uint64_t> actual_writes{};
constexpr std::uint64_t async_handle = 0xfedcba9876543210ULL;
void check(bool value, const char* reason) { if (!value) { std::fprintf(stderr, "%s\n", reason); std::exit(1); } }
bool write_file(void*, const char*, const void*, std::int32_t) { ++actual_writes; return true; }
std::int32_t read_file(void* self, const char* name, void* buffer, std::int32_t size) {
    check(self == expected_self, "read receiver changed");
    check(name && std::strcmp(name, "fixture") == 0, "read filename changed");
    ++actual_reads;
    if (size == -7) { check(buffer == nullptr, "negative request buffer changed"); return -9; }
    check(size == 4 && buffer != nullptr, "read buffer/size changed");
    std::memcpy(buffer, "ABC", 4);
    return 3;
}
std::uint64_t read_async(void* self, const char* name, std::uint32_t offset, std::uint32_t size) {
    check(self == expected_self && name && std::strcmp(name, "fixture") == 0, "async receiver/name changed");
    check(offset == 0xfedcba98U && size == 0xabcdef12U, "async uint32 arguments truncated");
    return async_handle;
}
bool complete_async(void* self, std::uint64_t handle, void* buffer, std::uint32_t size) {
    check(self == expected_self && handle == async_handle && size == 0xabcdef12U, "completion arguments changed");
    return buffer != nullptr;
}
template<typename Function>
Function function(void* address) {
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(address);
}
} // namespace

int main() {
    using Read = std::int32_t(*)(void*, const char*, void*, std::int32_t);
    using Write = bool(*)(void*, const char*, const void*, std::int32_t);
    using Async = std::uint64_t(*)(void*, const char*, std::uint32_t, std::uint32_t);
    using Complete = bool(*)(void*, std::uint64_t, void*, std::uint32_t);
    std::array<void*, coop::storage_prefix_size> original{};
    original.fill(reinterpret_cast<void*>(&write_file));
    original[1] = reinterpret_cast<void*>(&read_file);
    original[3] = reinterpret_cast<void*>(&read_async);
    original[4] = reinterpret_cast<void*>(&complete_async);
    auto** table = static_cast<void**>(VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    check(table != nullptr, "vtable allocation failed");
    for (std::size_t i = 0; i != original.size(); ++i) table[i] = original[i];
    DWORD previous{};
    check(VirtualProtect(table, 4096, PAGE_READONLY, &previous) != 0, "read-only setup failed");
    Interface object{table};
    expected_self = &object;
    coop::StorageGuard writers;
    coop::StorageReadObserver reads;
    check(!reads.attach(nullptr), "invalid read interface accepted");
    check(writers.attach(&object), "write barrier setup failed");
    check(table[1] == original[1] && table[3] == original[3] && table[4] == original[4], "default guard changed reads");
    check(reads.attach(&object) && reads.intact() && writers.intact(), "optional read observer not attached");
    MEMORY_BASIC_INFORMATION protection{};
    VirtualQuery(table, &protection, sizeof(protection));
    check(protection.Protect == PAGE_READONLY, "observer left table writable");
    char buffer[4]{};
    check(function<Read>(table[1])(&object, "fixture", buffer, 4) == 3 && std::strcmp(buffer, "ABC") == 0,
        "read result/data changed");
    check(function<Read>(table[1])(&object, "fixture", nullptr, -7) == -9, "negative read result/arguments changed");
    check(function<Async>(table[3])(&object, "fixture", 0xfedcba98U, 0xabcdef12U) == async_handle, "64-bit async handle changed");
    check(function<Complete>(table[4])(&object, async_handle, buffer, 0xabcdef12U), "true completion changed");
    check(!function<Complete>(table[4])(&object, async_handle, nullptr, 0xabcdef12U), "false completion changed");
    check(!function<Write>(table[0])(&object, "fixture", buffer, 4) && actual_writes == 0, "write barrier relaxed");
    auto counts = coop::storage_read_observation();
    check(counts.calls == std::array<std::uint64_t, 3>{2, 1, 2} && counts.sync_reported_bytes == 3, "initial read accounting wrong");
    std::vector<std::thread> threads;
    for (int t = 0; t != 4; ++t) threads.emplace_back([&] {
        char local[4]{};
        for (int i = 0; i != 1000; ++i) check(function<Read>(table[1])(&object, "fixture", local, 4) == 3, "concurrent forwarding failed");
    });
    for (auto& thread : threads) thread.join();
    counts = coop::storage_read_observation();
    check(counts.calls[0] == 4002 && counts.sync_reported_bytes == 12003 && actual_reads == 4002, "concurrent read accounting wrong");
    auto separate_table = original;
    Interface separate{separate_table.data()};
    coop::StorageReadObserver rejected;
    check(!rejected.attach(&separate) && separate_table == original, "second observer changed delegates/table");
    // A cached forwarding pointer remains valid after detach: it holds no
    // reference to this observer and the original delegates cannot be reused.
    const auto cached = function<Read>(table[1]);
    check(VirtualProtect(table, 4096, PAGE_READWRITE, &previous) != 0, "tamper setup failed");
    table[3] = reinterpret_cast<void*>(&write_file);
    check(VirtualProtect(table, 4096, PAGE_READONLY, &previous) != 0, "tamper protection restore failed");
    check(!reads.intact() && writers.intact(), "changed read entry remained healthy or damaged writer health");
    reads.detach();
    check(!reads.intact() && writers.intact(), "read detach changed write barrier");
    check(table[1] == original[1] && table[4] == original[4], "owned read entries not restored");
    check(table[3] == reinterpret_cast<void*>(&write_file), "detach overwrote another owner's read entry");
    check(cached(&object, "fixture", buffer, 4) == 3, "late forwarding pointer lost original");
    check(!rejected.attach(&separate), "delegate storage reused after detach");
    check(VirtualProtect(table, 4096, PAGE_READWRITE, &previous) != 0, "fixture cleanup protection failed");
    table[3] = original[3];
    check(VirtualProtect(table, 4096, PAGE_READONLY, &previous) != 0, "fixture cleanup restore failed");
    writers.detach();
    for (std::size_t i = 0; i != original.size(); ++i) check(table[i] == original[i], "combined restoration failed");
    VirtualQuery(table, &protection, sizeof(protection));
    check(protection.Protect == PAGE_READONLY, "combined detach left table writable");
    VirtualFree(table, 0, MEM_RELEASE);
    std::puts("Optional v014 read forwarding preserves ABI/results/data, writer barriers, concurrent counters and restoration");
}
