#include "private_read_source.h"
#include <windows.h>
#include <algorithm>
#include <chrono>
#include <cstring>
#include <limits>

namespace coop {
namespace {
struct ErrorRestore { DWORD value=GetLastError(); ~ErrorRestore(){ SetLastError(value); } };
struct Handle { HANDLE value=INVALID_HANDLE_VALUE; ~Handle(){ if(value!=INVALID_HANDLE_VALUE) CloseHandle(value); } };
bool token(std::string_view value) {
    if(value.size()!=32) return false;
    for(const auto c:value) if(!((c>='0'&&c<='9')||(c>='a'&&c<='f'))) return false;
    return true;
}
bool writable(void* buffer,std::size_t size) {
    const auto address=reinterpret_cast<std::uintptr_t>(buffer);
    if(!buffer || !size || address>(std::numeric_limits<std::uintptr_t>::max)()-(size-1)) return false;
    for(std::size_t offset=0;offset<size;) {
        MEMORY_BASIC_INFORMATION info{};
        if(VirtualQuery(reinterpret_cast<void*>(address+offset),&info,sizeof(info))!=sizeof(info)
            || info.State!=MEM_COMMIT || (info.Protect & (PAGE_GUARD|PAGE_NOACCESS))) return false;
        const auto protection=info.Protect&0xff;
        if(protection!=PAGE_READWRITE && protection!=PAGE_WRITECOPY) return false;
        const auto base=reinterpret_cast<std::uintptr_t>(info.BaseAddress);
        if(address+offset<base || address+offset-base>=info.RegionSize) return false;
        offset+=(std::min)(size-offset,info.RegionSize-(address+offset-base));
    }
    return true;
}
bool exact_file_path(HANDLE file,const std::filesystem::path& path) {
    const auto input=path.native();
    if(input.size()<3 || input[1]!=L':' || (input[2]!=L'\\' && input[2]!=L'/')) return false;
    const auto full_size=GetFullPathNameW(input.c_str(),0,nullptr,nullptr);
    const auto final_size=GetFinalPathNameByHandleW(file,nullptr,0,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    if(!full_size || !final_size || full_size>32768 || final_size>32768) return false;
    std::vector<wchar_t> full(full_size+1),final(final_size+1);
    const auto full_read=GetFullPathNameW(input.c_str(),static_cast<DWORD>(full.size()),full.data(),nullptr);
    const auto final_read=GetFinalPathNameByHandleW(file,final.data(),static_cast<DWORD>(final.size()),FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    if(!full_read || full_read>=full.size() || !final_read || final_read>=final.size()) return false;
    const std::wstring expected=L"\\\\?\\"+std::wstring(full.data());
    return _wcsicmp(expected.c_str(),final.data())==0;
}
} // namespace
const char* private_read_reason_name(PrivateReadReason value) {
    switch(value) {
    case PrivateReadReason::disabled:return "disabled"; case PrivateReadReason::ready:return "ready";
    case PrivateReadReason::bad_config:return "bad_config"; case PrivateReadReason::bad_source:return "bad_source";
    case PrivateReadReason::source_hash_mismatch:return "source_hash_mismatch";
    case PrivateReadReason::lease_unavailable:return "lease_unavailable"; case PrivateReadReason::scope_mismatch:return "scope_mismatch";
    case PrivateReadReason::exhausted:return "exhausted"; case PrivateReadReason::duplicate:return "duplicate";
    case PrivateReadReason::original_mismatch:return "original_mismatch";
    case PrivateReadReason::destination_not_writable:return "destination_not_writable";
    case PrivateReadReason::copy_failed:return "copy_failed"; case PrivateReadReason::post_copy_mismatch:return "post_copy_mismatch";
    case PrivateReadReason::supplied:return "supplied";
    }
    return "unsupported";
}
bool PrivateReadSource::prepare(const std::filesystem::path& path,const std::array<unsigned char,32>& expected,
    std::uint32_t size,std::string_view run,std::string_view request,std::uint32_t pid) noexcept {
    const ErrorRestore preserve;
    try {
        const std::lock_guard<std::mutex> lock(mutex_);
        if(enabled_) return false;
        enabled_=true; reason_=PrivateReadReason::bad_config;
        if(!token(run)||!token(request)||!pid||!size||size>max_digest_bytes
            || !path.is_absolute() || path.filename()!=L"data004Slot.bin") return false;
        std::copy(run.begin(),run.end(),run_id_.begin());
        std::copy(request.begin(),request.end(),request_id_.begin()); pid_=pid; expected_=expected;
        reason_=PrivateReadReason::bad_source;
        Handle file;
        file.value=CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
        if(file.value==INVALID_HANDLE_VALUE) return false;
        BY_HANDLE_FILE_INFORMATION info{};
        if(!GetFileInformationByHandle(file.value,&info) || (info.dwFileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT))
            || info.nFileSizeHigh || info.nFileSizeLow!=size || !exact_file_path(file.value,path)) return false;
        auto bytes=std::make_shared<std::vector<unsigned char>>(size);
        DWORD read{};
        if(!ReadFile(file.value,bytes->data(),size,&read,nullptr)||read!=size) return false;
        const auto digest=hash_read_buffer(bytes->data(),size);
        if(!digest.ok || digest.bytes!=expected) { reason_=PrivateReadReason::source_hash_mismatch; return false; }
        source_=std::move(bytes); reason_=PrivateReadReason::ready; return true;
    } catch(...) { ++bookkeeping_errors_; return false; }
}
bool PrivateReadSource::renew(std::string_view run,std::string_view request,std::uint32_t pid,
    std::uint64_t issued,std::uint64_t now,bool healthy) noexcept {
    try {
        const std::lock_guard<std::mutex> lock(mutex_);
        if(!source_||!healthy||run!=run_id_.data()||request!=request_id_.data()||pid!=pid_
            || issued>now||now-issued>3||issued>(std::numeric_limits<std::uint64_t>::max)()-5) {
            lease_until_=0; return false;
        }
        lease_until_=issued+5; return true;
    } catch(...) { ++bookkeeping_errors_; return false; }
}
void PrivateReadSource::apply(const ReadCompletion& completion,void* buffer,std::uint64_t now) noexcept {
    const ErrorRestore preserve;
    const auto started=std::chrono::steady_clock::now();
    try {
        std::shared_ptr<const std::vector<unsigned char>> source;
        std::array<unsigned char,32> expected{};
        std::size_t index{};
        {
            const std::lock_guard<std::mutex> lock(mutex_);
            if(!source_) return;
            if(completion.target!=classify_read_target("./win64_save/data004Slot.bin")) { ++ignored_; return; }
            if(!lease_until_||now>lease_until_) { ++rejected_; reason_=PrivateReadReason::lease_unavailable; return; }
            if(!completion.matched||!completion.original_ok||!completion.request_id||!completion.event_sequence||completion.offset
                ||completion.requested_size!=source_->size()||completion.completion_size!=source_->size()) {
                ++rejected_; reason_=PrivateReadReason::scope_mismatch; return;
            }
            for(std::size_t n=0;n<count_;++n) if(records_[n].completion.request_id==completion.request_id) {
                ++rejected_; reason_=PrivateReadReason::duplicate; return;
            }
            if(count_==records_.size()) { ++rejected_; reason_=PrivateReadReason::exhausted; return; }
            index=count_++; records_[index].completion=completion;
            source=source_; expected=expected_;
        }
        PrivateReadRecord record; record.completion=completion;
        const auto before=hash_read_buffer(buffer,completion.completion_size);
        record.before_matches=before.ok && before.bytes==expected;
        bool leased{};
        {
            const auto elapsed=std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now()-started).count();
            const std::lock_guard<std::mutex> lock(mutex_);
            leased=lease_until_ && elapsed>=0 && static_cast<std::uint64_t>(elapsed)<=lease_until_
                && now<=lease_until_-static_cast<std::uint64_t>(elapsed);
        }
        if(!record.before_matches) record.reason=PrivateReadReason::original_mismatch;
        else if(!leased) record.reason=PrivateReadReason::lease_unavailable;
        else if(!writable(buffer,source->size())) record.reason=PrivateReadReason::destination_not_writable;
        else {
            SIZE_T written{};
            const bool copied=WriteProcessMemory(GetCurrentProcess(),buffer,source->data(),source->size(),&written)!=0;
            record.copied_bytes=written;
            const auto after=hash_read_buffer(buffer,completion.completion_size);
            record.after_matches=after.ok && after.bytes==expected;
            record.supplied=copied && written==source->size() && record.after_matches;
            record.reason=!copied||written!=source->size()?PrivateReadReason::copy_failed:
                record.after_matches?PrivateReadReason::supplied:PrivateReadReason::post_copy_mismatch;
        }
        record.in_progress=false;
        {
            const std::lock_guard<std::mutex> lock(mutex_);
            records_[index]=record; reason_=record.reason;
        }
    } catch(...) { ++bookkeeping_errors_; }
}
PrivateReadSnapshot PrivateReadSource::snapshot(std::uint64_t now) const noexcept {
    PrivateReadSnapshot result;
    try {
        const std::lock_guard<std::mutex> lock(mutex_);
        result.enabled=enabled_; result.prepared=source_!=nullptr;
        result.armed=source_ && lease_until_ && now<=lease_until_;
        result.source_bytes=source_?static_cast<std::uint32_t>(source_->size()):0;
        result.request_id=request_id_; result.records=records_; result.count=count_;
        result.ignored=ignored_; result.rejected=rejected_; result.reason=reason_;
    } catch(...) { ++bookkeeping_errors_; result.available=false; }
    result.bookkeeping_errors=bookkeeping_errors_.load(); return result;
}
} // namespace coop
