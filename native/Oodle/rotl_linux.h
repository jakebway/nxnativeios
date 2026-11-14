#include <stdint.h>
static inline uint32_t _rotl(uint32_t x, int n) { return (x << n) | (x >> (32 - n)); }   // clang on Linux x86 has no _rotl (ooz takes it from x86gprintrin.h)
