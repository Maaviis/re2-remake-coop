#include "read_trace.h"

namespace coop {
namespace {
constexpr std::array<const char*, known_read_targets> names{{
    "./win64_save/data00-1.bin", "./win64_save/data000.bin",
    "./win64_save/data001Slot.bin", "./win64_save/data002Slot.bin", "./win64_save/data003Slot.bin",
    "./win64_save/data004Slot.bin", "./win64_save/data005Slot.bin", "./win64_save/data006Slot.bin",
    "./win64_save/data007Slot.bin", "./win64_save/data008Slot.bin", "./win64_save/data009Slot.bin",
    "./win64_save/data010Slot.bin", "./win64_save/data011Slot.bin", "./win64_save/data012Slot.bin",
    "./win64_save/data013Slot.bin", "./win64_save/data014Slot.bin", "./win64_save/data015Slot.bin",
    "./win64_save/data016Slot.bin", "./win64_save/data017Slot.bin", "./win64_save/data018Slot.bin",
    "./win64_save/data019Slot.bin", "./win64_save/data020Slot.bin", "./win64_save/data021Slot.bin",
}};
std::size_t bounded_target(std::size_t target) { return target < names.size() ? target : unknown_read_target; }
} // namespace

const char* known_read_target(std::size_t index) { return index < names.size() ? names[index] : nullptr; }
std::size_t classify_read_target(std::string_view name) {
    for (std::size_t index = 0; index != names.size(); ++index) {
        if (name == names[index]) return index;
    }
    return unknown_read_target;
}
const char* read_phase_name(ReadPhase phase) {
    switch (phase) {
    case ReadPhase::requested: return "request_returned";
    case ReadPhase::invalid_request: return "invalid_request_returned";
    case ReadPhase::untracked_request: return "untracked_request_returned";
    case ReadPhase::ambiguous_request: return "ambiguous_request_returned";
    case ReadPhase::completed: return "completion_returned";
    case ReadPhase::unmatched_completion: return "unmatched_completion_returned";
    case ReadPhase::ambiguous_completion: return "ambiguous_completion_returned";
    }
    return "unsupported";
}

void ReadTrace::append(ReadEvent event) {
    event.sequence = ++event_sequence_;
    if (event_count_ == events_.size()) {
        event_start_ = (event_start_ + 1) % events_.size();
        --event_count_;
        ++discarded_events_;
    }
    events_[(event_start_ + event_count_) % events_.size()] = event;
    ++event_count_;
}
void ReadTrace::sync(std::size_t target, std::int32_t reported) noexcept {
    try {
        const std::lock_guard<std::mutex> lock(mutex_);
        auto& value = targets_[bounded_target(target)];
        ++value.sync_calls;
        if (reported > 0) value.sync_reported_bytes += static_cast<std::uint64_t>(reported);
    } catch (...) { ++bookkeeping_errors_; }
}
void ReadTrace::request(std::size_t target, void* owner, std::uint64_t handle,
                        std::uint32_t offset, std::uint32_t size) noexcept {
    try {
        const std::lock_guard<std::mutex> lock(mutex_);
        target = bounded_target(target);
        auto& value = targets_[target];
        ++value.async_requests;
        value.requested_bytes += size;
        value.last_offset = offset;
        value.last_requested_size = size;
        ReadEvent event{0, ++request_id_, target, ReadPhase::requested, offset, size, 0, handle != 0};
        if (!handle) { ++value.invalid_handles; event.phase = ReadPhase::invalid_request; append(event); return; }
        Ticket* free = nullptr;
        for (auto& item : tickets_) {
            if (item.used && item.owner == owner && item.handle == handle) {
                // Keep the ambiguous key poisoned for this trace's lifetime.
                // Never attribute either request's completion to one file.
                item.ambiguous = true;
                item.retired = false;
                ++collisions_;
                event.phase = ReadPhase::ambiguous_request;
                append(event);
                return;
            }
            if (!item.used && !free) free = &item;
        }
        if (!free) { ++overflows_; event.phase = ReadPhase::untracked_request; append(event); return; }
        *free = {true, false, false, owner, handle, event.request_id, target, offset, size};
        append(event);
    } catch (...) { ++bookkeeping_errors_; }
}
void ReadTrace::complete(void* owner, std::uint64_t handle, std::uint32_t size, bool ok) noexcept {
    try {
        const std::lock_guard<std::mutex> lock(mutex_);
        for (auto& item : tickets_) {
            if (!item.used || item.retired || item.owner != owner || item.handle != handle) continue;
            if (item.ambiguous) {
                ++ambiguous_completions_;
                append({0, 0, unknown_read_target, ReadPhase::ambiguous_completion, 0, 0, size, ok});
                return;
            }
            auto& value = targets_[item.target];
            ++value.completion_attempts;
            value.last_completion_size = size;
            value.last_completion_ok = ok;
            if (ok) { ++value.completion_successes; value.successful_completion_bytes += size; }
            else ++value.completion_failures;
            if (size > item.size) ++value.oversized_completions;
            append({0, item.request_id, item.target, ReadPhase::completed, item.offset, item.size, size, ok});
            // Retain the completed key so late duplicate completions or handle
            // reuse cannot be attributed to a different request in this trace.
            if (ok) item.retired = true;
            return;
        }
        ++unmatched_completions_;
        append({0, 0, unknown_read_target, ReadPhase::unmatched_completion, 0, 0, size, ok});
    } catch (...) { ++bookkeeping_errors_; }
}
ReadTraceSnapshot ReadTrace::snapshot() const noexcept {
    ReadTraceSnapshot result;
    try {
        const std::lock_guard<std::mutex> lock(mutex_);
        result.targets = targets_;
        result.event_count = event_count_;
        result.event_sequence = event_sequence_;
        result.discarded_events = discarded_events_;
        result.collisions = collisions_;
        result.overflows = overflows_;
        result.unmatched_completions = unmatched_completions_;
        result.ambiguous_completions = ambiguous_completions_;
        for (std::size_t index = 0; index != event_count_; ++index)
            result.events[index] = events_[(event_start_ + index) % events_.size()];
        for (const auto& item : tickets_) if (item.used) {
            ++result.retained_keys;
            if (!item.retired) ++result.pending;
            if (item.ambiguous) ++result.ambiguous_pending;
        }
    } catch (...) { ++bookkeeping_errors_; result.available = false; }
    result.bookkeeping_errors = bookkeeping_errors_.load();
    return result;
}
} // namespace coop
