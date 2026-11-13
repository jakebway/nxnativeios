// The phone's signer: zsign (MIT, github.com/zhlynn/zsign) built into the app. The build's app folder is signed in place with the user's own .p12 and .mobileprovision,
// before it is zipped, so signing needs no second copy of a 36 GB game. Python calls nxb_sign_app through ctypes (assemble.py).
#include "common/common.h"
#include "openssl.h"
#include "bundle.h"
#include <cstring>

extern "C" __attribute__((used, visibility("default")))
int nxb_sign_app(const char *folder, const char *p12, const char *password, const char *prov, const char *bundleId, char *err, int errlen) {
    ZSignAsset asset;
    if (!asset.Init("", p12, prov, "", password ? password : "", false, false, false)) { snprintf(err, errlen, "the certificate or profile could not be loaded (wrong password, or the profile does not list this certificate)"); return 1; }
    ZBundle bundle;
    bundle.m_bEnableDocuments = false;
    vector<string> none;
    if (!bundle.SignFolder(&asset, folder, bundleId ? bundleId : "", "", "", none, none, true, false, false, false)) { snprintf(err, errlen, "signing failed"); return 2; }
    return 0;
}
