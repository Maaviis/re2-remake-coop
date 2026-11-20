#include "buffer_digest.h"
#include <windows.h>
#include <bcrypt.h>
#include <algorithm>
#include <limits>

namespace coop {
namespace {
struct LastErrorRestore {
    DWORD value = GetLastError();
    ~LastErrorRestore() { SetLastError(value); }
};
struct HashResources {
    BCRYPT_ALG_HANDLE algorithm{};
    BCRYPT_HASH_HANDLE hash{};
    std::array<unsigned char,4096> object{};
    std::array<unsigned char,65536> scratch{};
    ~HashResources() {
        if (hash) BCryptDestroyHash(hash);
        if (algorithm) BCryptCloseAlgorithmProvider(algorithm,0);
        SecureZeroMemory(object.data(),object.size());
        SecureZeroMemory(scratch.data(),scratch.size());
    }
};
} // namespace
const char* digest_reason_name(DigestReason value) {
    switch (value) {
    case DigestReason::pending: return "pending";
    case DigestReason::ok: return "ok";
    case DigestReason::invalid_range: return "invalid_range";
    case DigestReason::unreadable_buffer: return "unreadable_buffer";
    case DigestReason::crypto_unavailable: return "crypto_unavailable";
    }
    return "unsupported";
}
BufferDigest hash_read_buffer(const void* buffer, std::uint32_t size) noexcept {
    const LastErrorRestore last_error;
    BufferDigest result;
    const auto address = reinterpret_cast<std::uintptr_t>(buffer);
    if (size > max_digest_bytes || (size && (!buffer
        || address > (std::numeric_limits<std::uintptr_t>::max)() - (size-1)))) return result;
    result.reason = DigestReason::crypto_unavailable;
    HashResources resources;
    if (BCryptOpenAlgorithmProvider(&resources.algorithm,BCRYPT_SHA256_ALGORITHM,MS_PRIMITIVE_PROVIDER,0) < 0) return result;
    ULONG object_size{}, digest_size{}, returned{};
    if (BCryptGetProperty(resources.algorithm,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&object_size),sizeof(object_size),&returned,0) < 0
        || returned != sizeof(object_size) || object_size > resources.object.size()
        || BCryptGetProperty(resources.algorithm,BCRYPT_HASH_LENGTH,reinterpret_cast<PUCHAR>(&digest_size),sizeof(digest_size),&returned,0) < 0
        || returned != sizeof(digest_size) || digest_size != result.bytes.size()
        || BCryptCreateHash(resources.algorithm,&resources.hash,resources.object.data(),object_size,nullptr,0,0) < 0) return result;
    const auto process = GetCurrentProcess();
    for (std::uint32_t offset = 0; offset < size;) {
        const auto count = (std::min)(static_cast<std::uint32_t>(resources.scratch.size()),size-offset);
        SIZE_T read{};
        if (!ReadProcessMemory(process,reinterpret_cast<const void*>(address+offset),resources.scratch.data(),count,&read)
            || read != count) { result.reason = DigestReason::unreadable_buffer; return result; }
        if (BCryptHashData(resources.hash,resources.scratch.data(),count,0) < 0) return result;
        offset += count;
    }
    if (BCryptFinishHash(resources.hash,result.bytes.data(),static_cast<ULONG>(result.bytes.size()),0) < 0) return result;
    result.ok = true;
    result.reason = DigestReason::ok;
    return result;
}
void BufferDigestStore::observe(const ReadCompletion& completion, const void* buffer) noexcept {
    try {
        std::size_t index{};
        {
            const std::lock_guard<std::mutex> lock(mutex_);
            if (!completion.matched || !completion.original_ok || !completion.request_id || !completion.event_sequence
                || completion.target >= known_read_targets
                || completion.completion_size > completion.requested_size
                || static_cast<std::uint64_t>(completion.offset)+completion.requested_size > max_digest_bytes) { ++skipped_; return; }
            for (std::size_t n = 0; n != count_; ++n) if (records_[n].completion.request_id == completion.request_id) { ++skipped_; return; }
            if (count_ == records_.size()) { ++overflows_; return; }
            index = count_++;
            records_[index].completion = completion;
        }
        // No metadata lock is held while reading/hash-computing caller memory.
        // No caller buffer or native object reference is retained in the store.
        const auto digest = hash_read_buffer(buffer,completion.completion_size);
        {
            const std::lock_guard<std::mutex> lock(mutex_);
            records_[index].digest = digest;
            records_[index].in_progress = false;
        }
    } catch (...) { ++bookkeeping_errors_; }
}
BufferDigestSnapshot BufferDigestStore::snapshot() const noexcept {
    BufferDigestSnapshot result;
    try {
        const std::lock_guard<std::mutex> lock(mutex_);
        result.records = records_;
        result.count = count_;
        result.skipped = skipped_;
        result.overflows = overflows_;
    } catch (...) { ++bookkeeping_errors_; result.available = false; }
    result.bookkeeping_errors = bookkeeping_errors_.load();
    return result;
}
} // namespace coop
