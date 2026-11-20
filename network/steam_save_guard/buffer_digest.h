#pragma once
#include "read_trace.h"

namespace coop {
constexpr std::uint32_t max_digest_bytes = 8 * 1024 * 1024;
constexpr std::size_t digest_record_capacity = read_ticket_capacity;
enum class DigestReason { pending, ok, invalid_range, unreadable_buffer, crypto_unavailable };
const char* digest_reason_name(DigestReason value);
struct BufferDigest {
    bool ok{};
    DigestReason reason = DigestReason::invalid_range;
    std::array<unsigned char,32> bytes{};
};
BufferDigest hash_read_buffer(const void* buffer, std::uint32_t size) noexcept;
struct BufferDigestRecord {
    ReadCompletion completion;
    bool in_progress = true;
    BufferDigest digest{false,DigestReason::pending,{}};
};
struct BufferDigestSnapshot {
    bool available = true;
    std::array<BufferDigestRecord,digest_record_capacity> records{};
    std::size_t count{};
    std::uint64_t skipped{}, overflows{}, bookkeeping_errors{};
};
class BufferDigestStore {
public:
    void observe(const ReadCompletion& completion, const void* buffer) noexcept;
    BufferDigestSnapshot snapshot() const noexcept;
private:
    mutable std::mutex mutex_;
    std::array<BufferDigestRecord,digest_record_capacity> records_{};
    std::size_t count_{};
    std::uint64_t skipped_{}, overflows_{};
    mutable std::atomic<std::uint64_t> bookkeeping_errors_{};
};
} // namespace coop
