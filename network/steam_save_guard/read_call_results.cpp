#include "read_call_results.h"
#include <windows.h>

namespace coop {
namespace {
std::atomic<bool> claimed{};
std::array<std::atomic<void*>,read_call_methods> delegates{};
std::array<std::atomic<std::uint64_t>,read_call_methods> calls{};
std::atomic<std::uint64_t> observation_errors{},bookkeeping_errors{};
std::mutex mutex;
ReadCallSnapshot state;
std::size_t event_start{};
struct ErrorRestore{DWORD value=GetLastError();~ErrorRestore(){SetLastError(value);}};
// Windows x64 public RemoteStorageFileReadAsyncComplete_t, tail padding omitted
// from fields but included in the 24-byte SDK buffer size. No handle exported.
struct RemoteReadResult {
    std::uint64_t handle{};
    std::int32_t result{};
    std::uint32_t offset{},bytes{};
    ~RemoteReadResult(){SecureZeroMemory(this,sizeof(*this));}
};
static_assert(sizeof(RemoteReadResult)==remote_read_callback_size);
static_assert(offsetof(RemoteReadResult,result)==8&&offsetof(RemoteReadResult,offset)==12&&offsetof(RemoteReadResult,bytes)==16);
template<typename Function> Function original(std::size_t index){
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(delegates[index].load(std::memory_order_acquire));
}
bool copy(const void* source,void* destination,std::size_t size) noexcept {
    SIZE_T bytes{};
    if(source&&ReadProcessMemory(GetCurrentProcess(),source,destination,size,&bytes)&&bytes==size) return true;
    ++observation_errors;return false;
}
void failure_flag(ReadCallEvent& event,const bool* pointer) noexcept {
    // Inspect bytes, not an invalid C++ bool representation supplied by native
    // memory. A false original result does not make the output meaningful.
    unsigned char value{};
    if(!copy(pointer,&value,1))return;
    if(value>1){++observation_errors;return;}
    event.failed_available=true;event.failed=value!=0;
}
void append(ReadCallEvent event) noexcept {
    if(!event.read.matched) return;
    try {
        const std::lock_guard<std::mutex> lock(mutex);
        ++state.matched_calls[event.method];event.sequence=++state.event_sequence;
        if(state.event_count==state.events.size()){
            event_start=(event_start+1)%state.events.size();--state.event_count;++state.discarded_events;
        }
        state.events[(event_start+state.event_count++)%state.events.size()]=event;
    } catch(...){++bookkeeping_errors;}
}
bool completed(void* self,std::uint64_t handle,bool* failed){
    ++calls[0];
    const auto result=original<bool(*)(void*,std::uint64_t,bool*)>(0)(self,handle,failed);
    const ErrorRestore preserve;
    ReadCallEvent event;event.method=0;event.read=storage_read_call_identity(handle);event.original_result=result;
    if(event.read.matched&&result)failure_flag(event,failed);
    append(event);return result;
}
std::int32_t failure_reason(void* self,std::uint64_t handle){
    ++calls[1];
    const auto result=original<std::int32_t(*)(void*,std::uint64_t)>(1)(self,handle);
    const ErrorRestore preserve;
    ReadCallEvent event;event.method=1;event.read=storage_read_call_identity(handle);event.failure_reason=result;
    append(event);return result;
}
bool call_result(void* self,std::uint64_t handle,void* buffer,std::int32_t size,std::int32_t expected,bool* failed){
    ++calls[2];
    const auto result=original<bool(*)(void*,std::uint64_t,void*,std::int32_t,std::int32_t,bool*)>(2)
        (self,handle,buffer,size,expected,failed);
    const ErrorRestore preserve;
    ReadCallEvent event;event.method=2;event.read=storage_read_call_identity(handle);event.original_result=result;
    event.callback_id=expected;event.callback_size=size;
    if(event.read.matched&&result){
        failure_flag(event,failed);
        if(event.failed_available&&!event.failed&&expected==remote_read_callback&&size==remote_read_callback_size){
            RemoteReadResult payload;
            event.payload_available=copy(buffer,&payload,sizeof(payload));
            if(event.payload_available){
                event.payload_result=payload.result;event.payload_offset=payload.offset;event.payload_bytes=payload.bytes;
                event.payload_handle_matches=payload.handle==handle;
                event.payload_scope_matches=event.payload_handle_matches&&payload.offset==event.read.offset
                    &&payload.bytes<=event.read.requested_size;
            }
        }
    }
    append(event);return result;
}
bool readable(const void* address,std::size_t bytes){
    MEMORY_BASIC_INFORMATION info{};
    if(!address||VirtualQuery(address,&info,sizeof(info))!=sizeof(info)||info.State!=MEM_COMMIT
        ||(info.Protect&(PAGE_NOACCESS|PAGE_GUARD)))return false;
    const auto start=reinterpret_cast<std::uintptr_t>(address),base=reinterpret_cast<std::uintptr_t>(info.BaseAddress);
    return start>=base&&bytes<=info.RegionSize&&start-base<=info.RegionSize-bytes;
}
} // namespace
const std::array<GuardedMethod,read_call_methods>& read_call_methods_table(){
    static const std::array<GuardedMethod,read_call_methods> methods{{
        {11,"IsAPICallCompleted",reinterpret_cast<void*>(&completed)},
        {12,"GetAPICallFailureReason",reinterpret_cast<void*>(&failure_reason)},
        {13,"GetAPICallResult",reinterpret_cast<void*>(&call_result)},
    }};return methods;
}
ReadCallSnapshot read_call_observation() noexcept {
    ReadCallSnapshot result;
    try{
        const std::lock_guard<std::mutex> lock(mutex);result=state;
        for(std::size_t n=0;n<state.event_count;++n)result.events[n]=state.events[(event_start+n)%state.events.size()];
    }catch(...){++bookkeeping_errors;result.available=false;}
    for(std::size_t n=0;n<calls.size();++n)result.calls[n]=calls[n].load();
    result.observation_errors=observation_errors.load();result.bookkeeping_errors=bookkeeping_errors.load();return result;
}
ReadCallObserver::~ReadCallObserver(){detach();}
bool ReadCallObserver::attach(void* object){
    if(table_){error_="already_attached";return false;}
    if(claimed.load()){error_="observation_already_used";return false;}
    if(!readable(object,sizeof(void*))){error_="invalid_interface";return false;}
    auto** table=*reinterpret_cast<void***>(object);
    if(!readable(table,sizeof(void*)*utils_call_prefix_size)){error_="invalid_vtable";return false;}
    const auto& methods=read_call_methods_table();
    for(std::size_t n=0;n<methods.size();++n){
        const auto method=table[methods[n].slot];
        if(!readable(method,1)||method==methods[n].replacement){error_="invalid_result_method";return false;}
        original_[n]=method;
    }
    bool expected=false;
    if(!claimed.compare_exchange_strong(expected,true)){error_="observation_already_used";return false;}
    DWORD previous{};
    if(!VirtualProtect(table,sizeof(void*)*utils_call_prefix_size,PAGE_READWRITE,&previous)){
        claimed.store(false);error_="vtable_protection_failed";return false;
    }
    for(std::size_t n=0;n<methods.size();++n)delegates[n].store(original_[n],std::memory_order_release);
    table_=table;original_protection_=previous;
    for(const auto& method:methods)InterlockedExchangePointer(table_+method.slot,method.replacement);
    DWORD ignored{};protection_restored_=VirtualProtect(table_,sizeof(void*)*utils_call_prefix_size,previous,&ignored)!=0;
    const bool healthy=protection_restored_&&intact();
    error_=!protection_restored_?"vtable_protection_restore_failed":healthy?"ok":"result_integrity_failed";return healthy;
}
bool ReadCallObserver::intact() const {
    if(!protection_restored_||!readable(table_,sizeof(void*)*utils_call_prefix_size))return false;
    for(const auto& method:read_call_methods_table())if(table_[method.slot]!=method.replacement)return false;
    return true;
}
void ReadCallObserver::detach(){
    if(!readable(table_,sizeof(void*)*utils_call_prefix_size)){table_=nullptr;return;}
    DWORD previous{};if(!VirtualProtect(table_,sizeof(void*)*utils_call_prefix_size,PAGE_READWRITE,&previous))return;
    const auto& methods=read_call_methods_table();
    for(std::size_t n=0;n<methods.size();++n)InterlockedCompareExchangePointer(table_+methods[n].slot,original_[n],methods[n].replacement);
    DWORD ignored{};VirtualProtect(table_,sizeof(void*)*utils_call_prefix_size,original_protection_,&ignored);
    table_=nullptr;protection_restored_=false;
}
} // namespace coop
