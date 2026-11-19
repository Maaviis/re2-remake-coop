#pragma once
#include "storage_guard.h"
#include "read_trace.h"
#include "buffer_digest.h"
#include "private_read_source.h"

namespace coop {
constexpr std::size_t observed_read_methods = 3;
struct ReadObservation {
    std::array<std::uint64_t, observed_read_methods> calls{};
    std::uint64_t sync_reported_bytes{};
    std::uint64_t classification_errors{};
    ReadTraceSnapshot trace;
    bool digest_enabled{};
    BufferDigestSnapshot digests;
    PrivateReadSnapshot private_source;
};
const std::array<GuardedMethod, observed_read_methods>& storage_read_methods();
ReadObservation storage_read_observation();
ReadCallIdentity storage_read_call_identity(std::uint64_t handle) noexcept;
bool configure_storage_buffer_digests(bool enabled);
bool configure_storage_private_source(const std::filesystem::path& path,const std::array<unsigned char,32>& expected,
    std::string_view run_id,std::string_view request_id,std::uint32_t pid);
bool renew_storage_private_source(std::string_view run_id,std::string_view request_id,std::uint32_t pid,
    std::uint64_t issued,std::uint64_t now,bool healthy);

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
