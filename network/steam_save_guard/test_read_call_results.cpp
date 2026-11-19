#include "read_call_results.h"
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <vector>

namespace {
struct Interface{void** table;};
struct Result{std::uint64_t handle;std::int32_t result;std::uint32_t offset,bytes;};
static_assert(sizeof(Result)==24);
constexpr std::uint64_t handle=0xfedcba9876543210ULL;
constexpr char file[]="./win64_save/data004Slot.bin";
void* storage_self{};void* utils_self{};
std::atomic<bool> ready{},io_failed{};
int mode{};
void check(bool value,const char* why){if(!value){std::fprintf(stderr,"%s\n",why);std::exit(1);}}
bool writer(void*,const char*,const void*,std::int32_t){check(false,"writer escaped barrier");return true;}
std::uint64_t request(void* self,const char* name,std::uint32_t offset,std::uint32_t size){
    check(self==storage_self&&name&&std::strcmp(name,file)==0&&offset==7&&size==100,"storage request changed");return handle;
}
bool finish(void* self,std::uint64_t id,void* buffer,std::uint32_t size){
    check(self==storage_self&&id==handle&&buffer==nullptr&&size==100,"storage completion changed");return true;
}
bool completed(void* self,std::uint64_t id,bool* failed){
    check(self==utils_self&&(id==handle||id==handle+1),"completion receiver/64-bit handle changed");
    if(ready.load()&&reinterpret_cast<std::uintptr_t>(failed)!=1&&failed)*failed=io_failed.load();
    SetLastError(0x12345678UL);return ready.load();
}
std::int32_t reason(void* self,std::uint64_t id){
    check(self==utils_self&&id==handle,"failure receiver/handle changed");SetLastError(0x87654321UL);return -1;
}
bool result(void* self,std::uint64_t id,void* output,std::int32_t size,std::int32_t expected,bool* failed){
    check(self==utils_self&&(id==handle||id==handle+1),"result receiver/64-bit handle changed");
    SetLastError(0xabcdef12UL);
    if(size==-7){check(expected==-1332&&output==nullptr&&failed==nullptr,"negative result arguments changed");return false;}
    check(size==24,"callback size changed");
    if(id==handle+1)return true; // Unknown calls must not trigger output inspection.
    if(mode==6)return true; // Invalid native bool representation remains untouched.
    if(failed)*failed=io_failed.load();
    if(mode==5)return true; // Opaque original output pointer remains untouched.
    if(output){
        Result payload{handle,1,7,100};
        if(mode==1)payload.handle=handle+1;
        if(mode==2)payload.offset=8;
        if(mode==3)payload.bytes=101;
        std::memcpy(output,&payload,sizeof(payload));
    }
    return true;
}
template<typename Function>Function fn(void* address){
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(address);
}
void** table(const void* data,std::size_t bytes){
    auto** value=static_cast<void**>(VirtualAlloc(nullptr,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
    check(value!=nullptr,"table allocation failed");std::memcpy(value,data,bytes);DWORD previous{};
    check(VirtualProtect(value,4096,PAGE_READONLY,&previous)!=0,"table protection failed");return value;
}
coop::ReadCallEvent last(){const auto s=coop::read_call_observation();check(s.event_count>0,"missing event");return s.events[s.event_count-1];}
} // namespace
int main(){
    using Request=std::uint64_t(*)(void*,const char*,std::uint32_t,std::uint32_t);
    using Finish=bool(*)(void*,std::uint64_t,void*,std::uint32_t);
    using Completed=bool(*)(void*,std::uint64_t,bool*);
    using Reason=std::int32_t(*)(void*,std::uint64_t);
    using GetResult=bool(*)(void*,std::uint64_t,void*,std::int32_t,std::int32_t,bool*);
    std::array<void*,13> storage_original{};storage_original.fill(reinterpret_cast<void*>(&writer));
    storage_original[3]=reinterpret_cast<void*>(&request);storage_original[4]=reinterpret_cast<void*>(&finish);
    std::array<void*,15> utils_original{};utils_original.fill(reinterpret_cast<void*>(&writer));
    utils_original[11]=reinterpret_cast<void*>(&completed);utils_original[12]=reinterpret_cast<void*>(&reason);
    utils_original[13]=reinterpret_cast<void*>(&result);
    auto** storage_table=table(storage_original.data(),sizeof(storage_original));
    auto** utils_table=table(utils_original.data(),sizeof(utils_original));
    Interface storage{storage_table},utils{utils_table};storage_self=&storage;utils_self=&utils;
    coop::StorageGuard writers;coop::StorageReadObserver reads;coop::ReadCallObserver calls;
    check(writers.attach(&storage)&&reads.attach(&storage),"read/write observers failed");
    check(std::memcmp(utils_table,utils_original.data(),sizeof(utils_original))==0,"default setup changed utils");
    check(!calls.attach(nullptr),"null utils accepted");
    auto invalid=utils_original;invalid[12]=nullptr;Interface bad{invalid.data()};const auto before_bad=invalid;
    check(!calls.attach(&bad)&&invalid==before_bad,"bad utils table changed");
    check(calls.attach(&utils)&&calls.intact()&&writers.intact()&&reads.intact(),"result observer attach failed");
    MEMORY_BASIC_INFORMATION protection{};VirtualQuery(utils_table,&protection,sizeof(protection));
    check(protection.Protect==PAGE_READONLY&&utils_table[10]==utils_original[10]&&utils_table[14]==utils_original[14],
        "observer changed adjacent entries/protection");
    check(fn<Request>(storage_table[3])(&storage,file,7,100)==handle,"original async request changed");
    check(coop::storage_read_call_identity(handle).matched,"real read observer did not supply identity");
    auto* opaque=reinterpret_cast<bool*>(std::uintptr_t{1});
    check(!fn<Completed>(utils_table[11])(&utils,handle,opaque)&&GetLastError()==0x12345678UL,"pending result/error changed");
    check(!last().failed_available&&coop::read_call_observation().observation_errors==0,"pending failure output read");
    ready=true;bool failed=true;
    check(fn<Completed>(utils_table[11])(&utils,handle,&failed)&&!failed&&GetLastError()==0x12345678UL,"completed result/error changed");
    check(last().failed_available&&!last().failed&&last().read.request_id==1&&last().read.offset==7,"completed identity/flag wrong");
    check(fn<Reason>(utils_table[12])(&utils,handle)==-1&&GetLastError()==0x87654321UL&&last().failure_reason==-1,
        "negative failure reason/error changed");
    Result payload{};
    check(fn<GetResult>(utils_table[13])(&utils,handle,&payload,24,1332,&failed)&&!failed
        &&payload.handle==handle&&payload.offset==7&&payload.bytes==100&&GetLastError()==0xabcdef12UL,"payload/error changed");
    auto event=last();
    check(event.payload_available&&event.payload_handle_matches&&event.payload_scope_matches&&event.payload_result==1
        &&event.payload_offset==7&&event.payload_bytes==100&&event.callback_id==1332&&event.callback_size==24,"read payload not correlated");
    for(mode=1;mode<=3;++mode){
        check(fn<GetResult>(utils_table[13])(&utils,handle,&payload,24,1332,&failed),"mismatch result changed");
        check(last().payload_available&&!last().payload_scope_matches,"mismatched payload attributed to range");
    }
    mode=0;io_failed=true;
    check(fn<GetResult>(utils_table[13])(&utils,handle,&payload,24,1332,&failed)&&failed
        &&last().failed&&!last().payload_available,"failed call payload read");io_failed=false;
    check(fn<GetResult>(utils_table[13])(&utils,handle,&payload,24,999,&failed)&&!last().payload_available,
        "unrelated callback payload read");
    check(!fn<GetResult>(utils_table[13])(&utils,handle,nullptr,-7,-1332,nullptr)
        &&GetLastError()==0xabcdef12UL&&!last().failed_available,"false callback outputs read");
    const auto before_unknown=coop::read_call_observation();
    check(fn<GetResult>(utils_table[13])(&utils,handle+1,reinterpret_cast<void*>(std::uintptr_t{1}),24,1332,opaque),"unknown callback changed");
    check(coop::read_call_observation().event_sequence==before_unknown.event_sequence
        &&coop::read_call_observation().observation_errors==0,"unknown callback inspected/attributed");
    check(fn<Completed>(utils_table[11])(&utils,handle,opaque)&&!last().failed_available,"opaque flag changed result");
    mode=5;check(fn<GetResult>(utils_table[13])(&utils,handle,reinterpret_cast<void*>(std::uintptr_t{1}),24,1332,&failed)
        &&!last().payload_available,"opaque payload changed result");
    mode=6;unsigned char malformed=2;
    check(fn<GetResult>(utils_table[13])(&utils,handle,&payload,24,1332,reinterpret_cast<bool*>(&malformed))
        &&malformed==2&&!last().failed_available,"invalid bool normalized/read as bool");
    check(coop::read_call_observation().observation_errors==3,"invalid observations not counted");mode=0;
    check(fn<Finish>(storage_table[4])(&storage,handle,nullptr,100),"original data completion changed");
    check(fn<GetResult>(utils_table[13])(&utils,handle,&payload,24,1332,&failed)&&last().read.completed,
        "completed read key lost late-result identity");
    ready=false;
    std::vector<std::thread> threads;
    for(int t=0;t<4;++t)threads.emplace_back([&]{for(int n=0;n<1000;++n)check(!fn<Completed>(utils_table[11])(&utils,handle,opaque),"concurrent pending result changed");});
    for(auto& thread:threads)thread.join();
    auto snapshot=coop::read_call_observation();
    check(snapshot.event_count==coop::read_call_event_capacity&&snapshot.discarded_events==snapshot.event_sequence-snapshot.event_count
        &&snapshot.matched_calls[0]==4003&&snapshot.calls[2]==snapshot.matched_calls[2]+1&&!snapshot.bookkeeping_errors,
        "concurrent/bounded/unmatched accounting wrong");
    for(std::size_t n=1;n<snapshot.event_count;++n)check(snapshot.events[n].sequence==snapshot.events[n-1].sequence+1,"event history unordered");
    snapshot.events[0].read.request_id=0;check(coop::read_call_observation().events[0].read.request_id==1,"snapshot aliases events");
    auto separate=utils_original;Interface other{separate.data()};coop::ReadCallObserver denied;
    check(!denied.attach(&other)&&separate==utils_original,"delegate storage reused");
    const auto cached=fn<Completed>(utils_table[11]);DWORD previous{};
    check(VirtualProtect(utils_table,4096,PAGE_READWRITE,&previous)!=0,"tamper setup failed");utils_table[12]=utils_original[0];
    check(VirtualProtect(utils_table,4096,PAGE_READONLY,&previous)!=0,"tamper protection failed");
    check(!calls.intact()&&reads.intact()&&writers.intact(),"utils tamper not detected/affected storage");calls.detach();
    check(utils_table[11]==utils_original[11]&&utils_table[12]==utils_original[0]&&utils_table[13]==utils_original[13],"detach ownership wrong");
    check(!cached(&utils,handle,opaque)&&!denied.attach(&other),"late delegate lifetime wrong");
    reads.detach();writers.detach();
    check(std::memcmp(storage_table,storage_original.data(),sizeof(storage_original))==0,"storage observers not restored");
    VirtualQuery(utils_table,&protection,sizeof(protection));check(protection.Protect==PAGE_READONLY,"utils table left writable");
    VirtualFree(utils_table,0,MEM_RELEASE);VirtualFree(storage_table,0,MEM_RELEASE);
    std::puts("Read call results preserve ABI, failure/payload semantics, unique read scope, concurrency and independent write barriers");
}
