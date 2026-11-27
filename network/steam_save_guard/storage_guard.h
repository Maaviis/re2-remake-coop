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
                      const std::filesystem::path& steam_userdata = {}, bool (*healthy)() = nullptr,
                      bool (*completed)(std::uint64_t) = nullptr);
    std::string campaign_namespace(const char** loss_reason = nullptr) const;
    void retire_completed(bool (*completed)(std::uint64_t));
    static std::uint64_t write_async(void* object, const char* filename, const void* data, std::uint32_t size);
    std::shared_ptr<CampaignFolder> capture_campaign() const;
    bool campaign_matches(const std::shared_ptr<CampaignFolder>& scope) const;
    std::uint64_t write_checkpoint(const std::shared_ptr<CampaignFolder>& scope, const std::string& leaf,
                                   const void* data, std::uint32_t size);
    void detach();
    const char* error() const { return error_; }
    void** table() const { return table_; }
private:
    static std::uint64_t write_locked(void* object, const char* filename, const void* data, std::uint32_t size,
                                      const CampaignFolder* expected);
    struct Pending {
        std::uint64_t call{};
        std::shared_ptr<CampaignFolder> folder;
        FileHandle staging;
        std::string key;
        DWORD size{};
        ExistingCheckpoint existing;
    };
    void* object_{};
    bool (*healthy_)(){};
    bool (*completed_)(std::uint64_t){};
    void retire_locked(bool (*completed)(std::uint64_t));
    std::shared_ptr<CampaignFolder> campaign_;
    const char* campaign_loss_{};
    std::vector<Pending> pending_;
    void** table_{};
    std::array<void*, guarded_methods> original_{};
    const char* error_ = "not_attached";
};
} // namespace coop
