#include "buffer_digest.h"
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <thread>
#include <vector>

namespace {
void check(bool value, const char* reason) { if (!value) { std::fprintf(stderr,"%s\n",reason); std::exit(1); } }
std::string hex(const coop::BufferDigest& digest) {
    constexpr char alphabet[]="0123456789abcdef";
    std::string result;
    for (const auto value : digest.bytes) { result += alphabet[value >> 4]; result += alphabet[value & 15]; }
    return result;
}
coop::ReadCompletion completion(std::uint64_t id, std::uint32_t size=3) {
    return {true,true,id,id*2,2,0,size,size};
}
} // namespace
int main() {
    constexpr char abc[]="abc";
    const auto original=std::string(abc);
    SetLastError(0x87654321UL);
    auto digest=coop::hash_read_buffer(abc,3);
    check(GetLastError()==0x87654321UL,"digest changed Win32 error state");
    check(digest.ok && digest.reason==coop::DigestReason::ok
        && hex(digest)=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "SHA256 known vector mismatch");
    check(std::string(abc)==original,"digest modified source buffer");
    digest=coop::hash_read_buffer(nullptr,0);
    check(digest.ok && hex(digest)=="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "empty buffer digest mismatch");
    constexpr char ranged[]="prefixabcSuffix";
    check(hex(coop::hash_read_buffer(ranged+6,3))==hex(coop::hash_read_buffer(abc,3)),"digest escaped selected span");
    std::vector<unsigned char> large(100003);
    for (std::size_t i=0;i<large.size();++i) large[i]=static_cast<unsigned char>(i%251);
    digest=coop::hash_read_buffer(large.data(),static_cast<std::uint32_t>(large.size()));
    check(digest.ok && hex(digest)=="635e9a7d2f64ce04a46b1503cbe287b8721795f215f4b8cf24b256908acaab1a",
        "multi-chunk digest mismatch");
    std::puts("ok - SHA256 vectors, empty/ranged/multi-chunk buffers, input bytes and error state");

    check(!coop::hash_read_buffer(abc,coop::max_digest_bytes+1).ok,"oversized span accepted");
    check(!coop::hash_read_buffer(reinterpret_cast<void*>((std::numeric_limits<std::uintptr_t>::max)()-1),4).ok,
        "wrapping pointer range accepted");
    check(coop::hash_read_buffer(reinterpret_cast<void*>(std::uintptr_t{1}),3).reason==coop::DigestReason::unreadable_buffer,
        "unreadable pointer not rejected");
    auto* pages=static_cast<unsigned char*>(VirtualAlloc(nullptr,8192,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
    check(pages!=nullptr,"guard page allocation failed");
    std::memcpy(pages+4093,abc,3);
    DWORD previous{};
    check(VirtualProtect(pages+4096,4096,PAGE_NOACCESS,&previous)!=0,"guard page setup failed");
    check(coop::hash_read_buffer(pages+4093,3).ok,"valid range before guard page failed");
    digest=coop::hash_read_buffer(pages+4093,4);
    check(!digest.ok && digest.reason==coop::DigestReason::unreadable_buffer,"partial inaccessible range acquired digest");
    VirtualFree(pages,0,MEM_RELEASE);
    std::puts("ok - size/pointer bounds and inaccessible trailing page fail without changing memory");

    coop::BufferDigestStore store;
    store.observe({},reinterpret_cast<void*>(std::uintptr_t{1}));
    auto invalid=completion(1);invalid.original_ok=false;store.observe(invalid,abc);
    invalid=completion(1);invalid.target=coop::unknown_read_target;store.observe(invalid,abc);
    invalid=completion(1);invalid.completion_size=4;store.observe(invalid,abc);
    invalid=completion(1);invalid.offset=coop::max_digest_bytes;store.observe(invalid,abc);
    invalid=completion(0);store.observe(invalid,abc);
    check(store.snapshot().count==0 && store.snapshot().skipped==6,"ineligible completion read a buffer");
    store.observe(completion(1),abc);
    store.observe(completion(1),reinterpret_cast<void*>(std::uintptr_t{1}));
    auto state=store.snapshot();
    check(state.count==1 && !state.records[0].in_progress && state.records[0].digest.ok && state.skipped==7,
        "duplicate completion acquired another digest");
    store.observe(completion(2),reinterpret_cast<void*>(std::uintptr_t{1}));
    state=store.snapshot();
    check(state.count==2 && !state.records[1].digest.ok && !state.records[1].in_progress
        && state.records[1].digest.reason==coop::DigestReason::unreadable_buffer,"failed buffer digest concealed");
    std::puts("ok - completion scope, failed/unknown/oversized sources, duplicates and read failures remain explicit");

    coop::BufferDigestStore parallel;
    std::vector<std::thread> threads;
    for (std::uint64_t t=0;t<4;++t) threads.emplace_back([&,t] {
        for (std::uint64_t n=1;n<=16;++n) parallel.observe(completion(t*16+n),abc);
    });
    for (auto& thread:threads) thread.join();
    state=parallel.snapshot();
    check(state.count==64 && state.available && state.bookkeeping_errors==0,"parallel digest records lost");
    for (std::size_t n=0;n<state.count;++n) check(state.records[n].digest.ok && !state.records[n].in_progress,"parallel digest unfinished");
    parallel.observe(completion(65),abc);
    check(parallel.snapshot().overflows==1 && parallel.snapshot().count==64,"digest capacity exceeded");
    state.records[0].digest.ok=false;
    check(parallel.snapshot().records[0].digest.ok,"digest snapshot aliases internal state");
    std::puts("ok - concurrent private fingerprints, fixed capacity and detached snapshots");
}
