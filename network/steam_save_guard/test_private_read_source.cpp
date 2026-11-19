#include "private_read_source.h"
#include <windows.h>
#include <fstream>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

namespace {
void check(bool value,const char* reason){if(!value){std::fprintf(stderr,"%s\n",reason);std::exit(1);}}
constexpr char abc[]="abc";
const std::string run(32,'a'),request(32,'b');
coop::ReadCompletion completion(std::uint64_t id){
    return {true,true,id,id*2,coop::classify_read_target("./win64_save/data004Slot.bin"),0,3,3};
}
void write(const std::filesystem::path& path,const char* bytes){
    std::ofstream file(path,std::ios::binary|std::ios::trunc);file.write(bytes,3);check(static_cast<bool>(file),"fixture write failed");
}
} // namespace
int main(){
    const auto root=std::filesystem::absolute(std::filesystem::current_path()/ ("source-fixture-"+std::to_string(GetCurrentProcessId())));
    check(!std::filesystem::exists(root),"fixture directory already exists");
    std::filesystem::create_directory(root);
    const auto path=root/L"data004Slot.bin";write(path,abc);
    const auto expected=coop::hash_read_buffer(abc,3);check(expected.ok,"fixture hash failed");
    const auto pid=GetCurrentProcessId();
    {
        coop::PrivateReadSource off;
        char buffer[3]={'a','b','c'};off.apply(completion(1),buffer,100);
        check(!off.snapshot(100).enabled && std::memcmp(buffer,abc,3)==0,"disabled source changed input");
        coop::PrivateReadSource source;
        check(source.prepare(path,expected.bytes,3,run,request,pid),"valid private source rejected");
        check(!source.prepare(path,expected.bytes,3,run,request,pid),"source replaced after preparation");
        check(!source.renew(run,std::string(32,'c'),pid,100,100,true),"wrong request armed");
        check(!source.renew(run,request,pid+1,100,100,true),"wrong PID armed");
        check(!source.renew(std::string(32,'c'),request,pid,100,100,true),"wrong run armed");
        check(!source.renew(run,request,pid,101,100,true),"future lease armed");
        check(!source.renew(run,request,pid,96,100,true),"stale lease armed");
        check(!source.renew(run,request,pid,100,100,false),"unhealthy guard armed");
        check(source.renew(run,request,pid,100,100,true) && source.snapshot(100).armed,"fresh scope lease rejected");
        source.apply(completion(1),buffer,106);
        check(source.snapshot(106).count==0 && !source.snapshot(106).armed,"expired lease wrote input");
        check(source.renew(run,request,pid,107,107,true),"lease renewal failed");
        auto wrong=completion(1);wrong.requested_size=4;
        source.apply(wrong,reinterpret_cast<void*>(std::uintptr_t{1}),107);
        wrong=completion(1);wrong.target=coop::unknown_read_target;
        source.apply(wrong,buffer,107);
        check(source.snapshot(107).count==0,"wrong range/file read input");
        // Later disk changes cannot replace the already verified immutable RAM source.
        write(path,"XYZ");
        SetLastError(0x98765432UL);
        source.apply(completion(2),buffer,107);
        check(GetLastError()==0x98765432UL,"source replay changed error state");
        auto state=source.snapshot(107);
        check(state.count==1 && state.records[0].supplied && state.records[0].copied_bytes==3
            && state.records[0].before_matches && state.records[0].after_matches && !state.records[0].in_progress,
            "verified private RAM bytes were not supplied");
        check(std::memcmp(buffer,abc,3)==0,"identical replay changed bytes");
        source.apply(completion(2),buffer,107);
        check(source.snapshot(107).count==1,"duplicate request was replayed");
        source.apply(completion(3),buffer,107);
        check(source.snapshot(107).count==2 && source.snapshot(107).records[1].supplied,"second response failed");
        source.apply(completion(4),buffer,107);
        check(source.snapshot(107).count==2 && source.snapshot(107).reason==coop::PrivateReadReason::exhausted,
            "source replay exceeded two responses");
        state.records[0].supplied=false;
        check(source.snapshot(107).records[0].supplied,"snapshot aliases state");
    }
    write(path,abc);
    {
        coop::PrivateReadSource mismatch;
        check(mismatch.prepare(path,expected.bytes,3,run,request,pid),"mismatch fixture prepare failed");
        check(mismatch.renew(run,request,pid,100,100,true),"mismatch fixture lease failed");
        char different[3]={'X','Y','Z'};mismatch.apply(completion(1),different,100);
        check(!mismatch.snapshot(100).records[0].supplied && mismatch.snapshot(100).records[0].copied_bytes==0
            && std::memcmp(different,"XYZ",3)==0,"nonidentical original was overwritten");
        auto* page=static_cast<char*>(VirtualAlloc(nullptr,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
        check(page!=nullptr,"destination fixture allocation failed");std::memcpy(page,abc,3);
        DWORD previous{};check(VirtualProtect(page,4096,PAGE_READONLY,&previous)!=0,"read-only setup failed");
        mismatch.apply(completion(2),page,100);
        auto state=mismatch.snapshot(100);
        check(state.records[1].reason==coop::PrivateReadReason::destination_not_writable
            && state.records[1].copied_bytes==0 && std::memcmp(page,abc,3)==0,"read-only destination changed");
        MEMORY_BASIC_INFORMATION protection{};VirtualQuery(page,&protection,sizeof(protection));
        check(protection.Protect==PAGE_READONLY,"destination protection changed");VirtualFree(page,0,MEM_RELEASE);
    }
    {
        auto wrong_hash=expected.bytes;wrong_hash[0]^=1;
        coop::PrivateReadSource bad_hash;
        check(!bad_hash.prepare(path,wrong_hash,3,run,request,pid) && !bad_hash.snapshot(100).prepared,
            "unverified source prepared");
        coop::PrivateReadSource wrong_size;
        check(!wrong_size.prepare(path,expected.bytes,4,run,request,pid),"wrong source size accepted");
        coop::PrivateReadSource wrong_token;
        check(!wrong_token.prepare(path,expected.bytes,3,"invalid",request,pid),"invalid scope accepted");
    }
    // Only remove these two exact fixture paths, never recursively remove computed roots.
    check(std::filesystem::remove(path),"fixture file cleanup failed");
    check(std::filesystem::remove(root),"fixture directory cleanup failed");
    std::puts("Private replay: source/scope/lease/hash, immutable source, two responses, duplicate and memory-protection gates verified");
}
