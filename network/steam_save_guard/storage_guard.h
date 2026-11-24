#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include "campaign_folder.h"

namespace coop {
// Exact published ISteamRemoteStorage014 prefix, not the aliased flat export stubs.
// Valve Proton steamworks_sdk_151/isteamremotestorage.h defines these slots.
constexpr std::size_t storage_prefix_size = 13;
constexpr std::size_t guarded_methods = 10;
struct GuardedMethod {
    std::size_t slot;
    const char* name;
    void* replacement;
};
const std::array<GuardedMethod, guarded_methods>& storage_methods();
std::array<std::uint64_t, guarded_methods> storage_counts();

class StorageGuard {
public:
    StorageGuard() = default;
    StorageGuard(const StorageGuard&) = delete;
    StorageGuard& operator=(const StorageGuard&) = delete;
    ~StorageGuard();
    bool attach(void* interface_object);
    bool intact() const;
    bool set_campaign(const std::filesystem::path& save, const char* token,
                      const std::filesystem::path& steam_userdata = {}, bool (*healthy)() = nullptr);
    std::string campaign_namespace() const;
    void retire_completed(bool (*completed)(std::uint64_t));
    static std::uint64_t write_async(void* object, const char* filename, const void* data, std::uint32_t size);
    void detach();
    const char* error() const { return error_; }
    void** table() const { return table_; }
private:
    struct Pending {
        std::uint64_t call{};
        std::shared_ptr<CampaignFolder> folder;
        FileHandle file;
        std::string key;
    };
    void* object_{};
    bool (*healthy_)(){};
    std::shared_ptr<CampaignFolder> campaign_;
    std::vector<Pending> pending_;
    void** table_{};
    std::array<void*, guarded_methods> original_{};
    const char* error_ = "not_attached";
};
} // namespace coop
