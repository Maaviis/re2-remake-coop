#pragma once
#include "storage_reads.h"

namespace coop {
constexpr std::size_t read_call_methods=3, utils_call_prefix_size=14, read_call_event_capacity=128;
constexpr std::int32_t remote_read_callback=1332, remote_read_callback_size=24;
struct ReadCallEvent {
    std::uint64_t sequence{};
    std::size_t method{};
    ReadCallIdentity read;
    bool original_result{}, failed_available{}, failed{}, payload_available{}, payload_handle_matches{}, payload_scope_matches{};
    std::int32_t callback_id{}, callback_size{}, failure_reason{}, payload_result{};
    std::uint32_t payload_offset{}, payload_bytes{};
};
struct ReadCallSnapshot {
    bool available=true;
    std::array<std::uint64_t,read_call_methods> calls{},matched_calls{};
    std::array<ReadCallEvent,read_call_event_capacity> events{};
    std::size_t event_count{};
    std::uint64_t event_sequence{},discarded_events{},observation_errors{},bookkeeping_errors{};
};
const std::array<GuardedMethod,read_call_methods>& read_call_methods_table();
ReadCallSnapshot read_call_observation() noexcept;

// Optional forwarding-only SteamUtils010 observation. Only unique known read
// handles receive events; originals remain immutable for late cached calls.
class ReadCallObserver {
public:
    ReadCallObserver()=default;
    ReadCallObserver(const ReadCallObserver&)=delete;
    ReadCallObserver& operator=(const ReadCallObserver&)=delete;
    ~ReadCallObserver();
    bool attach(void* utils);
    bool intact() const;
    void detach();
    void** table() const{return table_;}
    const char* error() const{return error_;}
private:
    void** table_{};
    std::array<void*,read_call_methods> original_{};
    unsigned long original_protection_{};
    bool protection_restored_{};
    const char* error_="not_attached";
};
} // namespace coop
