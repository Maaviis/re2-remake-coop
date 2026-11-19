#include "delay_import.h"
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace {
void check(bool v,const char* why){if(!v){std::fprintf(stderr,"%s\n",why);std::exit(1);}}
int original(){return 1;}int replacement(){return 2;}int other(){return 3;}
struct Descriptor{std::uint32_t attributes,name,module,iat,int_table,bound,unload,timestamp;};
struct Fixture {
    char* bytes=static_cast<char*>(VirtualAlloc(nullptr,0x6000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
    Fixture(){check(bytes!=nullptr,"allocation failed");reset();}
    ~Fixture(){VirtualFree(bytes,0,MEM_RELEASE);}
    void reset(){
        std::memset(bytes,0,0x6000);
        auto* dos=reinterpret_cast<IMAGE_DOS_HEADER*>(bytes);dos->e_magic=IMAGE_DOS_SIGNATURE;dos->e_lfanew=0x100;
        auto* nt=reinterpret_cast<IMAGE_NT_HEADERS64*>(bytes+0x100);nt->Signature=IMAGE_NT_SIGNATURE;
        nt->FileHeader.Machine=IMAGE_FILE_MACHINE_AMD64;nt->FileHeader.SizeOfOptionalHeader=sizeof(IMAGE_OPTIONAL_HEADER64);
        nt->OptionalHeader.Magic=IMAGE_NT_OPTIONAL_HDR64_MAGIC;nt->OptionalHeader.SizeOfImage=0x6000;
        nt->OptionalHeader.NumberOfRvaAndSizes=16;nt->OptionalHeader.DataDirectory[13]={0x400,64};
        *reinterpret_cast<Descriptor*>(bytes+0x400)={1,0x600,0,0x1000,0x1200,0,0,0};
        strcpy_s(bytes+0x600,128,"steam_api64.dll");
        auto* names=reinterpret_cast<std::uint64_t*>(bytes+0x1200);names[0]=0x1400;names[1]=0x1500;
        strcpy_s(bytes+0x1402,128,"SteamAPI_RegisterCallResult");strcpy_s(bytes+0x1502,128,"SteamAPI_UnregisterCallResult");
        slots()[0]=reinterpret_cast<void*>(&original);slots()[1]=reinterpret_cast<void*>(&other);
    }
    void** slots(){return reinterpret_cast<void**>(bytes+0x1000);}
    void** find(){return coop::find_call_result_import(bytes,0x6000,coop::CallResultImport::register_result);}
};
} // namespace
int main(){
    Fixture f;
    SetLastError(0x12345678UL);check(f.find()==f.slots()&&GetLastError()==0x12345678UL,"valid lookup/error failed");
    check(coop::find_call_result_import(f.bytes,0x6000,coop::CallResultImport::unregister_result)==f.slots()+1,"unregister lookup wrong");
    check(!coop::find_call_result_import(nullptr,0x6000,coop::CallResultImport::register_result),"null image accepted");
    check(!coop::find_call_result_import(reinterpret_cast<void*>(std::uintptr_t{1}),0x6000,coop::CallResultImport::register_result),"unreadable image accepted");
    check(!coop::find_call_result_import(f.bytes,16,coop::CallResultImport::register_result),"truncated image accepted");
    reinterpret_cast<IMAGE_DOS_HEADER*>(f.bytes)->e_lfanew=-1;check(!f.find(),"negative NT offset accepted");f.reset();
    auto* nt=reinterpret_cast<IMAGE_NT_HEADERS64*>(f.bytes+0x100);
    nt->OptionalHeader.DataDirectory[13]={0x5ff0,64};check(!f.find(),"directory escaped image");f.reset();
    reinterpret_cast<Descriptor*>(f.bytes+0x400)->attributes=0;check(!f.find(),"VA-based descriptor accepted");f.reset();
    reinterpret_cast<Descriptor*>(f.bytes+0x400)->int_table=0x5fff;check(!f.find(),"thunk escaped image");f.reset();
    reinterpret_cast<std::uint64_t*>(f.bytes+0x1200)[0]=0xfffffffefULL;check(!f.find(),"64-bit name RVA truncated");f.reset();
    strcpy_s(f.bytes+0x1502,128,"SteamAPI_RegisterCallResult");check(!f.find(),"duplicate named imports accepted");f.reset();
    std::memset(f.bytes+0x1402,'X',128);check(!f.find(),"unterminated import name accepted");f.reset();
    f.slots()[0]=nullptr;check(!f.find(),"null import target accepted");f.reset();
    reinterpret_cast<std::uint64_t*>(f.bytes+0x1200)[0]=IMAGE_ORDINAL_FLAG64|1;
    check(!f.find(),"ordinal acquired named import identity");f.reset();
    DWORD previous{};check(VirtualProtect(f.bytes,0x6000,PAGE_READONLY,&previous)!=0,"read-only setup failed");
    check(f.find()==f.slots(),"lookup requires writable image");
    coop::ImportPatch patch;
    check(!patch.attach(f.slots(),reinterpret_cast<void*>(&other),reinterpret_cast<void*>(&replacement)),"unexpected slot overwritten");
    check(patch.attach(f.slots(),reinterpret_cast<void*>(&original),reinterpret_cast<void*>(&replacement))&&patch.intact(),"patch failed");
    check(f.slots()[0]==reinterpret_cast<void*>(&replacement)&&f.slots()[1]==reinterpret_cast<void*>(&other),"adjacent import changed");
    MEMORY_BASIC_INFORMATION protection{};VirtualQuery(f.slots(),&protection,sizeof(protection));
    check(protection.Protect==PAGE_READONLY,"patch left image writable");
    check(!patch.attach(f.slots(),reinterpret_cast<void*>(&replacement),reinterpret_cast<void*>(&other)),"patch reused");
    patch.detach();check(f.slots()[0]==reinterpret_cast<void*>(&original)&&!patch.intact(),"original not restored");
    coop::ImportPatch owner;
    check(owner.attach(f.slots(),reinterpret_cast<void*>(&original),reinterpret_cast<void*>(&replacement)),"ownership setup failed");
    check(VirtualProtect(f.slots(),sizeof(void*),PAGE_READWRITE,&previous)!=0,"tamper setup failed");
    f.slots()[0]=reinterpret_cast<void*>(&other);DWORD ignored{};
    check(VirtualProtect(f.slots(),sizeof(void*),previous,&ignored)!=0,"tamper restore failed");
    check(!owner.intact(),"foreign change remained healthy");owner.detach();
    check(f.slots()[0]==reinterpret_cast<void*>(&other),"detach overwrote another owner");
    VirtualQuery(f.slots(),&protection,sizeof(protection));check(protection.Protect==PAGE_READONLY,"detach protection wrong");
    std::puts("Bounded delay-import lookup, malformed/duplicate rejection and owned pointer patch/restore verified");
}
