#pragma once
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string_view>

namespace coop {
constexpr std::size_t known_read_targets = 23;
constexpr std::size_t unknown_read_target = known_read_targets;
constexpr std::size_t read_ticket_capacity = 64;
constexpr std::size_t read_event_capacity = 64;
const char* known_read_target(std::size_t index);
std::size_t classify_read_target(std::string_view name);
enum class ReadPhase { requested, invalid_request, untracked_request, ambiguous_request,
    completed, unmatched_completion, ambiguous_completion };
const char* read_phase_name(ReadPhase phase);

struct ReadTargetObservation {
    std::uint64_t sync_calls{}, sync_reported_bytes{}, async_requests{}, invalid_handles{};
    std::uint64_t requested_bytes{}, completion_attempts{}, completion_successes{}, completion_failures{};
    std::uint64_t successful_completion_bytes{}, oversized_completions{};
    std::uint32_t last_offset{}, last_requested_size{}, last_completion_size{};
    bool last_completion_ok{};
};
struct ReadEvent {
    std::uint64_t sequence{}, request_id{};
    std::size_t target = unknown_read_target;
    ReadPhase phase{};
    std::uint32_t offset{}, requested_size{}, completion_size{};
    bool result{};
};
struct ReadTraceSnapshot {
    bool available = true;
    std::array<ReadTargetObservation, known_read_targets + 1> targets{};
    std::array<ReadEvent, read_event_capacity> events{};
    std::size_t event_count{}, retained_keys{}, pending{}, ambiguous_pending{};
    std::uint64_t event_sequence{}, discarded_events{}, collisions{}, overflows{};
    std::uint64_t unmatched_completions{}, ambiguous_completions{}, bookkeeping_errors{};
};
struct ReadCompletion {
    bool matched{}, original_ok{};
    std::uint64_t request_id{}, event_sequence{};
    std::size_t target = unknown_read_target;
    std::uint32_t offset{}, requested_size{}, completion_size{};
};
struct ReadCallIdentity {
    bool matched{}, completed{};
    std::uint64_t request_id{};
    std::size_t target = unknown_read_target;
    std::uint32_t offset{}, requested_size{};
};

// Bounded metadata only. Call methods after the original API returns, without
// holding a metadata lock across any Steam call. Never expose native handles.
class ReadTrace {
public:
    void sync(std::size_t target, std::int32_t reported) noexcept;
    void request(std::size_t target, void* owner, std::uint64_t handle,
                 std::uint32_t offset, std::uint32_t size) noexcept;
    ReadCompletion complete(void* owner, std::uint64_t handle, std::uint32_t size, bool ok) noexcept;
    // Utils call-result methods do not supply the storage receiver. Match only
    // a unique retained handle across all receivers, including completed keys.
    ReadCallIdentity call_identity(std::uint64_t handle) const noexcept;
    ReadTraceSnapshot snapshot() const noexcept;
private:
    struct Ticket {
        bool used{}, retired{}, ambiguous{};
        void* owner{};
        std::uint64_t handle{}, request_id{};
        std::size_t target = unknown_read_target;
        std::uint32_t offset{}, size{};
    };
    void append(ReadEvent event);
    mutable std::mutex mutex_;
    std::array<Ticket, read_ticket_capacity> tickets_{};
    std::array<ReadTargetObservation, known_read_targets + 1> targets_{};
    std::array<ReadEvent, read_event_capacity> events_{};
    std::size_t event_start_{}, event_count_{};
    std::uint64_t request_id_{}, event_sequence_{}, discarded_events_{}, collisions_{}, overflows_{};
    std::uint64_t unmatched_completions_{}, ambiguous_completions_{};
    mutable std::atomic<std::uint64_t> bookkeeping_errors_{};
};
} // namespace coop
