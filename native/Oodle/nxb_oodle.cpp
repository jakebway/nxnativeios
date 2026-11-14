// Oodle's Kraken / Mermaid / Selkie / Leviathan streams (the compression nxnative's shader tools meet in Unreal paks, Trinity packs and PlatinumGames PKZ archives), decoded on the phone.
// nxnative decodes them by running the game's own statically linked Oodle in its Mac host; an iPhone cannot run that code, so the same bytes go through ooz (an open reimplementation of the
// decoder, GPL-3, https://github.com/zao/ooz) instead. Oodle's block format is fixed: 0x8C or 0xCC, then the decoder id (6 Kraken, 10 Mermaid / Selkie, 12 Leviathan), per 256 KB block.
// The one entry point mirrors hle_oodle.c's request: nxb_oodle_decompress(compressed, its length, out, raw length) -> raw length, or -1.
#define OOZ_BUILD_DLL 1
#define NXB_OODLE_PAD 0x40080
#include "kraken.cpp"

extern "C" {

// For a caller that has room: dst must have dst_len + NXB_OODLE_PAD writable bytes (a quantum is 256 KB: the decoder finishes the last one whole, and writes 64 bytes past what it returns).
// The input is copied with padding, since the decoder reads a little past its end. Thread safe: all state is per call.
__attribute__((visibility("default"))) int64_t nxb_oodle_decompress_padded(const uint8_t *src, int64_t src_len, uint8_t *dst, int64_t dst_len) {
    enum { PAD = 128 };
    if (!src || !dst || src_len < 0 || dst_len < 0 || src_len > 0x7fffffff - PAD || dst_len > 0x7fffffff - 0x40080) return -1;
    if (dst_len == 0) return 0;
    uint8_t *in = (uint8_t *)malloc((size_t)src_len + PAD);
    if (!in) return -1;
    memcpy(in, src, (size_t)src_len); memset(in + src_len, 0, PAD);
    KrakenDecoder *dec = Kraken_Create();
    const byte *s = in; size_t sl = (size_t)src_len, dl = (size_t)dst_len; int offset = 0; bool ok = true;
    while (dl != 0) {   // Kraken_Decompress, except that bytes after the last block are not an error (the Mac host's decoder takes them as they come)
        if (!Kraken_DecodeStep(dec, dst, offset, dl, s, sl) || dec->src_used == 0) { ok = false; break; }
        s += dec->src_used; sl -= (size_t)dec->src_used; dl -= (size_t)dec->dst_used; offset += dec->dst_used;
    }
    Kraken_Destroy(dec);
    free(in);
    return ok ? dst_len : -1;
}

// The same for any caller: the output goes through a padded copy
__attribute__((visibility("default"))) int64_t nxb_oodle_decompress(const uint8_t *src, int64_t src_len, uint8_t *dst, int64_t dst_len) {
    if (!src || !dst || dst_len < 0 || dst_len > 0x7fffffff - 0x40080) return -1;
    if (dst_len == 0) return 0;
    uint8_t *out = (uint8_t *)malloc((size_t)dst_len + 0x40080);
    if (!out) return -1;
    int64_t r = nxb_oodle_decompress_padded(src, src_len, out, dst_len);
    if (r == dst_len) memcpy(dst, out, (size_t)dst_len);
    free(out);
    return r;
}

}
