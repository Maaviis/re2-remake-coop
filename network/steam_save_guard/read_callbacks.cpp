#include "read_callbacks.h"
#include <windows.h>

namespace coop {
namespace {
struct ErrorRestore{DWORD value=GetLastError();~ErrorRestore(){SetLastError(value);}};
struct Prefix{void** table{};unsigned char flags{};std::int32_t callback{};};
static_assert(sizeof(Prefix)==16&&offsetof(Prefix,callback)==12);
struct Payload{
    std::uint64_t handle{};std::int32_t result{};std::uint32_t offset{},bytes{};
    ~Payload(){SecureZeroMemory(this,sizeof(*this));}
};
static_assert(sizeof(Payload)==24&&offsetof(Payload,result)==8&&offsetof(Payload,offset)==12&&offsetof(Payload,bytes)==16);
struct ClassHook{
    void** table{};
    std::array<std::atomic<void*>,2> originals{};
    ImportPatch single,call;
};
struct Context{
    std::atomic<bool> claimed{},enabled{};
    std::atomic<void*> register_export{},unregister_export{};
    void* code_owner{};
    std::array<std::atomic<std::uint64_t>,read_callback_methods> calls{};
    std::atomic<std::uint64_t> errors{},bookkeeping{},unsupported{};
    std::mutex events_mutex,classes_mutex;
    ReadCallbackSnapshot state;
    std::size_t event_start{},class_count{};
    std::array<ClassHook,read_callback_classes> classes;
};
// Process-lifetime delegates outlive observer detach and cached forwarding calls.
Context& context(){static auto* value=new Context;return *value;}
template<typename Function>Function function(void* pointer){
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(pointer);
}
bool copy(const void* source,void* destination,std::size_t bytes){
    SIZE_T read{};
    if(source&&ReadProcessMemory(GetCurrentProcess(),source,destination,bytes,&read)&&read==bytes)return true;
    ++context().errors;return false;
}
bool code_owned(void* pointer){
    HMODULE owner{};
    return pointer&&GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(pointer),&owner)&&owner==context().code_owner;
}
void append(ReadCallbackEvent event) noexcept{
    if(!event.read.matched)return;
    try{
        auto& c=context();const std::lock_guard<std::mutex> lock(c.events_mutex);
        ++c.state.matched_calls[event.method];event.sequence=++c.state.event_sequence;
        if(c.state.event_count==c.state.events.size()){
            c.event_start=(c.event_start+1)%c.state.events.size();--c.state.event_count;++c.state.discarded_events;
        }
        c.state.events[(c.event_start+c.state.event_count++)%c.state.events.size()]=event;
    }catch(...){++context().bookkeeping;}
}
void payload_fields(ReadCallbackEvent& event,const Payload& value,std::uint64_t argument){
    event.payload_available=true;event.payload_result=value.result;event.payload_offset=value.offset;event.payload_bytes=value.bytes;
    event.handle_matches=value.handle==argument;
    event.scope_matches=event.handle_matches&&value.offset==event.read.offset&&value.bytes<=event.read.requested_size;
}
template<std::size_t Index>void single_run(void* self,void* data){
    auto& c=context();const auto original=function<void(*)(void*,void*)>(c.classes[Index].originals[0].load(std::memory_order_acquire));
    ReadCallbackEvent event;event.method=2;
    if(c.enabled.load(std::memory_order_acquire)){
        const ErrorRestore preserve;++c.calls[2];
        try{
            Prefix prefix;
            if(copy(self,&prefix,sizeof(prefix))&&prefix.table==c.classes[Index].table&&prefix.callback==1332){
                Payload value;
                if(copy(data,&value,sizeof(value))){
                    event.read=storage_read_call_identity(value.handle);
                    event.callback_id=1332;event.callback_size=24;event.metadata_available=true;event.class_observed=true;
                    if(event.read.matched)payload_fields(event,value,value.handle);
                }
            }
        }catch(...){++c.bookkeeping;}
    }
    original(self,data);
    const ErrorRestore preserve;event.returned=true;append(event);
}
template<std::size_t Index>void call_run(void* self,void* data,bool failed,std::uint64_t handle){
    auto& c=context();const auto original=function<void(*)(void*,void*,bool,std::uint64_t)>(c.classes[Index].originals[1].load(std::memory_order_acquire));
    ReadCallbackEvent event;event.method=3;event.io_failure=failed;
    if(c.enabled.load(std::memory_order_acquire)){
        const ErrorRestore preserve;++c.calls[3];
        try{
            event.read=storage_read_call_identity(handle);
            if(event.read.matched){
                Prefix prefix;
                if(copy(self,&prefix,sizeof(prefix))){
                    event.callback_id=prefix.callback;event.callback_size=24;event.metadata_available=true;
                    event.class_observed=prefix.table==c.classes[Index].table;
                    if(event.class_observed&&prefix.callback==1332&&!failed){Payload value;if(copy(data,&value,sizeof(value)))payload_fields(event,value,handle);}
                }
            }
        }catch(...){++c.bookkeeping;}
    }
    // The original may destroy self and data. Everything below uses primitives.
    original(self,data,failed,handle);
    const ErrorRestore preserve;event.returned=true;append(event);
}
struct Wrappers{void* single;void* call;};
const std::array<Wrappers,read_callback_classes> wrappers{{
    {reinterpret_cast<void*>(&single_run<0>),reinterpret_cast<void*>(&call_run<0>)},
    {reinterpret_cast<void*>(&single_run<1>),reinterpret_cast<void*>(&call_run<1>)},
    {reinterpret_cast<void*>(&single_run<2>),reinterpret_cast<void*>(&call_run<2>)},
    {reinterpret_cast<void*>(&single_run<3>),reinterpret_cast<void*>(&call_run<3>)},
}};
bool observe_class(void** table,void* first,void* second){
    auto& c=context();const std::lock_guard<std::mutex> lock(c.classes_mutex);
    if(!c.enabled.load(std::memory_order_acquire))return false;
    for(std::size_t n=0;n<c.class_count;++n)if(c.classes[n].table==table)return c.classes[n].single.intact()&&c.classes[n].call.intact();
    if(c.class_count==c.classes.size()){++c.unsupported;return false;}
    const auto index=c.class_count++;auto& entry=c.classes[index];
    entry.table=table;entry.originals[0].store(first,std::memory_order_release);entry.originals[1].store(second,std::memory_order_release);
    if(!entry.single.attach(table+callback_single_slot,first,wrappers[index].single))return false;
    if(!entry.call.attach(table+callback_call_slot,second,wrappers[index].call)){entry.single.detach();return false;}
    return true;
}
void inspect_registration(ReadCallbackEvent& event,void* self){
    Prefix prefix;
    if(!copy(self,&prefix,sizeof(prefix)))return;
    event.callback_id=prefix.callback;
    if(prefix.callback!=1332)return;
    void* methods[3]{};
    if(!copy(prefix.table,methods,sizeof(methods)))return;
    auto& c=context();bool already=false;
    {
        const std::lock_guard<std::mutex> lock(c.classes_mutex);
        for(std::size_t n=0;n<c.class_count;++n)if(c.classes[n].table==prefix.table){already=true;break;}
    }
    if(!code_owned(methods[callback_size_slot])||(!already&&(!code_owned(methods[callback_single_slot])||!code_owned(methods[callback_call_slot]))))return;
    // Published CCallbackBase getter; no registration or dispatch is performed.
    event.callback_size=function<std::int32_t(*)(void*)>(methods[callback_size_slot])(self);
    event.metadata_available=true;
    if(event.callback_size==24)event.class_observed=observe_class(prefix.table,methods[callback_single_slot],methods[callback_call_slot]);
}
void register_result(void* self,std::uint64_t handle){
    auto& c=context();ReadCallbackEvent event;event.method=0;
    if(c.enabled.load(std::memory_order_acquire)){
        const ErrorRestore preserve;++c.calls[0];
        try{event.read=storage_read_call_identity(handle);if(event.read.matched)inspect_registration(event,self);}
        catch(...){++c.bookkeeping;}
    }
    function<void(*)(void*,std::uint64_t)>(c.register_export.load(std::memory_order_acquire))(self,handle);
    const ErrorRestore preserve;event.returned=true;append(event);
}
void unregister_result(void* self,std::uint64_t handle){
    auto& c=context();ReadCallbackEvent event;event.method=1;
    if(c.enabled.load(std::memory_order_acquire)){
        const ErrorRestore preserve;++c.calls[1];event.read=storage_read_call_identity(handle);
    }
    function<void(*)(void*,std::uint64_t)>(c.unregister_export.load(std::memory_order_acquire))(self,handle);
    const ErrorRestore preserve;event.returned=true;append(event);
}
} // namespace
const char* read_callback_method_name(std::size_t method){
    constexpr const char* names[]{"register_result","unregister_result","run_single","run_call_result"};
    return method<read_callback_methods?names[method]:"unsupported";
}
ReadCallbackSnapshot read_callback_observation() noexcept{
    ReadCallbackSnapshot result;auto& c=context();
    try{
        {const std::lock_guard<std::mutex> lock(c.events_mutex);result=c.state;
            for(std::size_t n=0;n<c.state.event_count;++n)result.events[n]=c.state.events[(c.event_start+n)%c.state.events.size()];}
        {const std::lock_guard<std::mutex> lock(c.classes_mutex);result.classes=c.class_count;
            for(std::size_t n=0;n<c.class_count;++n)if(!c.classes[n].single.intact()||!c.classes[n].call.intact())result.classes_intact=false;}
    }catch(...){++c.bookkeeping;result.available=false;}
    for(std::size_t n=0;n<c.calls.size();++n)result.calls[n]=c.calls[n].load();
    result.unsupported_classes=c.unsupported.load();result.observation_errors=c.errors.load();result.bookkeeping_errors=c.bookkeeping.load();return result;
}
ReadCallbackObserver::~ReadCallbackObserver(){detach();}
bool ReadCallbackObserver::attach(const ReadCallbackImports& imports){
    if(attempted_){error_="observation_already_used";return false;}attempted_=true;
    auto& c=context();bool expected=false;
    if(!imports.register_slot||!imports.unregister_slot||imports.register_slot==imports.unregister_slot
        ||!imports.register_export||!imports.unregister_export||!imports.callback_code_owner
        ||!c.claimed.compare_exchange_strong(expected,true)){error_="invalid_or_used_imports";return false;}
    owns_=true;c.code_owner=imports.callback_code_owner;c.register_export.store(imports.register_export,std::memory_order_release);
    c.unregister_export.store(imports.unregister_export,std::memory_order_release);c.enabled.store(true,std::memory_order_release);
    if(!register_patch_.attach(imports.register_slot,imports.register_previous,reinterpret_cast<void*>(&register_result))){
        c.enabled=false;error_=register_patch_.error();return false;}
    if(!unregister_patch_.attach(imports.unregister_slot,imports.unregister_previous,reinterpret_cast<void*>(&unregister_result))){
        c.enabled=false;register_patch_.detach();error_=unregister_patch_.error();return false;}
    error_="ok";return true;
}
bool ReadCallbackObserver::intact() const{
    if(!register_patch_.intact()||!unregister_patch_.intact()||!context().enabled.load())return false;
    try{auto& c=context();const std::lock_guard<std::mutex> lock(c.classes_mutex);
        for(std::size_t n=0;n<c.class_count;++n)if(!c.classes[n].single.intact()||!c.classes[n].call.intact())return false;
    }catch(...){++context().bookkeeping;return false;}return true;
}
void ReadCallbackObserver::detach(){
    if(!owns_)return;auto& c=context();c.enabled.store(false,std::memory_order_release);
    register_patch_.detach();unregister_patch_.detach();
    try{const std::lock_guard<std::mutex> lock(c.classes_mutex);
        for(std::size_t n=0;n<c.class_count;++n){c.classes[n].single.detach();c.classes[n].call.detach();}
    }catch(...){++c.bookkeeping;}
}
} // namespace coop
