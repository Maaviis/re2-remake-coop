#pragma once
#include "storage_guard.h"
#include <array>
#include <optional>
#include <string>
#include <string_view>

namespace coop {
inline constexpr std::array<const char*, 3> checkpoint_files{{"data000.bin", "data021Slot.bin", "data00-1.bin"}};
struct CheckpointImportRequest {
    std::string workspace, request_id, archive_namespace, generation;
    std::array<std::array<BYTE, 32>, 3> hashes{};
    bool operator==(const CheckpointImportRequest& other) const;
};
std::optional<CheckpointImportRequest> parse_checkpoint_import(std::string_view command);
struct CheckpointImportBackend {
    bool (*completed)(std::uint64_t);
    int (*result)(std::uint64_t);
};
class CheckpointImport {
public:
    bool start(const CheckpointImportRequest& request, StorageGuard& guard, bool title_ready,
               std::uint64_t now = GetTickCount64());
    void tick(StorageGuard& guard, const CheckpointImportBackend& backend, bool title_ready,
              std::uint64_t now = GetTickCount64());
    bool cancel(std::string_view request_id);
    bool active() const;
    const CheckpointImportRequest& request() const { return request_; }
    const char* phase() const { return phase_; }
    const char* error() const { return error_; }
    std::size_t file_index() const { return index_; }
    int native_result() const { return result_; }
private:
    void fail(const char* reason);
    void clear_payload();
    void release_scope();
    CheckpointImportRequest request_;
    std::shared_ptr<CampaignFolder> scope_;
    std::weak_ptr<CampaignFolder> completed_scope_;
    std::vector<BYTE> payload_;
    std::array<DWORD, 3> sizes_{};
    std::uint64_t call_{}, deadline_{};
    std::size_t index_{};
    int result_{};
    const char* phase_ = "idle";
    const char* error_ = "";
};
} // namespace coop
