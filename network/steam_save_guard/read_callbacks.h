#pragma once
#include "delay_import.h"
#include "callback_abi.h"
#include "storage_reads.h"

namespace coop {
constexpr std::size_t read_callback_methods=4,read_callback_classes=4,read_callback_events=128;
const char* read_callback_method_name(std::size_t method);
struct ReadCallbackEvent {
    std::uint64_t sequence{};
    std::size_t method{};
    ReadCallIdentity read;
    std::int32_t callback_id{},callback_size{},payload_result{};
    std::uint32_t payload_offset{},payload_bytes{};
    bool metadata_available{},class_observed{},io_failure{},payload_available{},handle_matches{},scope_matches{},returned{};
};
struct ReadCallbackSnapshot {
    bool available=true,classes_intact=true;
    std::array<std::uint64_t,read_callback_methods> calls{},matched_calls{};
    std::array<ReadCallbackEvent,read_callback_events> events{};
    std::size_t event_count{},classes{};
    std::uint64_t event_sequence{},discarded_events{},unsupported_classes{},observation_errors{},bookkeeping_errors{};
};
struct ReadCallbackImports {
    void** register_slot{};void** unregister_slot{};
    void* register_previous{};void* unregister_previous{};
    void* register_export{};void* unregister_export{};
    void* callback_code_owner{};
};
ReadCallbackSnapshot read_callback_observation() noexcept;
// The bootstrap caller verifies PE import identity, exports and current target
// provenance. Observers forward through fixed exports, including unresolved
// delay slots. No callback instance or payload pointer survives its API call.
class ReadCallbackObserver {
public:
    ReadCallbackObserver()=default;
    ReadCallbackObserver(const ReadCallbackObserver&)=delete;
    ReadCallbackObserver& operator=(const ReadCallbackObserver&)=delete;
    ~ReadCallbackObserver();
    bool attach(const ReadCallbackImports& imports);
    bool intact() const;
    void detach();
    bool attempted() const{return attempted_;}
    const char* error() const{return error_;}
private:
    ImportPatch register_patch_,unregister_patch_;
    bool attempted_{},owns_{};
    const char* error_="not_attached";
};
} // namespace coop
