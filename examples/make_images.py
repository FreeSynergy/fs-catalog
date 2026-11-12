#!/usr/bin/env python3
"""Writes the example pictures (images/*.png): simple generated patterns, made for this repository, no third-party material.
They are dedicated to the public domain (CC0-1.0). Pure standard library; the output is deterministic.
Run: python3 -I examples/make_images.py"""
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))


def png(path, w, h, pixel):
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(w)) for y in range(h))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(os.path.join(HERE, "images", path), "wb") as f:
        f.write(data)


def icon(base):
    r, g, b = base
    return lambda x, y: (r, g, b) if (x - 32) ** 2 + (y - 32) ** 2 < 28 ** 2 else (255, 255, 255)


def shot(x, y):  # a window-like picture: title bar, side bar, content lines
    if y < 20:
        return (60, 90, 140)
    if x < 80:
        return (225, 232, 242)
    return (70, 70, 70) if (y // 12) % 3 == 0 and x > 100 and x < 300 else (250, 250, 250)


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "images"), exist_ok=True)
    png("example-program-icon.png", 64, 64, icon((40, 110, 200)))
    png("example-server-icon.png", 64, 64, icon((200, 110, 40)))
    png("example-icons-icon.png", 64, 64, icon((60, 160, 90)))
    png("example-program-screenshot.png", 320, 200, shot)
