#include "callback_abi.h"
#include <steam/steam_api.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>

namespace {
int selected=-1;
void check(bool value,const char* why){if(!value){std::fprintf(stderr,"%s\n",why);std::exit(1);}}
void first(void*,void*){selected=0;}
void second(void*,void*){selected=1;}
int size(void*){return 24;}
class Probe:public CCallbackBase{
public:
    Probe(){m_iCallback=1332;m_nCallbackFlags=0x42;}
    void Run(void*)override{}
    void Run(void*,bool,SteamAPICall_t)override{}
    int GetCallbackSizeBytes()override{return 24;}
};
// The calls use the SDK declarations, independently of the production hook's
// assumed table order. The marker callees ignore extra Windows x64 arguments.
__declspec(noinline)void invoke_single(CCallbackBase* p){p->Run(nullptr);}
__declspec(noinline)void invoke_call(CCallbackBase* p){p->Run(nullptr,false,0xfedcba9876543210ULL);}
__declspec(noinline)int invoke_size(CCallbackBase* p){return p->GetCallbackSizeBytes();}
} // namespace
int main(){
    Probe probe;unsigned char prefix[16]{};std::memcpy(prefix,&probe,sizeof(prefix));std::int32_t id{};
    std::memcpy(&id,prefix+12,sizeof(id));
    check(sizeof(CCallbackBase)==16&&prefix[8]==0x42&&id==1332,"published callback object prefix changed");
    void* table[]{reinterpret_cast<void*>(&first),reinterpret_cast<void*>(&second),reinterpret_cast<void*>(&size)};
    *reinterpret_cast<void***>(&probe)=table;
    invoke_single(&probe);check(selected==static_cast<int>(coop::callback_single_slot),"SDK single Run vftable slot differs");
    invoke_call(&probe);check(selected==static_cast<int>(coop::callback_call_slot),"SDK call-result Run vftable slot differs");
    check(coop::callback_size_slot==2&&invoke_size(&probe)==24,"SDK size getter slot differs");
    std::puts("Pinned SDK CCallbackBase: MSVC x64 call-result slot0, single slot1, getter slot2, prefix16/id12 verified");
}
