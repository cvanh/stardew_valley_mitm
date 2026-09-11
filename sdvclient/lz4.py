"""Pure-python LZ4 *block* decompressor.

Stardew Valley 1.6 compresses network messages larger than 1 KiB with
``LZ4_compress_default`` and prefixes them with a 9 byte header
(``0x7F``, int32 compressed size, int32 decompressed size).  The client never
has to compress anything: the server accepts uncompressed messages of any
size, so only decompression is implemented here.
"""

from __future__ import annotations


class LZ4Error(ValueError):
    pass


def block_decompress(src: bytes, out_size: int) -> bytes:
    """Decompress one raw LZ4 block into exactly ``out_size`` bytes."""
    dst = bytearray()
    i = 0
    n = len(src)
    try:
        while i < n:
            token = src[i]
            i += 1
            literal_len = token >> 4
            if literal_len == 15:
                while True:
                    b = src[i]
                    i += 1
                    literal_len += b
                    if b != 255:
                        break
            if literal_len:
                dst += src[i : i + literal_len]
                i += literal_len
            if i >= n:
                break  # final literal run has no match part
            offset = src[i] | (src[i + 1] << 8)
            i += 2
            if offset == 0:
                raise LZ4Error("zero match offset")
            match_len = token & 0x0F
            if match_len == 15:
                while True:
                    b = src[i]
                    i += 1
                    match_len += b
                    if b != 255:
                        break
            match_len += 4
            start = len(dst) - offset
            if start < 0:
                raise LZ4Error("match offset points before start of output")
            if offset >= match_len:
                dst += dst[start : start + match_len]
            else:
                # overlapping match: copy byte by byte (run-length style)
                for k in range(match_len):
                    dst.append(dst[start + k])
    except IndexError as exc:
        raise LZ4Error("truncated LZ4 block") from exc
    if len(dst) != out_size:
        raise LZ4Error(f"decompressed {len(dst)} bytes, expected {out_size}")
    return bytes(dst)
