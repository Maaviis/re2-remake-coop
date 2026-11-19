#include "storage_guard.h"
#include <windows.h>
#include <atomic>
#include <limits>

namespace coop {
namespace {
std::array<std::atomic<std::uint64_t>, guarded_methods> counts{};
bool write_file(void*, const char*, const void*, std::int32_t) { ++counts[0]; return false; }
std::uint64_t write_async(void*, const char*, const void*, std::uint32_t) { ++counts[1]; return 0; }
bool forget_file(void*, const char*) { ++counts[2]; return false; }
bool delete_file(void*, const char*) { ++counts[3]; return false; }
std::uint64_t share_file(void*, const char*) { ++counts[4]; return 0; }
bool sync_platforms(void*, const char*, std::uint32_t) { ++counts[5]; return false; }
std::uint64_t stream_open(void*, const char*) { ++counts[6]; return (std::numeric_limits<std::uint64_t>::max)(); }
bool stream_write(void*, std::uint64_t, const void*, std::int32_t) { ++counts[7]; return false; }
bool stream_close(void*, std::uint64_t) { ++counts[8]; return false; }
bool stream_cancel(void*, std::uint64_t) { ++counts[9]; return false; }

bool readable(const void* address, std::size_t size) {
    MEMORY_BASIC_INFORMATION info{};
    if (!address || VirtualQuery(address, &info, sizeof(info)) != sizeof(info)
        || info.State != MEM_COMMIT || (info.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
    const auto start = reinterpret_cast<std::uintptr_t>(address);
    const auto base = reinterpret_cast<std::uintptr_t>(info.BaseAddress);
    return start >= base && size <= info.RegionSize && start - base <= info.RegionSize - size;
}
} // namespace

const std::array<GuardedMethod, guarded_methods>& storage_methods() {
    static const std::array<GuardedMethod, guarded_methods> result{{
        {0, "FileWrite", reinterpret_cast<void*>(&write_file)},
        {2, "FileWriteAsync", reinterpret_cast<void*>(&write_async)},
        {5, "FileForget", reinterpret_cast<void*>(&forget_file)},
        {6, "FileDelete", reinterpret_cast<void*>(&delete_file)},
        {7, "FileShare", reinterpret_cast<void*>(&share_file)},
        {8, "SetSyncPlatforms", reinterpret_cast<void*>(&sync_platforms)},
        {9, "FileWriteStreamOpen", reinterpret_cast<void*>(&stream_open)},
        {10, "FileWriteStreamWriteChunk", reinterpret_cast<void*>(&stream_write)},
        {11, "FileWriteStreamClose", reinterpret_cast<void*>(&stream_close)},
        {12, "FileWriteStreamCancel", reinterpret_cast<void*>(&stream_cancel)},
    }};
    return result;
}

std::array<std::uint64_t, guarded_methods> storage_counts() {
    std::array<std::uint64_t, guarded_methods> result{};
    for (std::size_t index = 0; index != result.size(); ++index) result[index] = counts[index].load();
    return result;
}

StorageGuard::~StorageGuard() { detach(); }

bool StorageGuard::attach(void* interface_object) {
    if (table_) { error_ = "already_attached"; return false; }
    if (!readable(interface_object, sizeof(void*))) { error_ = "invalid_interface"; return false; }
    auto** table = *reinterpret_cast<void***>(interface_object);
    if (!readable(table, sizeof(void*) * storage_prefix_size)) { error_ = "invalid_vtable"; return false; }
    for (std::size_t index = 0; index != storage_prefix_size; ++index) {
        if (!readable(table[index], 1)) { error_ = "invalid_method"; return false; }
    }
    const auto& methods = storage_methods();
    for (std::size_t index = 0; index != methods.size(); ++index) {
        if (table[methods[index].slot] == methods[index].replacement) { error_ = "already_guarded"; return false; }
        original_[index] = table[methods[index].slot];
    }
    DWORD previous{};
    if (!VirtualProtect(table, sizeof(void*) * storage_prefix_size, PAGE_READWRITE, &previous)) {
        error_ = "vtable_protection_failed"; return false;
    }
    table_ = table;
    for (const auto& method : methods) InterlockedExchangePointer(table_ + method.slot, method.replacement);
    DWORD ignored{};
    const bool restored = VirtualProtect(table_, sizeof(void*) * storage_prefix_size, previous, &ignored) != 0;
    const bool healthy = restored && intact();
    error_ = !restored ? "vtable_protection_restore_failed" : healthy ? "ok" : "guard_integrity_failed";
    return healthy;
}

bool StorageGuard::intact() const {
    if (!readable(table_, sizeof(void*) * storage_prefix_size)) return false;
    for (const auto& method : storage_methods()) if (table_[method.slot] != method.replacement) return false;
    return true;
}

void StorageGuard::detach() {
    if (!readable(table_, sizeof(void*) * storage_prefix_size)) { table_ = nullptr; return; }
    DWORD previous{};
    if (!VirtualProtect(table_, sizeof(void*) * storage_prefix_size, PAGE_READWRITE, &previous)) return;
    const auto& methods = storage_methods();
    for (std::size_t index = 0; index != methods.size(); ++index) {
        InterlockedCompareExchangePointer(table_ + methods[index].slot, original_[index], methods[index].replacement);
    }
    DWORD ignored{};
    VirtualProtect(table_, sizeof(void*) * storage_prefix_size, previous, &ignored);
    table_ = nullptr;
}
} // namespace coop
