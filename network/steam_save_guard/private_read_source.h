#pragma once
#include "buffer_digest.h"
#include <filesystem>
#include <memory>
#include <vector>

namespace coop {
enum class PrivateReadReason { disabled, ready, bad_config, bad_source, source_hash_mismatch,
    lease_unavailable, scope_mismatch, exhausted, duplicate, original_mismatch,
    destination_not_writable, copy_failed, post_copy_mismatch, supplied };
const char* private_read_reason_name(PrivateReadReason value);
struct PrivateReadRecord {
    ReadCompletion completion;
    bool in_progress = true, before_matches{}, after_matches{}, supplied{};
    std::uint64_t copied_bytes{};
    PrivateReadReason reason = PrivateReadReason::ready;
};
struct PrivateReadSnapshot {
    bool enabled{}, prepared{}, armed{}, available = true;
    std::uint32_t source_bytes{};
    std::array<char,33> request_id{};
    std::array<PrivateReadRecord,2> records{};
    std::size_t count{};
    std::uint64_t ignored{}, rejected{}, bookkeeping_errors{};
    PrivateReadReason reason = PrivateReadReason::disabled;
};
// Bootstrap replay: an identical, verified old-slot copy supplies two whole
// responses. Original Steam requests/callbacks and disk write barriers remain.
class PrivateReadSource {
public:
    bool prepare(const std::filesystem::path& path, const std::array<unsigned char,32>& expected,
        std::uint32_t size, std::string_view run_id, std::string_view request_id, std::uint32_t pid) noexcept;
    bool renew(std::string_view run_id, std::string_view request_id, std::uint32_t pid,
        std::uint64_t issued, std::uint64_t now, bool guard_healthy) noexcept;
    void apply(const ReadCompletion& completion, void* buffer, std::uint64_t now) noexcept;
    PrivateReadSnapshot snapshot(std::uint64_t now) const noexcept;
private:
    mutable std::mutex mutex_;
    std::shared_ptr<const std::vector<unsigned char>> source_;
    std::array<unsigned char,32> expected_{};
    std::array<char,33> run_id_{}, request_id_{};
    std::uint32_t pid_{};
    std::uint64_t lease_until_{};
    bool enabled_{};
    PrivateReadReason reason_ = PrivateReadReason::disabled;
    std::array<PrivateReadRecord,2> records_{};
    std::size_t count_{};
    std::uint64_t ignored_{}, rejected_{};
    mutable std::atomic<std::uint64_t> bookkeeping_errors_{};
};
} // namespace coop
