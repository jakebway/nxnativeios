// LZ5 2.0.1 (later renamed Lizard), DRAGON QUEST XI S's pak compression (method 3: every block starts with its level, 0x2d). nxnative decodes it with the game's own LZ5_decompress_safe in
// its Mac host; here the library's own decoder (BSD-2-Clause, https://github.com/inikep/lizard at the last commit before the rename) does it.
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
extern "C" int LZ5_decompress_safe(const char *source, char *dest, int compressedSize, int maxDecompressedSize);
#ifdef NXB_TEST
extern "C" int LZ5_compress_MinLevel(const char *src, char *dst, int srcSize, int maxDstSize, int compressionLevel);
extern "C" int LZ5_compress(const char *src, char *dst, int srcSize, int maxDstSize, int compressionLevel);
#endif
extern "C" {
// -> bytes decoded (a block may decode to less than dst_len), or -1. The output has slack: the decoder copies in wide steps.
__attribute__((visibility("default"))) int64_t nxb_lz5_decompress(const uint8_t *src, int64_t src_len, uint8_t *dst, int64_t dst_len) {
    if (!src || !dst || src_len < 0 || dst_len < 0 || src_len > 0x7ffff000 || dst_len > 0x7ffff000) return -1;
    if (dst_len == 0) return 0;
    uint8_t *out = (uint8_t *)malloc((size_t)dst_len + 0x10000);
    if (!out) return -1;
    int r = LZ5_decompress_safe((const char *)src, (char *)out, (int)src_len, (int)dst_len);
    if (r >= 0) memcpy(dst, out, (size_t)r);
    free(out);
    return r;
}
#ifdef NXB_TEST
__attribute__((visibility("default"))) int64_t nxb_lz5_compress(const uint8_t *src, int64_t n, uint8_t *dst, int64_t cap, int level) {
    return LZ5_compress((const char *)src, (char *)dst, (int)n, (int)cap, level);
}
#endif
}
