"""Little-endian binary reader/writer with .NET BinaryReader/BinaryWriter semantics.

Stardew Valley serialises its network messages with ``System.IO.BinaryWriter``
and Lidgren uses the same 7-bit variable-length integer for string lengths, so
one pair of helpers covers both layers of the protocol.
"""

from __future__ import annotations

import struct
from typing import List


class Reader:
    """Sequential reader over a bytes object."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def read(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise EOFError(
                f"need {n} bytes at offset {self.pos}, only {len(self.data) - self.pos} left"
            )
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return bytes(chunk)

    def peek_u8(self) -> int:
        if self.pos >= len(self.data):
            raise EOFError(f"peek past end at offset {self.pos}")
        return self.data[self.pos]

    def _unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        if self.pos + size > len(self.data):
            raise EOFError(
                f"need {size} bytes at offset {self.pos}, only {len(self.data) - self.pos} left"
            )
        (value,) = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return value

    def u8(self) -> int:
        return self._unpack("<B")

    def i8(self) -> int:
        return self._unpack("<b")

    def bool_(self) -> bool:
        return self.u8() != 0

    def i16(self) -> int:
        return self._unpack("<h")

    def u16(self) -> int:
        return self._unpack("<H")

    def i32(self) -> int:
        return self._unpack("<i")

    def u32(self) -> int:
        return self._unpack("<I")

    def i64(self) -> int:
        return self._unpack("<q")

    def u64(self) -> int:
        return self._unpack("<Q")

    def f32(self) -> float:
        return self._unpack("<f")

    def f64(self) -> float:
        return self._unpack("<d")

    def varint(self) -> int:
        """7-bit encoded unsigned integer (BinaryReader.Read7BitEncodedInt / Lidgren varuint)."""
        result = 0
        shift = 0
        while True:
            b = self.u8()
            result |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return result
            if shift > 35:
                raise ValueError("malformed 7-bit encoded integer")

    def string(self) -> str:
        """Length-prefixed UTF-8 string (BinaryWriter.Write(string) / Lidgren Write(string))."""
        n = self.varint()
        return self.read(n).decode("utf-8")

    def bitarray(self) -> List[bool]:
        """Netcode ``BinaryReader.ReadBitArray``: 7-bit length then LSB-first packed bits."""
        length = self.varint()
        raw = self.read((length + 7) // 8)
        return [bool(raw[i >> 3] >> (i & 7) & 1) for i in range(length)]

    def skippable(self) -> bytes:
        """Netcode ``ReadSkippableBytes``: uint32 length followed by that many bytes."""
        n = self.u32()
        return self.read(n)


class Writer:
    """Append-only little-endian writer."""

    __slots__ = ("buf",)

    def __init__(self) -> None:
        self.buf = bytearray()

    def __len__(self) -> int:
        return len(self.buf)

    def getvalue(self) -> bytes:
        return bytes(self.buf)

    def raw(self, data: bytes) -> None:
        self.buf += data

    def _pack(self, fmt: str, value) -> None:
        self.buf += struct.pack(fmt, value)

    def u8(self, v: int) -> None:
        self._pack("<B", v)

    def bool_(self, v: bool) -> None:
        self._pack("<B", 1 if v else 0)

    def i16(self, v: int) -> None:
        self._pack("<h", v)

    def u16(self, v: int) -> None:
        self._pack("<H", v)

    def i32(self, v: int) -> None:
        self._pack("<i", v)

    def u32(self, v: int) -> None:
        self._pack("<I", v)

    def i64(self, v: int) -> None:
        self._pack("<q", v)

    def u64(self, v: int) -> None:
        self._pack("<Q", v)

    def f32(self, v: float) -> None:
        self._pack("<f", v)

    def f64(self, v: float) -> None:
        self._pack("<d", v)

    def varint(self, v: int) -> None:
        if v < 0:
            raise ValueError("varint must be non-negative")
        while v >= 0x80:
            self.buf.append((v & 0x7F) | 0x80)
            v >>= 7
        self.buf.append(v)

    def string(self, s: str) -> None:
        data = s.encode("utf-8")
        self.varint(len(data))
        self.buf += data

    def bitarray(self, bits: List[bool]) -> None:
        raw = bytearray((len(bits) + 7) // 8)
        for i, bit in enumerate(bits):
            if bit:
                raw[i >> 3] |= 1 << (i & 7)
        self.varint(len(bits))
        self.buf += raw

    def skippable(self, payload: bytes) -> None:
        self.u32(len(payload))
        self.buf += payload
