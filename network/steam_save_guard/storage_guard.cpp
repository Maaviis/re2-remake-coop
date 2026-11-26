#include "storage_guard.h"
#include <windows.h>
#include <atomic>
#include <limits>
#include <algorithm>
#include <mutex>

namespace coop {
namespace {
std::array<std::atomic<std::uint64_t>, guarded_methods> counts{};
std::mutex campaign_mutex;
StorageGuard* authorized{};
bool write_file(void*, const char*, const void*, std::int32_t) { ++counts[0]; return false; }
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
        {2, "FileWriteAsync", reinterpret_cast<void*>(&StorageGuard::write_async)},
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

bool StorageGuard::set_campaign(const std::filesystem::path& save, const char* token,
                                const std::filesystem::path& steam_userdata, bool (*healthy)(),
                                bool (*completed)(std::uint64_t)) {
    std::lock_guard<std::mutex> lock(campaign_mutex);
    if (authorized == this) authorized = nullptr;
    campaign_.reset();
    if (!token) return true;
    if (authorized || !intact()) return false;
    auto folder = std::make_shared<CampaignFolder>();
    if (!folder->open(save, token, steam_userdata) || (healthy && !healthy())) return false;
    campaign_ = std::move(folder);
    healthy_ = healthy;
    completed_ = completed;
    authorized = this;
    return true;
}

std::string StorageGuard::campaign_namespace() const {
    std::lock_guard<std::mutex> lock(campaign_mutex);
    return campaign_ ? campaign_->token : std::string{};
}

std::uint64_t StorageGuard::write_async(void* object, const char* filename, const void* data, std::uint32_t size) {
    std::lock_guard<std::mutex> lock(campaign_mutex);
    return write_locked(object, filename, data, size, nullptr);
}

std::uint64_t StorageGuard::write_locked(void* object, const char* filename, const void* data,
                                        std::uint32_t size, const CampaignFolder* expected) {
    auto* guard = authorized;
    try {
        if (guard && guard->completed_) {
            guard->retire_locked(guard->completed_);
            guard = authorized;
        }
        if (guard && (!guard->intact() || (guard->healthy_ && !guard->healthy_()))) {
            authorized = nullptr;
            guard->campaign_.reset();
            guard = nullptr;
        }
        if (guard && (!expected || guard->campaign_.get() == expected) && guard->object_ == object && *reinterpret_cast<void***>(object) == guard->table_ && data && size &&
                size <= 100u * 1024u * 1024u && guard->pending_.size() < 128) {
            auto key = guard->campaign_->canonical_key(filename);
            const bool available = !key.empty() && std::none_of(guard->pending_.begin(), guard->pending_.end(),
                [&](const Pending& pending) { return pending.key == key; });
            if (available) {
                guard->pending_.reserve(guard->pending_.size() + 1);
                auto staging = guard->campaign_->reserve_staging(key);
                if (!staging) { ++counts[1]; return 0; }
                auto& pending = guard->pending_.emplace_back(Pending{0, guard->campaign_, std::move(staging), std::move(key), size, {}});
                pending.existing = pending.folder->matching_existing(pending.key, data, size);
                using Async = std::uint64_t(*)(void*, const char*, const void*, std::uint32_t);
                const auto original = reinterpret_cast<Async>(guard->original_[1]);
                pending.call = original(object, pending.key.c_str(), data, size);
                if (pending.call) return pending.call;
                pending.folder->discard_empty_staging(pending.key, pending.staging.get());
                guard->pending_.pop_back();
                // Steam rejected this allowed submission; preserve its result.
                return 0;
            }
        }
    } catch (const std::exception&) {
        // A malformed path or allocation failure must keep the hook closed.
    }
    ++counts[1];
    return 0;
}

std::shared_ptr<CampaignFolder> StorageGuard::capture_campaign() const {
    std::lock_guard<std::mutex> lock(campaign_mutex);
    return authorized == this && intact() && (!healthy_ || healthy_()) ? campaign_ : nullptr;
}

bool StorageGuard::campaign_matches(const std::shared_ptr<CampaignFolder>& scope) const {
    std::lock_guard<std::mutex> lock(campaign_mutex);
    return scope && campaign_ == scope && authorized == this && intact() && (!healthy_ || healthy_());
}

std::uint64_t StorageGuard::write_checkpoint(const std::shared_ptr<CampaignFolder>& scope,
                                            const std::string& leaf, const void* data, std::uint32_t size) {
    if (!scope || (leaf != "data000.bin" && leaf != "data021Slot.bin" && leaf != "data00-1.bin")) return 0;
    std::lock_guard<std::mutex> lock(campaign_mutex);
    if (authorized != this) return 0;
    const auto key = "coop-save-" + scope->token + '/' + leaf;
    return write_locked(object_, key.c_str(), data, size, scope.get());
}

void StorageGuard::retire_completed(bool (*completed)(std::uint64_t)) {
    std::lock_guard<std::mutex> lock(campaign_mutex);
    retire_locked(completed);
}

void StorageGuard::retire_locked(bool (*completed)(std::uint64_t)) {
    pending_.erase(std::remove_if(pending_.begin(), pending_.end(),
        [&](const Pending& pending) {
            if (!completed(pending.call)) return false;
            if (!pending.folder->committed(pending.key, pending.staging.get(), pending.size, pending.existing)) {
                if (campaign_ && campaign_->token == pending.folder->token) {
                    authorized = nullptr;
                    campaign_.reset();
                }
            }
            pending.folder->discard_empty_staging(pending.key, pending.staging.get());
            return true;
        }), pending_.end());
}

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
    object_ = interface_object;
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
    set_campaign({}, nullptr);
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
