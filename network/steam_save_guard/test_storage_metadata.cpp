#include "storage_metadata.h"
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <vector>

namespace {
struct Interface{void** table;};
void* expected_self{};
constexpr char name[]="./win64_save/data004Slot.bin";
constexpr std::int64_t stamp=0x123456789abcdefLL;
constexpr std::uint64_t quota_total=0xfedcba9876543210ULL,quota_free=0xabcdefff12345678ULL;
std::atomic<std::uint64_t> actual_exists{},actual_writes{};
void check(bool value,const char* why){if(!value){std::fprintf(stderr,"%s\n",why);std::exit(1);}}
void receiver(void* self){check(self==expected_self,"receiver changed");}
void named(void* self,const char* file){receiver(self);check(file&&std::strcmp(file,name)==0,"name changed");}
bool exists(void* self,const char* file){
    receiver(self);++actual_exists;
    if(reinterpret_cast<std::uintptr_t>(file)==1){
        check(GetLastError()==0x11223344UL,"input error changed");SetLastError(0x55667788UL);return false;
    }
    check(file&&std::strcmp(file,name)==0,"exists name changed");SetLastError(0x99887766UL);return true;
}
bool persisted(void* self,const char* file){named(self,file);return false;}
std::int32_t size(void* self,const char* file){named(self,file);return -17;}
std::int64_t timestamp(void* self,const char* file){named(self,file);return stamp;}
std::uint32_t platforms(void* self,const char* file){named(self,file);return 0xffffffffU;}
std::int32_t count(void* self){receiver(self);return -19;}
const char* name_size(void* self,std::int32_t index,std::int32_t* out){
    receiver(self);
    if(index==-9){check(out==nullptr,"null output changed");SetLastError(0x12345678UL);return nullptr;}
    if(index==7){check(reinterpret_cast<std::uintptr_t>(out)==1,"opaque output changed");return name;}
    check(index==123456789&&out,"enumeration input changed");*out=-23;SetLastError(0x87654321UL);return name;
}
bool quota(void* self,std::uint64_t* total,std::uint64_t* free){
    receiver(self);
    if(!total){check(free==nullptr,"quota null arguments changed");SetLastError(0xabcdef11UL);return false;}
    *total=quota_total;*free=quota_free;SetLastError(0xabcdef12UL);return true;
}
bool account(void* self){receiver(self);return false;}
bool app(void* self){receiver(self);return true;}
bool writer(void*,const char*,const void*,std::int32_t){++actual_writes;return true;}
void cloud_setter(void*,bool){check(false,"cloud setter called");}
template<typename Function>Function fn(void* address){
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(address);
}
} // namespace

int main(){
    const auto known=coop::classify_read_target(name);
    check(coop::classify_metadata_target("win64_save/data004slot.bin")==known
        &&coop::classify_metadata_target("./WIN64_SAVE/DATA004SLOT.BIN")==known,"Steam filename aliases not recognized");
    check(coop::classify_metadata_target("../win64_save/data004slot.bin")==coop::unknown_read_target
        &&coop::classify_metadata_target("././win64_save/data004Slot.bin")==coop::unknown_read_target
        &&coop::classify_metadata_target("win64_save/data004slot.bin.extra")==coop::unknown_read_target,
        "unknown filename escaped fixed namespace");
    using BoolName=bool(*)(void*,const char*);
    using Size=std::int32_t(*)(void*,const char*);
    using Stamp=std::int64_t(*)(void*,const char*);
    using Platforms=std::uint32_t(*)(void*,const char*);
    using Count=std::int32_t(*)(void*);
    using Name=const char*(*)(void*,std::int32_t,std::int32_t*);
    using Quota=bool(*)(void*,std::uint64_t*,std::uint64_t*);
    using Bool=bool(*)(void*);
    using Write=bool(*)(void*,const char*,const void*,std::int32_t);
    std::array<void*,24> original{};original.fill(reinterpret_cast<void*>(&writer));
    original[13]=reinterpret_cast<void*>(&exists);original[14]=reinterpret_cast<void*>(&persisted);
    original[15]=reinterpret_cast<void*>(&size);original[16]=reinterpret_cast<void*>(&timestamp);
    original[17]=reinterpret_cast<void*>(&platforms);original[18]=reinterpret_cast<void*>(&count);
    original[19]=reinterpret_cast<void*>(&name_size);original[20]=reinterpret_cast<void*>(&quota);
    original[21]=reinterpret_cast<void*>(&account);original[22]=reinterpret_cast<void*>(&app);
    original[23]=reinterpret_cast<void*>(&cloud_setter);
    auto** table=static_cast<void**>(VirtualAlloc(nullptr,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
    check(table!=nullptr,"table allocation failed");
    std::memcpy(table,original.data(),sizeof(original));DWORD previous{};
    check(VirtualProtect(table,4096,PAGE_READONLY,&previous)!=0,"table protection failed");
    Interface object{table};expected_self=&object;
    coop::StorageGuard guard;coop::StorageMetadataObserver observer;
    check(!observer.attach(nullptr),"null interface attached");
    auto invalid=original;invalid[16]=nullptr;Interface bad{invalid.data()};
    const auto before_invalid=invalid;
    check(!observer.attach(&bad)&&invalid==before_invalid,"invalid table changed");
    check(guard.attach(&object),"guard attach failed");
    for(std::size_t n=13;n<original.size();++n)check(table[n]==original[n],"default guard changed metadata");
    check(observer.attach(&object)&&observer.intact()&&guard.intact(),"combined attach failed");
    MEMORY_BASIC_INFORMATION protection{};VirtualQuery(table,&protection,sizeof(protection));
    check(protection.Protect==PAGE_READONLY&&table[23]==original[23],"protection/cloud setter changed");
    check(fn<BoolName>(table[13])(&object,name)&&GetLastError()==0x99887766UL,"exists result/error changed");
    check(!fn<BoolName>(table[14])(&object,name),"persisted false changed");
    check(fn<Size>(table[15])(&object,name)==-17,"negative size changed");
    check(fn<Stamp>(table[16])(&object,name)==stamp,"64-bit timestamp changed");
    check(fn<Platforms>(table[17])(&object,name)==0xffffffffU,"platform bits changed");
    check(fn<Count>(table[18])(&object)==-19,"negative count changed");
    std::int32_t out{};
    check(fn<Name>(table[19])(&object,123456789,&out)==name&&out==-23&&GetLastError()==0x87654321UL,
        "enumeration return pointer/output/error changed");
    std::uint64_t total{},free{};
    check(fn<Quota>(table[20])(&object,&total,&free)&&total==quota_total&&free==quota_free&&GetLastError()==0xabcdef12UL,
        "unsigned quota outputs/error changed");
    check(!fn<Bool>(table[21])(&object)&&fn<Bool>(table[22])(&object),"cloud bool changed");
    auto snapshot=coop::storage_metadata_observation();
    check(snapshot.event_sequence==10&&snapshot.event_count==10&&!snapshot.observation_errors&&!snapshot.bookkeeping_errors,
        "initial observation incomplete");
    for(auto value:snapshot.calls)check(value==1,"method count wrong");
    check(snapshot.events[2].value==-17&&snapshot.events[3].value==stamp&&snapshot.events[4].value==0xffffffffLL,
        "signed/unsigned metadata value truncated");
    check(snapshot.events[6].index==123456789&&snapshot.events[6].value==-23&&snapshot.events[6].name_returned,
        "enumeration observation wrong");
    check(snapshot.events[7].unsigned_value==quota_total&&snapshot.events[7].secondary==quota_free
        &&snapshot.events[7].has_unsigned_value&&snapshot.events[7].has_secondary,"quota observation truncated");
    check(!fn<Name>(table[19])(&object,-9,nullptr)&&GetLastError()==0x12345678UL,"null enumeration changed");
    check(!fn<Quota>(table[20])(&object,nullptr,nullptr)&&GetLastError()==0xabcdef11UL,"false quota changed");
    check(coop::storage_metadata_observation().observation_errors==0,"failed API output was read");
    check(fn<Name>(table[19])(&object,7,reinterpret_cast<std::int32_t*>(std::uintptr_t{1}))==name,
        "unreadable output changed original result");
    SetLastError(0x11223344UL);
    check(!fn<BoolName>(table[13])(&object,reinterpret_cast<const char*>(std::uintptr_t{1}))
        &&GetLastError()==0x55667788UL,"unreadable name/error changed");
    check(coop::storage_metadata_observation().observation_errors==2,"unreadable observations not reported");
    check(!fn<Write>(table[0])(&object,name,nullptr,0)&&actual_writes==0,"writer barrier relaxed");
    std::vector<std::thread> threads;
    for(int n=0;n<4;++n)threads.emplace_back([&]{for(int i=0;i<1000;++i)check(fn<BoolName>(table[13])(&object,name),"concurrent forwarding failed");});
    for(auto& thread:threads)thread.join();
    snapshot=coop::storage_metadata_observation();
    check(snapshot.calls[0]==4002&&actual_exists==4002&&snapshot.event_sequence==4014
        &&snapshot.event_count==coop::metadata_event_capacity
        &&snapshot.discarded_events==snapshot.event_sequence-snapshot.event_count,"bounded history/concurrency accounting wrong");
    for(std::size_t n=1;n<snapshot.event_count;++n)check(snapshot.events[n].sequence==snapshot.events[n-1].sequence+1,"history not ordered");
    const auto file=coop::classify_read_target(name);
    check(snapshot.targets[file][0]==4001&&snapshot.targets[coop::unknown_read_target][0]==1,
        "known/unknown aggregation wrong");
    snapshot.targets[file][0]=0;check(coop::storage_metadata_observation().targets[file][0]==4001,"snapshot aliases state");
    auto separate=original;Interface another{separate.data()};coop::StorageMetadataObserver denied;
    check(!denied.attach(&another)&&separate==original,"second attachment reused delegates");
    const auto cached=fn<BoolName>(table[13]);
    check(VirtualProtect(table,4096,PAGE_READWRITE,&previous)!=0,"tamper setup failed");
    table[14]=reinterpret_cast<void*>(&writer);
    check(VirtualProtect(table,4096,PAGE_READONLY,&previous)!=0,"tamper restore failed");
    check(!observer.intact()&&guard.intact(),"tamper not detected or guard damaged");
    observer.detach();
    check(table[13]==original[13]&&table[14]==reinterpret_cast<void*>(&writer)&&table[23]==original[23],"detach ownership wrong");
    check(cached(&object,name)&&!denied.attach(&another),"late delegate lifetime/reuse wrong");
    check(VirtualProtect(table,4096,PAGE_READWRITE,&previous)!=0,"cleanup setup failed");table[14]=original[14];
    check(VirtualProtect(table,4096,PAGE_READONLY,&previous)!=0,"cleanup protection failed");guard.detach();
    check(std::memcmp(table,original.data(),sizeof(original))==0,"original table not restored");
    VirtualQuery(table,&protection,sizeof(protection));check(protection.Protect==PAGE_READONLY,"detach protection wrong");
    VirtualFree(table,0,MEM_RELEASE);
    std::puts("Metadata ABI, forwarding/results/errors, bounded concurrent observations and independent writer barrier verified");
}
