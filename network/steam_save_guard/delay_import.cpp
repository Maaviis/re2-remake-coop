#include "delay_import.h"
#include <windows.h>
#include <cstdint>
#include <cstring>
#include <limits>

namespace coop {
namespace {
struct ErrorRestore{DWORD value=GetLastError();~ErrorRestore(){SetLastError(value);}};
bool copy(const void* pointer,void* output,std::size_t size){
    SIZE_T read{};return pointer&&ReadProcessMemory(GetCurrentProcess(),pointer,output,size,&read)&&read==size;
}
struct View {
    std::uintptr_t base{};std::size_t size{};
    bool read(std::size_t rva,void* output,std::size_t bytes) const {
        return rva<=size&&bytes<=size-rva&&copy(reinterpret_cast<const void*>(base+rva),output,bytes);
    }
    bool string(std::uint32_t rva,char(&out)[128]) const {
        for(std::size_t n=0;n<sizeof(out);++n){if(!read(static_cast<std::size_t>(rva)+n,out+n,1))return false;if(!out[n])return true;}
        return false;
    }
};
struct DelayDescriptor{std::uint32_t attributes,name,module,iat,int_table,bound,unload,timestamp;};
static_assert(sizeof(DelayDescriptor)==32);
} // namespace
const char* call_result_import_name(CallResultImport name){
    return name==CallResultImport::register_result?"SteamAPI_RegisterCallResult":"SteamAPI_UnregisterCallResult";
}
void** find_call_result_import(void* image,std::size_t mapped_size,CallResultImport wanted) noexcept {
    const ErrorRestore preserve;
    try{
        const auto base=reinterpret_cast<std::uintptr_t>(image);
        if(!base||mapped_size<4096||mapped_size>512ULL*1024*1024
            ||base>(std::numeric_limits<std::uintptr_t>::max)()-mapped_size)return nullptr;
        View view{base,mapped_size};IMAGE_DOS_HEADER dos{};IMAGE_NT_HEADERS64 nt{};
        if(!view.read(0,&dos,sizeof(dos))||dos.e_magic!=IMAGE_DOS_SIGNATURE||dos.e_lfanew<0
            ||!view.read(static_cast<std::size_t>(dos.e_lfanew),&nt,sizeof(nt))||nt.Signature!=IMAGE_NT_SIGNATURE
            ||nt.FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64||nt.FileHeader.SizeOfOptionalHeader<sizeof(IMAGE_OPTIONAL_HEADER64)
            ||nt.OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC||nt.OptionalHeader.NumberOfRvaAndSizes<=IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT
            ||nt.OptionalHeader.SizeOfImage<4096||nt.OptionalHeader.SizeOfImage>mapped_size)return nullptr;
        view.size=nt.OptionalHeader.SizeOfImage;
        const auto directory=nt.OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT];
        if(!directory.VirtualAddress||directory.Size<sizeof(DelayDescriptor)||directory.Size>4096
            ||directory.Size%sizeof(DelayDescriptor)||directory.VirtualAddress>view.size
            ||directory.Size>view.size-directory.VirtualAddress)return nullptr;
        void** found=nullptr;bool ended=false;
        for(std::size_t n=0;n<directory.Size/sizeof(DelayDescriptor);++n){
            DelayDescriptor descriptor{};
            if(!view.read(directory.VirtualAddress+n*sizeof(descriptor),&descriptor,sizeof(descriptor)))return nullptr;
            if(!descriptor.name){
                if(descriptor.attributes||descriptor.module||descriptor.iat||descriptor.int_table||descriptor.bound||descriptor.unload||descriptor.timestamp)return nullptr;
                ended=true;break;
            }
            if(descriptor.attributes!=1)return nullptr;
            char dll[128]{};if(!view.string(descriptor.name,dll))return nullptr;
            if(_stricmp(dll,"steam_api64.dll"))continue;
            if(!descriptor.iat||!descriptor.int_table)return nullptr;
            bool names_ended=false;
            for(std::size_t t=0;t<4096;++t){
                std::uint64_t thunk{};
                const auto int_rva=static_cast<std::size_t>(descriptor.int_table)+t*sizeof(thunk);
                const auto iat_rva=static_cast<std::size_t>(descriptor.iat)+t*sizeof(void*);
                void* current{};
                if(!view.read(int_rva,&thunk,sizeof(thunk))||!view.read(iat_rva,&current,sizeof(current)))return nullptr;
                if(!thunk){names_ended=true;break;}
                if(thunk&IMAGE_ORDINAL_FLAG64)continue;
                if(thunk>(std::numeric_limits<std::uint32_t>::max)()-2)return nullptr;
                char name[128]{};if(!view.string(static_cast<std::uint32_t>(thunk)+2,name))return nullptr;
                if(std::strcmp(name,call_result_import_name(wanted)))continue;
                if(found||!current||iat_rva%alignof(void*))return nullptr;
                found=reinterpret_cast<void**>(view.base+iat_rva);
            }
            if(!names_ended)return nullptr;
        }
        return ended?found:nullptr;
    }catch(...){return nullptr;}
}
ImportPatch::~ImportPatch(){detach();}
bool ImportPatch::attach(void** slot,void* expected,void* replacement){
    const ErrorRestore preserve;
    if(slot_){error_="already_attached";return false;}
    void* current{};
    if(!slot||reinterpret_cast<std::uintptr_t>(slot)%alignof(void*)||!expected||!replacement||expected==replacement
        ||!copy(slot,&current,sizeof(current))||current!=expected){error_="import_slot_mismatch";return false;}
    DWORD previous{};
    if(!VirtualProtect(slot,sizeof(void*),PAGE_READWRITE,&previous)){error_="import_protection_failed";return false;}
    const auto exchanged=InterlockedCompareExchangePointer(slot,replacement,expected);
    DWORD ignored{};
    const bool restored=VirtualProtect(slot,sizeof(void*),previous,&ignored)!=0;
    if(exchanged!=expected){error_="import_slot_changed";return false;}
    slot_=slot;original_=expected;replacement_=replacement;protection_=previous;protection_restored_=restored;
    error_=restored?"ok":"import_protection_restore_failed";return restored;
}
bool ImportPatch::intact() const{
    const ErrorRestore preserve;void* current{};
    return slot_&&protection_restored_&&copy(slot_,&current,sizeof(current))&&current==replacement_;
}
void ImportPatch::detach(){
    const ErrorRestore preserve;
    if(!slot_)return;
    DWORD previous{};if(!VirtualProtect(slot_,sizeof(void*),PAGE_READWRITE,&previous))return;
    InterlockedCompareExchangePointer(slot_,original_,replacement_);
    DWORD ignored{};VirtualProtect(slot_,sizeof(void*),protection_,&ignored);slot_=nullptr;protection_restored_=false;
}
} // namespace coop
