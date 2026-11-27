#include "checkpoint_import.h"
#include <algorithm>
#include <cstring>
#include <sstream>

namespace coop {
namespace {
bool hex(const std::string& value, std::size_t size) {
    return value.size() == size && std::all_of(value.begin(), value.end(), [](char ch) {
        return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
    });
}
}
bool CheckpointImportRequest::operator==(const CheckpointImportRequest& other) const {
    return workspace == other.workspace && request_id == other.request_id && archive_namespace == other.archive_namespace &&
        generation == other.generation && hashes == other.hashes;
}
std::optional<CheckpointImportRequest> parse_checkpoint_import(std::string_view command) {
    if (command.empty() || command.size() > 512 || !std::all_of(command.begin(), command.end(), [](char ch) {
        return ch == ' ' || (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
    })) return std::nullopt;
    CheckpointImportRequest request;
    std::array<std::string, 3> hashes;
    std::string extra;
    std::istringstream input{std::string(command)};
    if (!(input >> request.workspace >> request.request_id >> request.archive_namespace >> request.generation >>
          hashes[0] >> hashes[1] >> hashes[2]) || input >> extra ||
        !hex(request.workspace, 32) || !hex(request.request_id, 32) || !hex(request.archive_namespace, 32) ||
        !hex(request.generation, 64)) return std::nullopt;
    for (std::size_t index = 0; index < hashes.size(); ++index) {
        if (!hex(hashes[index], 64)) return std::nullopt;
        const auto digit = [](char ch) { return static_cast<BYTE>(ch <= '9' ? ch-'0' : ch-'a'+10); };
        for (std::size_t at = 0; at < 32; ++at)
            request.hashes[index][at] = static_cast<BYTE>(digit(hashes[index][2*at]) * 16 + digit(hashes[index][2*at+1]));
    }
    return request;
}
void CheckpointImport::release_scope() { completed_scope_ = scope_; scope_.reset(); }
void CheckpointImport::fail(const char* reason) {
    phase_ = "failed"; error_ = reason;
    if (!call_) release_scope();
}
void CheckpointImport::clear_payload() {
    if (!payload_.empty()) SecureZeroMemory(payload_.data(), payload_.size());
    payload_.clear();
}
bool CheckpointImport::cancel(std::string_view request_id) {
    if (request_.request_id != request_id) return false;
    if (active()) fail("checkpoint_import_cancelled");
    return true;
}
bool CheckpointImport::active() const { return call_ || std::strcmp(phase_, "writing") == 0; }
bool CheckpointImport::start(const CheckpointImportRequest& request, StorageGuard& guard,
                             bool title_ready, std::uint64_t now) {
    if (!title_ready) return false;
    auto scope = guard.capture_campaign();
    if (!scope || scope->token != request.workspace) return false;
    if (!request_.request_id.empty() && request_.request_id == request.request_id)
        return request_ == request && (scope_ ? scope_ : completed_scope_.lock()) == scope;
    if (active()) return false;
    request_ = request;
    scope_ = std::move(scope);
    index_ = 0; call_ = 0; sizes_ = {}; result_ = 0;
    clear_payload();
    phase_ = "writing"; error_ = ""; deadline_ = now + 45000;
    return true;
}
void CheckpointImport::tick(StorageGuard& guard, const CheckpointImportBackend& backend,
                            bool title_ready, std::uint64_t now) {
    if (!active()) return;
    if (!backend.completed || !backend.result) { fail("steam_result_unavailable"); return; }
    if (std::strcmp(phase_, "failed") != 0) {
        if (!title_ready) fail("checkpoint_title_changed");
        else if (!guard.campaign_matches(scope_)) fail("checkpoint_campaign_changed");
        else if (now >= deadline_) fail("checkpoint_import_timeout");
    }
    if (call_) {
        if (!backend.completed(call_)) return;
        result_ = backend.result(call_);
        guard.retire_completed(backend.completed);
        call_ = 0;
        clear_payload();
        if (std::strcmp(phase_, "failed") == 0) { release_scope(); return; }
        if (result_ != 1) { fail("steam_checkpoint_write_failed"); return; }
        if (!guard.campaign_matches(scope_)) { fail("checkpoint_campaign_changed"); return; }
        if (!scope_->matches_checkpoint(checkpoint_files[index_], sizes_[index_], request_.hashes[index_])) {
            fail("checkpoint_working_file_mismatch"); return;
        }
        ++index_;
    }
    if (std::strcmp(phase_, "failed") == 0) return;
    if (index_ == checkpoint_files.size()) {
        for (std::size_t file = 0; file < sizes_.size(); ++file)
            if (!scope_->matches_checkpoint(checkpoint_files[file], sizes_[file], request_.hashes[file])) {
                fail("checkpoint_working_file_mismatch"); return;
            }
        phase_ = "ready";
        release_scope();
        return;
    }
    try {
        payload_ = scope_->read_checkpoint(request_.archive_namespace, request_.generation,
                                            checkpoint_files[index_], request_.hashes[index_]);
        sizes_[index_] = static_cast<DWORD>(payload_.size());
        call_ = guard.write_checkpoint(scope_, checkpoint_files[index_], payload_.data(), sizes_[index_]);
        if (!call_) { clear_payload(); fail("steam_checkpoint_write_rejected"); }
    } catch (const std::exception&) {
        clear_payload(); fail("checkpoint_archive_invalid");
    }
}
} // namespace coop
