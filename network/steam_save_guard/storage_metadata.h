#pragma once
#include "storage_guard.h"
#include "read_trace.h"

namespace coop {
// ISteamRemoteStorage014 (Steamworks 1.51), slots 13 through 22.
// SetCloudEnabledForApp at slot 23 is deliberately outside this reader.
constexpr std::size_t metadata_prefix_size = 23, metadata_methods = 10;
constexpr std::size_t global_metadata_target = known_read_targets + 1;
constexpr std::size_t metadata_target_count = known_read_targets + 2;
constexpr std::size_t metadata_event_capacity = 128;
struct MetadataEvent {
    std::uint64_t sequence{};
    std::size_t method{}, target = unknown_read_target;
    std::int32_t index = -1;
    std::int64_t value{};
    std::uint64_t unsigned_value{}, secondary{};
    bool name_returned{}, has_value{}, has_unsigned_value{}, has_secondary{};
};
struct MetadataSnapshot {
    bool available = true;
    std::array<std::uint64_t, metadata_methods> calls{};
    std::array<std::array<std::uint64_t, metadata_methods>, metadata_target_count> targets{};
    std::array<MetadataEvent, metadata_event_capacity> events{};
    std::size_t event_count{};
    std::uint64_t event_sequence{}, discarded_events{}, observation_errors{}, bookkeeping_errors{};
};
const std::array<GuardedMethod, metadata_methods>& storage_metadata_methods();
std::size_t classify_metadata_target(std::string_view name);
MetadataSnapshot storage_metadata_observation() noexcept;

// One attachment per process. Cached forwarding pointers keep immutable original
// delegates after detach; no observer object or native output pointer is retained.
class StorageMetadataObserver {
public:
    StorageMetadataObserver() = default;
    StorageMetadataObserver(const StorageMetadataObserver&) = delete;
    StorageMetadataObserver& operator=(const StorageMetadataObserver&) = delete;
    ~StorageMetadataObserver();
    bool attach(void* interface_object);
    bool intact() const;
    void detach();
    void** table() const { return table_; }
    const char* error() const { return error_; }
private:
    void** table_{};
    std::array<void*, metadata_methods> original_{};
    unsigned long original_protection_{};
    bool protection_restored_{};
    const char* error_ = "not_attached";
};
} // namespace coop
