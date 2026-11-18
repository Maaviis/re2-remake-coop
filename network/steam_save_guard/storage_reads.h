#pragma once
#include "storage_guard.h"

namespace coop {
constexpr std::size_t observed_read_methods = 3;
struct ReadObservation {
    std::array<std::uint64_t, observed_read_methods> calls{};
    std::uint64_t sync_reported_bytes{};
};
const std::array<GuardedMethod, observed_read_methods>& storage_read_methods();
ReadObservation storage_read_observation();

// Optional forwarding-only instrumentation. One attachment per process lifetime:
// original delegates remain immutable even after detach and concurrent late calls.
class StorageReadObserver {
public:
    StorageReadObserver() = default;
    StorageReadObserver(const StorageReadObserver&) = delete;
    StorageReadObserver& operator=(const StorageReadObserver&) = delete;
    ~StorageReadObserver();
    bool attach(void* interface_object);
    bool intact() const;
    void detach();
    void** table() const { return table_; }
    const char* error() const { return error_; }
private:
    void** table_{};
    std::array<void*, observed_read_methods> original_{};
    unsigned long original_protection_{};
    bool protection_restored_{};
    const char* error_ = "not_attached";
};
} // namespace coop
