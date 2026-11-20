#include "storage_reads.h"
#include <windows.h>
#include <atomic>
#include <limits>

namespace coop {
namespace {
std::atomic<bool> claimed{};
std::array<std::atomic<void*>, observed_read_methods> delegates{};
std::array<std::atomic<std::uint64_t>, observed_read_methods> calls{};
std::atomic<std::uint64_t> sync_reported_bytes{};
std::atomic<std::uint64_t> classification_errors{};
ReadTrace trace;
std::atomic<bool> digest_enabled{};
BufferDigestStore digests;
struct LastErrorRestore {
    DWORD value = GetLastError();
    ~LastErrorRestore() { SetLastError(value); }
};

std::size_t read_target(const char* name) noexcept {
    const LastErrorRestore last_error;
    // Do not dereference an untrusted native string or retain unknown names.
    // A short failed observation must never replace the original API call.
    struct TemporaryName {
        char bytes[64]{};
        ~TemporaryName() { SecureZeroMemory(bytes, sizeof(bytes)); }
    } copy;
    if (!name) { ++classification_errors; return unknown_read_target; }
    const auto process = GetCurrentProcess();
    const auto address = reinterpret_cast<std::uintptr_t>(name);
    for (std::size_t index = 0; index != sizeof(copy.bytes); ++index) {
        SIZE_T read{};
        if (index > (std::numeric_limits<std::uintptr_t>::max)() - address
            || !ReadProcessMemory(process, reinterpret_cast<const void*>(address + index), &copy.bytes[index], 1, &read) || read != 1) {
            ++classification_errors;
            return unknown_read_target;
        }
        if (copy.bytes[index] == '\0') return classify_read_target(std::string_view(copy.bytes, index));
    }
    ++classification_errors;
    return unknown_read_target;
}

template<typename Function>
Function original(std::size_t index) {
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(delegates[index].load(std::memory_order_acquire));
}

std::int32_t read_file(void* self, const char* name, void* buffer, std::int32_t size) {
    ++calls[0];
    const auto target = read_target(name);
    const auto result = original<std::int32_t(*)(void*, const char*, void*, std::int32_t)>(0)(self, name, buffer, size);
    const LastErrorRestore last_error;
    if (result > 0) sync_reported_bytes.fetch_add(static_cast<std::uint64_t>(result));
    trace.sync(target, result);
    return result;
}
std::uint64_t read_async(void* self, const char* name, std::uint32_t offset, std::uint32_t size) {
    ++calls[1];
    const auto target = read_target(name);
    const auto result = original<std::uint64_t(*)(void*, const char*, std::uint32_t, std::uint32_t)>(1)(self, name, offset, size);
    const LastErrorRestore last_error;
    trace.request(target, self, result, offset, size);
    return result;
}
bool complete_async(void* self, std::uint64_t handle, void* buffer, std::uint32_t size) {
    ++calls[2];
    const auto result = original<bool(*)(void*, std::uint64_t, void*, std::uint32_t)>(2)(self, handle, buffer, size);
    const LastErrorRestore last_error;
    const auto completion = trace.complete(self, handle, size, result);
    if (digest_enabled.load()) digests.observe(completion,buffer);
    return result;
}

bool readable(const void* address, std::size_t size) {
    MEMORY_BASIC_INFORMATION info{};
    if (!address || VirtualQuery(address, &info, sizeof(info)) != sizeof(info)
        || info.State != MEM_COMMIT || (info.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
    const auto start = reinterpret_cast<std::uintptr_t>(address);
    const auto base = reinterpret_cast<std::uintptr_t>(info.BaseAddress);
    return start >= base && size <= info.RegionSize && start - base <= info.RegionSize - size;
}
} // namespace

const std::array<GuardedMethod, observed_read_methods>& storage_read_methods() {
    // ISteamRemoteStorage014, SDK 1.51. Never patch the aliased flat exports.
    static const std::array<GuardedMethod, observed_read_methods> result{{
        {1, "FileRead", reinterpret_cast<void*>(&read_file)},
        {3, "FileReadAsync", reinterpret_cast<void*>(&read_async)},
        {4, "FileReadAsyncComplete", reinterpret_cast<void*>(&complete_async)},
    }};
    return result;
}

ReadCallIdentity storage_read_call_identity(std::uint64_t handle) noexcept {return trace.call_identity(handle);}
ReadObservation storage_read_observation() {
    ReadObservation result;
    for (std::size_t index = 0; index != calls.size(); ++index) result.calls[index] = calls[index].load();
    result.sync_reported_bytes = sync_reported_bytes.load();
    result.classification_errors = classification_errors.load();
    result.trace = trace.snapshot();
    result.digest_enabled = digest_enabled.load();
    result.digests = digests.snapshot();
    return result;
}
bool configure_storage_buffer_digests(bool enabled) {
    if (claimed.load()) return false;
    digest_enabled.store(enabled);
    return true;
}

StorageReadObserver::~StorageReadObserver() { detach(); }

bool StorageReadObserver::attach(void* interface_object) {
    if (table_) { error_ = "already_attached"; return false; }
    if (claimed.load()) { error_ = "observation_already_used"; return false; }
    if (!readable(interface_object, sizeof(void*))) { error_ = "invalid_interface"; return false; }
    auto** table = *reinterpret_cast<void***>(interface_object);
    if (!readable(table, sizeof(void*) * storage_prefix_size)) { error_ = "invalid_vtable"; return false; }
    const auto& methods = storage_read_methods();
    for (std::size_t index = 0; index != methods.size(); ++index) {
        auto* const method = table[methods[index].slot];
        if (!readable(method, 1) || method == methods[index].replacement) { error_ = "invalid_read_method"; return false; }
        original_[index] = method;
    }
    bool expected = false;
    if (!claimed.compare_exchange_strong(expected, true)) {
        error_ = "observation_already_used"; return false;
    }
    DWORD previous{};
    if (!VirtualProtect(table, sizeof(void*) * storage_prefix_size, PAGE_READWRITE, &previous)) {
        claimed.store(false);
        error_ = "vtable_protection_failed"; return false;
    }
    // Publish every original before exposing any forwarding function. Keep the
    // delegates for the rest of this process, without references to this object.
    for (std::size_t index = 0; index != methods.size(); ++index) delegates[index].store(original_[index], std::memory_order_release);
    table_ = table;
    original_protection_ = previous;
    for (const auto& method : methods) InterlockedExchangePointer(table_ + method.slot, method.replacement);
    DWORD ignored{};
    protection_restored_ = VirtualProtect(table_, sizeof(void*) * storage_prefix_size, previous, &ignored) != 0;
    const bool healthy = protection_restored_ && intact();
    error_ = !protection_restored_ ? "vtable_protection_restore_failed" : healthy ? "ok" : "read_integrity_failed";
    return healthy;
}

bool StorageReadObserver::intact() const {
    if (!protection_restored_ || !readable(table_, sizeof(void*) * storage_prefix_size)) return false;
    for (const auto& method : storage_read_methods()) if (table_[method.slot] != method.replacement) return false;
    return true;
}

void StorageReadObserver::detach() {
    if (!readable(table_, sizeof(void*) * storage_prefix_size)) { table_ = nullptr; return; }
    DWORD previous{};
    if (!VirtualProtect(table_, sizeof(void*) * storage_prefix_size, PAGE_READWRITE, &previous)) return;
    const auto& methods = storage_read_methods();
    for (std::size_t index = 0; index != methods.size(); ++index) {
        InterlockedCompareExchangePointer(table_ + methods[index].slot, original_[index], methods[index].replacement);
    }
    DWORD ignored{};
    VirtualProtect(table_, sizeof(void*) * storage_prefix_size, original_protection_, &ignored);
    table_ = nullptr;
    protection_restored_ = false;
}
} // namespace coop
