#include "read_callbacks.h"
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <vector>

namespace {
void check(bool v,const char* why){if(!v){std::fprintf(stderr,"%s\n",why);std::exit(1);}}
struct Interface{void** table;};
struct Callback{void** table;unsigned char flags{};std::int32_t id=1332;int tag{};bool destroy{};};
static_assert(offsetof(Callback,id)==12);
struct Payload{std::uint64_t handle;std::int32_t result;std::uint32_t offset,bytes;};
static_assert(sizeof(Payload)==24);
using Register=void(*)(void*,std::uint64_t);
using Run=void(*)(void*,void*,bool,std::uint64_t);
using Single=void(*)(void*,void*);
using Request=std::uint64_t(*)(void*,const char*,std::uint32_t,std::uint32_t);
using Finish=bool(*)(void*,std::uint64_t,void*,std::uint32_t);
Interface* storage{};
std::atomic<std::uint64_t> next_handle{0xfedcba9876543200ULL},registrations{},unregistrations{};
std::array<std::atomic<unsigned>,5> deliveries{};
void** import_slots{};
template<typename Function>Function fn(void* pointer){
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(pointer);
}
bool writer(void*,const char*,const void*,std::int32_t){check(false,"writer escaped barrier");return true;}
std::uint64_t request(void* self,const char* name,std::uint32_t offset,std::uint32_t size){
    check(self==storage&&name&&std::strcmp(name,"./win64_save/data004Slot.bin")==0&&offset==0&&size==32,"read args changed");return ++next_handle;
}
bool finish(void* self,std::uint64_t,void* output,std::uint32_t size){check(self==storage&&!output&&size==32,"completion changed");return true;}
void register_native(void*,std::uint64_t){
    check(GetLastError()==0x11223344UL,"registration input error changed");++registrations;SetLastError(0x55667788UL);
}
void unregister_native(void*,std::uint64_t){++unregistrations;SetLastError(0x77778888UL);}
void foreign_native(void*,std::uint64_t){check(false,"foreign import called");}
std::int32_t get_size(void*){SetLastError(0xaaaaaaaaUL);return 24;}
template<int Index>void deliver(void* self,void* data,bool failed,std::uint64_t handle){
    check(GetLastError()==0x12344321UL,"callback input error changed");
    auto* cb=static_cast<Callback*>(self);check(cb->tag==Index,"class delegated to wrong original");
    ++deliveries[Index];
    if(!failed){
        const auto* p=static_cast<Payload*>(data);check(p&&p->handle==handle&&p->offset==0&&p->bytes==32,"payload changed");
        check(fn<Finish>(storage->table[4])(storage,handle,nullptr,32),"completion result changed");
    }
    if(cb->destroy){
        fn<Register>(import_slots[1])(self,handle);
        VirtualFree(data,0,MEM_RELEASE);VirtualFree(self,0,MEM_RELEASE);
    }
    SetLastError(0x88776655UL);
}
template<int Index>void single(void* self,void* data){deliver<Index>(self,data,false,static_cast<Payload*>(data)->handle);}
std::array<std::array<void*,3>,5> originals{{
    {{reinterpret_cast<void*>(&deliver<0>),reinterpret_cast<void*>(&single<0>),reinterpret_cast<void*>(&get_size)}},
    {{reinterpret_cast<void*>(&deliver<1>),reinterpret_cast<void*>(&single<1>),reinterpret_cast<void*>(&get_size)}},
    {{reinterpret_cast<void*>(&deliver<2>),reinterpret_cast<void*>(&single<2>),reinterpret_cast<void*>(&get_size)}},
    {{reinterpret_cast<void*>(&deliver<3>),reinterpret_cast<void*>(&single<3>),reinterpret_cast<void*>(&get_size)}},
    {{reinterpret_cast<void*>(&deliver<4>),reinterpret_cast<void*>(&single<4>),reinterpret_cast<void*>(&get_size)}},
}};
void** readonly_table(const void* original,std::size_t bytes){
    auto** value=static_cast<void**>(VirtualAlloc(nullptr,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
    check(value!=nullptr,"table allocation failed");std::memcpy(value,original,bytes);DWORD old{};
    check(VirtualProtect(value,4096,PAGE_READONLY,&old)!=0,"read-only setup failed");return value;
}
std::uint64_t issue(){return fn<Request>(storage->table[3])(storage,"./win64_save/data004Slot.bin",0,32);}
void reg(void* self,std::uint64_t handle){SetLastError(0x11223344UL);fn<Register>(import_slots[0])(self,handle);check(GetLastError()==0x55667788UL,"registration output error changed");}
coop::ReadCallbackEvent last(){const auto s=coop::read_callback_observation();check(s.event_count>0,"missing event");return s.events[s.event_count-1];}
} // namespace
int main(){
    std::array<void*,13> storage_original{};storage_original.fill(reinterpret_cast<void*>(&writer));
    storage_original[3]=reinterpret_cast<void*>(&request);storage_original[4]=reinterpret_cast<void*>(&finish);
    auto** storage_table=readonly_table(storage_original.data(),sizeof(storage_original));Interface remote{storage_table};storage=&remote;
    coop::StorageGuard writers;coop::StorageReadObserver reads;check(writers.attach(storage)&&reads.attach(storage),"storage setup failed");
    std::array<void*,2> imports{{reinterpret_cast<void*>(&register_native),reinterpret_cast<void*>(&unregister_native)}};
    import_slots=readonly_table(imports.data(),sizeof(imports));
    coop::ReadCallbackObserver observer;
    const coop::ReadCallbackImports config{import_slots,import_slots+1,imports[0],imports[1],imports[0],imports[1],GetModuleHandleW(nullptr)};
    check(observer.attach(config)&&observer.intact()&&writers.intact()&&reads.intact(),"callback imports not attached");
    {coop::ReadCallbackObserver other;check(!other.attach(config),"second observer accepted");}
    check(observer.intact(),"rejected observer destructor detached owner");
    reg(reinterpret_cast<void*>(std::uintptr_t{1}),123);
    check(coop::read_callback_observation().event_sequence==0&&coop::read_callback_observation().observation_errors==0,"unknown registration read callback memory");
    std::array<void**,5> tables{};
    for(std::size_t n=0;n<tables.size();++n)tables[n]=readonly_table(originals[n].data(),sizeof(originals[n]));
    Callback first{tables[0],0,1332,0,false};const auto first_handle=issue();reg(&first,first_handle);
    auto event=last();check(event.method==0&&event.read.request_id==1&&event.metadata_available&&event.callback_id==1332
        &&event.callback_size==24&&event.class_observed&&event.returned,"known registration not observed");
    Payload p{first_handle,1,0,32};SetLastError(0x12344321UL);fn<Run>(first.table[coop::callback_call_slot])(&first,&p,false,first_handle);
    event=last();check(GetLastError()==0x88776655UL&&event.method==3&&event.returned&&event.payload_available
        &&event.scope_matches&&event.handle_matches&&!event.io_failure&&event.payload_result==1&&!event.read.completed,
        "native callback payload/error/original completion not preserved");
    check(coop::storage_read_call_identity(first_handle).completed,"original callback did not complete read");
    const auto single_handle=issue();reg(&first,single_handle);Payload ps{single_handle,1,0,32};
    SetLastError(0x12344321UL);fn<Single>(first.table[coop::callback_single_slot])(&first,&ps);
    check(last().method==2&&last().scope_matches&&last().returned,"single callback not forwarded");
    const auto failed_handle=issue();reg(&first,failed_handle);
    SetLastError(0x12344321UL);fn<Run>(first.table[coop::callback_call_slot])(&first,reinterpret_cast<void*>(std::uintptr_t{1}),true,failed_handle);
    check(last().io_failure&&!last().payload_available&&last().returned,"failed callback inspected opaque payload");
    auto* dying=static_cast<Callback*>(VirtualAlloc(nullptr,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
    auto* dying_payload=static_cast<Payload*>(VirtualAlloc(nullptr,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
    check(dying&&dying_payload,"dying fixture allocation failed");
    *dying={tables[0],0,1332,0,true};const auto dying_handle=issue();*dying_payload={dying_handle,1,0,32};reg(dying,dying_handle);
    SetLastError(0x12344321UL);fn<Run>(dying->table[coop::callback_call_slot])(dying,dying_payload,false,dying_handle);
    check(GetLastError()==0x88776655UL&&last().scope_matches&&last().returned
        &&coop::read_callback_observation().observation_errors==0,"freed callback/payload read after original");
    for(int n=1;n<5;++n){
        Callback cb{tables[n],0,1332,n,false};const auto h=issue();reg(&cb,h);
        check(last().class_observed==(n<4),"class capacity not explicit");Payload value{h,1,0,32};
        SetLastError(0x12344321UL);fn<Run>(cb.table[coop::callback_call_slot])(&cb,&value,false,h);check(deliveries[n]==1,"class original lost");
    }
    auto snapshot=coop::read_callback_observation();check(snapshot.classes==4&&snapshot.classes_intact&&snapshot.unsupported_classes==1,"class accounting wrong");
    const auto active_handle=issue();reg(&first,active_handle);
    std::vector<std::thread> threads;
    for(int n=0;n<4;++n)threads.emplace_back([&]{for(int i=0;i<1000;++i)reg(&first,active_handle);});
    for(auto& t:threads)t.join();snapshot=coop::read_callback_observation();
    check(snapshot.event_count==coop::read_callback_events&&snapshot.discarded_events==snapshot.event_sequence-snapshot.event_count
        &&snapshot.observation_errors==0&&snapshot.bookkeeping_errors==0,"concurrency/history/errors wrong");
    for(std::size_t n=1;n<snapshot.event_count;++n)check(snapshot.events[n].sequence==snapshot.events[n-1].sequence+1,"event order wrong");
    snapshot.events[0].returned=false;check(coop::read_callback_observation().events[0].returned,"snapshot aliases state");
    const auto cached_register=fn<Register>(import_slots[0]);const auto cached_run=fn<Run>(tables[0][coop::callback_call_slot]);
    DWORD previous{};check(VirtualProtect(import_slots,sizeof(imports),PAGE_READWRITE,&previous)!=0,"tamper setup failed");
    import_slots[1]=reinterpret_cast<void*>(&foreign_native);DWORD ignored{};
    check(VirtualProtect(import_slots,sizeof(imports),previous,&ignored)!=0,"tamper restore failed");
    check(!observer.intact(),"import tamper remained healthy");observer.detach();
    check(import_slots[0]==imports[0]&&import_slots[1]==reinterpret_cast<void*>(&foreign_native),"import detach ownership wrong");
    for(std::size_t n=0;n<tables.size();++n)check(std::memcmp(tables[n],originals[n].data(),sizeof(originals[n]))==0,"class not restored");
    SetLastError(0x11223344UL);cached_register(&first,active_handle);Payload late{active_handle,1,0,32};
    SetLastError(0x12344321UL);cached_run(&first,&late,false,active_handle);
    check(coop::read_callback_observation().event_sequence==snapshot.event_sequence,"late detached call resumed observation");
    reads.detach();writers.detach();
    check(std::memcmp(storage_table,storage_original.data(),sizeof(storage_original))==0,"storage barrier not restored");
    MEMORY_BASIC_INFORMATION protection{};VirtualQuery(import_slots,&protection,sizeof(protection));check(protection.Protect==PAGE_READONLY,"import page left writable");
    for(auto value:tables)VirtualFree(value,0,MEM_RELEASE);VirtualFree(import_slots,0,MEM_RELEASE);VirtualFree(storage_table,0,MEM_RELEASE);
    std::puts("Read callback registration/dispatch, class scope, lifetime after self-free, concurrency and owned restoration verified");
}
