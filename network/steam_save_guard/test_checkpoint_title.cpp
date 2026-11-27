#include "checkpoint_title.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>
namespace {
struct Method { const char* name; std::uint64_t value; bool reference{}; };
std::array<Method, 9> methods{{
    {"get_IsInTitle",1},{"get_IsInLoadGameData",0},{"get_IsBusy",0},{"get_IsErrorBusy",0},
    {"get_CurrentPlayer",0,true},{"isBusyLoad",0},{"isBusyMenuStory",0},
    {"isTitleMenuOpened",1},{"isBusyMenuMain",0}
}};
bool missing{}, missing_player{}, bad_static{}, bad_type{}, exception{};
unsigned int parameters{};
REFrameworkResult invoke_error{};
int invocations{};
void check(bool value,const char* reason) { if (!value) { std::fprintf(stderr,"%s\n",reason);std::exit(1); } }
REFrameworkTDBHandle tdb() { return reinterpret_cast<REFrameworkTDBHandle>(1); }
REFrameworkTypeDefinitionHandle find_type(REFrameworkTDBHandle,const char*) {
    return missing ? nullptr : reinterpret_cast<REFrameworkTypeDefinitionHandle>(1);
}
REFrameworkManagedObjectHandle object(const char* type) {
    return missing || (missing_player && std::string_view(type)=="app.ropeway.PlayerManager") ? nullptr : reinterpret_cast<REFrameworkManagedObjectHandle>(1);
}
REFrameworkMethodHandle find_method(REFrameworkTypeDefinitionHandle,const char* name) {
    for(auto& method:methods) if(std::string_view(method.name)==name) return reinterpret_cast<REFrameworkMethodHandle>(&method);
    return nullptr;
}
REFrameworkTypeDefinitionHandle return_type(REFrameworkMethodHandle method) {
    return reinterpret_cast<REFrameworkTypeDefinitionHandle>(static_cast<std::uintptr_t>(reinterpret_cast<Method*>(method)->reference ? 2 : 1));
}
bool is_value(REFrameworkTypeDefinitionHandle type) { return type==reinterpret_cast<REFrameworkTypeDefinitionHandle>(1); }
REFrameworkResult full_name(REFrameworkTypeDefinitionHandle,char* out,unsigned int size,unsigned int* count) {
    const char* text=bad_type ? "System.Int32" : "System.Boolean";
    const auto length=std::strlen(text)+1;
    if(size<length) return REFRAMEWORK_ERROR_OUT_TOO_SMALL;
    std::memcpy(out,text,length);*count=static_cast<unsigned int>(length);return REFRAMEWORK_ERROR_NONE;
}
unsigned int num_params(REFrameworkMethodHandle) { return parameters; }
bool is_static(REFrameworkMethodHandle) { return bad_static; }
REFrameworkResult invoke(REFrameworkMethodHandle method,void* self,void** args,unsigned int count,void* out,unsigned int size) {
    check(self && !args && !count && size==129,"invalid getter invocation ABI");
    ++invocations;
    std::memset(out,0,size);
    const auto value=reinterpret_cast<Method*>(method)->value;
    std::memcpy(out,&value,sizeof(value));
    static_cast<unsigned char*>(out)[128]=exception;
    return invoke_error;
}
}
int main() {
    REFrameworkSDKFunctions functions{};
    functions.get_tdb=tdb;functions.get_managed_singleton=object;
    REFrameworkTDB database{};database.find_type=find_type;
    REFrameworkTDBTypeDefinition type{};
    type.find_method=find_method;type.get_full_name=full_name;type.is_valuetype=is_value;
    REFrameworkTDBMethod method{};
    method.invoke=invoke;method.get_return_type=return_type;method.get_num_params=num_params;method.is_static=is_static;
    REFrameworkSDKData api{};
    api.functions=&functions;api.tdb=&database;api.type_definition=&type;api.method=&method;
    check(!coop::checkpoint_title(nullptr).ready,"missing SDK accepted");
    check(coop::checkpoint_title(&api).ready && invocations>0,"ready native title rejected");
    missing_player=true;check(coop::checkpoint_title(&api).ready,"title without a player manager rejected");missing_player=false;
    for(std::size_t index=0;index<7;++index) {
        const auto old=methods[index].value;methods[index].value=old ? 0 : 1;
        check(!coop::checkpoint_title(&api).ready,"invalid title condition accepted");methods[index].value=old;
    }
    methods[7].value=0;check(!coop::checkpoint_title(&api).ready,"closed menus accepted");
    methods[8].value=1;check(coop::checkpoint_title(&api).ready,"main-menu entry rejected");
    methods[7].value=1;methods[8].value=0;
    for(auto* flag:{&missing,&bad_static,&bad_type,&exception}) {
        *flag=true;check(!coop::checkpoint_title(&api).ready,"unsupported native getter accepted");*flag=false;
    }
    parameters=1;check(!coop::checkpoint_title(&api).ready,"getter with arguments invoked");parameters=0;
    invoke_error=REFRAMEWORK_ERROR_EXCEPTION;check(!coop::checkpoint_title(&api).ready,"invoke error ignored");invoke_error=0;
    methods[0].value=2;check(!coop::checkpoint_title(&api).ready,"non-boolean return accepted");
    std::puts("Verified title-only checkpoint admission, getter metadata, exact invoke ABI and fail-closed reads");
}
