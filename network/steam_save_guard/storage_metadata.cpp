#include "storage_metadata.h"
#include <windows.h>
#include <limits>

namespace coop {
namespace {
std::atomic<bool> claimed{};
std::array<std::atomic<void*>,metadata_methods> delegates{};
std::array<std::atomic<std::uint64_t>,metadata_methods> calls{};
std::atomic<std::uint64_t> observation_errors{}, bookkeeping_errors{};
std::mutex mutex;
MetadataSnapshot state;
std::size_t event_start{};
struct ErrorRestore { DWORD value=GetLastError(); ~ErrorRestore(){SetLastError(value);} };

template<typename Function> Function original(std::size_t index) {
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(delegates[index].load(std::memory_order_acquire));
}
template<typename Value> bool copy_output(const Value* pointer,Value& value) noexcept {
    SIZE_T count{};
    const bool ok=pointer && ReadProcessMemory(GetCurrentProcess(),pointer,&value,sizeof(value),&count)
        && count==sizeof(value);
    if(!ok) ++observation_errors;
    return ok;
}
std::size_t target(const char* name) noexcept {
    const ErrorRestore preserve;
    struct Temporary {char bytes[64]{};~Temporary(){SecureZeroMemory(bytes,sizeof(bytes));}} copy;
    if(!name) {++observation_errors;return unknown_read_target;}
    const auto address=reinterpret_cast<std::uintptr_t>(name);
    for(std::size_t n=0;n<sizeof(copy.bytes);++n) {
        SIZE_T count{};
        if(n>(std::numeric_limits<std::uintptr_t>::max)()-address
            || !ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<const void*>(address+n),copy.bytes+n,1,&count)
            || count!=1) {++observation_errors;return unknown_read_target;}
        if(copy.bytes[n]=='\0') return classify_metadata_target(std::string_view(copy.bytes,n));
    }
    ++observation_errors;return unknown_read_target;
}
void append(MetadataEvent event) noexcept {
    try {
        const std::lock_guard<std::mutex> lock(mutex);
        ++state.targets[event.target][event.method];
        event.sequence=++state.event_sequence;
        if(state.event_count==state.events.size()) {
            event_start=(event_start+1)%state.events.size();--state.event_count;++state.discarded_events;
        }
        state.events[(event_start+state.event_count++)%state.events.size()]=event;
    } catch(...) {++bookkeeping_errors;}
}
template<typename Value> Value named(std::size_t method,void* self,const char* name) {
    ++calls[method];
    const auto file=target(name);
    const auto result=original<Value(*)(void*,const char*)>(method)(self,name);
    const ErrorRestore preserve;
    MetadataEvent event;event.method=method;event.target=file;
    event.value=static_cast<std::int64_t>(result);event.has_value=true;
    append(event);return result;
}
bool exists(void* self,const char* name){return named<bool>(0,self,name);}
bool persisted(void* self,const char* name){return named<bool>(1,self,name);}
std::int32_t size(void* self,const char* name){return named<std::int32_t>(2,self,name);}
std::int64_t timestamp(void* self,const char* name){return named<std::int64_t>(3,self,name);}
std::uint32_t platforms(void* self,const char* name){return named<std::uint32_t>(4,self,name);}
template<typename Value> Value global(std::size_t method,void* self) {
    ++calls[method];
    const auto result=original<Value(*)(void*)>(method)(self);
    const ErrorRestore preserve;
    MetadataEvent event;event.method=method;event.target=global_metadata_target;
    event.value=static_cast<std::int64_t>(result);event.has_value=true;
    append(event);return result;
}
std::int32_t count(void* self){return global<std::int32_t>(5,self);}
const char* name_size(void* self,std::int32_t index,std::int32_t* size_out) {
    ++calls[6];
    const auto result=original<const char*(*)(void*,std::int32_t,std::int32_t*)>(6)(self,index,size_out);
    const ErrorRestore preserve;
    MetadataEvent event;event.method=6;event.index=index;event.name_returned=result!=nullptr;
    if(result) {
        event.target=target(result);
        std::int32_t bytes{};event.has_value=copy_output(size_out,bytes);event.value=bytes;
    }
    append(event);return result;
}
bool quota(void* self,std::uint64_t* total,std::uint64_t* available) {
    ++calls[7];
    const auto result=original<bool(*)(void*,std::uint64_t*,std::uint64_t*)>(7)(self,total,available);
    const ErrorRestore preserve;
    MetadataEvent event;event.method=7;event.target=global_metadata_target;event.value=result;event.has_value=true;
    if(result) {
        event.has_unsigned_value=copy_output(total,event.unsigned_value);
        event.has_secondary=copy_output(available,event.secondary);
    }
    append(event);return result;
}
bool account_cloud(void* self){return global<bool>(8,self);}
bool app_cloud(void* self){return global<bool>(9,self);}
bool readable(const void* address,std::size_t bytes) {
    MEMORY_BASIC_INFORMATION info{};
    if(!address||VirtualQuery(address,&info,sizeof(info))!=sizeof(info)||info.State!=MEM_COMMIT
        ||(info.Protect&(PAGE_NOACCESS|PAGE_GUARD))) return false;
    const auto start=reinterpret_cast<std::uintptr_t>(address),base=reinterpret_cast<std::uintptr_t>(info.BaseAddress);
    return start>=base&&bytes<=info.RegionSize&&start-base<=info.RegionSize-bytes;
}
} // namespace

std::size_t classify_metadata_target(std::string_view name) {
    // Steam documents case-insensitive names and lowercases enumerated names.
    // Only match the fixed known namespace; never rewrite arguments or resolve
    // traversal, repeated separators, backslashes or an arbitrary prefix.
    if(name.substr(0,2)=="./") name.remove_prefix(2);
    auto lower=[](char c){return c>='A'&&c<='Z'?static_cast<char>(c-'A'+'a'):c;};
    for(std::size_t t=0;t<known_read_targets;++t) {
        const std::string_view known(known_read_target(t)+2);
        if(name.size()!=known.size()) continue;
        bool same=true;
        for(std::size_t n=0;n<name.size();++n) if(lower(name[n])!=lower(known[n])) {same=false;break;}
        if(same) return t;
    }
    return unknown_read_target;
}

const std::array<GuardedMethod,metadata_methods>& storage_metadata_methods() {
    static const std::array<GuardedMethod,metadata_methods> methods{{
        {13,"FileExists",reinterpret_cast<void*>(&exists)},
        {14,"FilePersisted",reinterpret_cast<void*>(&persisted)},
        {15,"GetFileSize",reinterpret_cast<void*>(&size)},
        {16,"GetFileTimestamp",reinterpret_cast<void*>(&timestamp)},
        {17,"GetSyncPlatforms",reinterpret_cast<void*>(&platforms)},
        {18,"GetFileCount",reinterpret_cast<void*>(&count)},
        {19,"GetFileNameAndSize",reinterpret_cast<void*>(&name_size)},
        {20,"GetQuota",reinterpret_cast<void*>(&quota)},
        {21,"IsCloudEnabledForAccount",reinterpret_cast<void*>(&account_cloud)},
        {22,"IsCloudEnabledForApp",reinterpret_cast<void*>(&app_cloud)},
    }};return methods;
}
MetadataSnapshot storage_metadata_observation() noexcept {
    MetadataSnapshot result;
    try {
        const std::lock_guard<std::mutex> lock(mutex);
        result=state;
        for(std::size_t n=0;n<state.event_count;++n) result.events[n]=state.events[(event_start+n)%state.events.size()];
    } catch(...) {++bookkeeping_errors;result.available=false;}
    for(std::size_t n=0;n<calls.size();++n) result.calls[n]=calls[n].load();
    result.observation_errors=observation_errors.load();result.bookkeeping_errors=bookkeeping_errors.load();
    return result;
}
StorageMetadataObserver::~StorageMetadataObserver(){detach();}
bool StorageMetadataObserver::attach(void* object) {
    if(table_){error_="already_attached";return false;}
    if(claimed.load()){error_="observation_already_used";return false;}
    if(!readable(object,sizeof(void*))){error_="invalid_interface";return false;}
    auto** table=*reinterpret_cast<void***>(object);
    if(!readable(table,sizeof(void*)*metadata_prefix_size)){error_="invalid_vtable";return false;}
    const auto& methods=storage_metadata_methods();
    for(std::size_t n=0;n<methods.size();++n) {
        const auto method=table[methods[n].slot];
        if(!readable(method,1)||method==methods[n].replacement){error_="invalid_metadata_method";return false;}
        original_[n]=method;
    }
    bool expected=false;
    if(!claimed.compare_exchange_strong(expected,true)){error_="observation_already_used";return false;}
    DWORD previous{};
    if(!VirtualProtect(table,sizeof(void*)*metadata_prefix_size,PAGE_READWRITE,&previous)) {
        claimed.store(false);error_="vtable_protection_failed";return false;
    }
    for(std::size_t n=0;n<methods.size();++n)delegates[n].store(original_[n],std::memory_order_release);
    table_=table;original_protection_=previous;
    for(const auto& method:methods)InterlockedExchangePointer(table_+method.slot,method.replacement);
    DWORD ignored{};
    protection_restored_=VirtualProtect(table_,sizeof(void*)*metadata_prefix_size,previous,&ignored)!=0;
    const bool healthy=protection_restored_&&intact();
    error_=!protection_restored_?"vtable_protection_restore_failed":healthy?"ok":"metadata_integrity_failed";
    return healthy;
}
bool StorageMetadataObserver::intact() const {
    if(!protection_restored_||!readable(table_,sizeof(void*)*metadata_prefix_size))return false;
    for(const auto& method:storage_metadata_methods())if(table_[method.slot]!=method.replacement)return false;
    return true;
}
void StorageMetadataObserver::detach() {
    if(!readable(table_,sizeof(void*)*metadata_prefix_size)){table_=nullptr;return;}
    DWORD previous{};
    if(!VirtualProtect(table_,sizeof(void*)*metadata_prefix_size,PAGE_READWRITE,&previous))return;
    const auto& methods=storage_metadata_methods();
    for(std::size_t n=0;n<methods.size();++n)
        InterlockedCompareExchangePointer(table_+methods[n].slot,original_[n],methods[n].replacement);
    DWORD ignored{};VirtualProtect(table_,sizeof(void*)*metadata_prefix_size,original_protection_,&ignored);
    table_=nullptr;protection_restored_=false;
}
} // namespace coop
