"""
微信小程序 tabBar 图标生成脚本
运行：python generate_icons.py
会在 miniprogram/assets/icons/ 下生成 8 个 81x81 PNG 图标
"""
import struct, zlib, base64, os, subprocess, sys

def make_png(w=81, h=81, r=127, g=127, b=127):
    """生成指定颜色的纯色 PNG"""
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)
    raw = b''
    for y in range(h):
        raw += b'\x00'
        for x in range(w):
            raw += bytes([r, g, b, 255])
    compressed = zlib.compress(raw)
    sig = b'\x89PNG\r\n\x1a\n'
    return sig + chunk(b'IHDR', ihdr_data) + chunk(b'IDAT', compressed) + chunk(b'IEND', b'')

ICONS = {
    'monitor':         (127, 140, 160),   # 灰色（未选中）
    'monitor_active':  (52,  152, 219),   # 蓝色（选中）
    'alarm':           (127, 140, 160),
    'alarm_active':    (231,  76,  60),   # 红色（预警选中）
    'device':          (127, 140, 160),
    'device_active':   (52,  152, 219),
    'settings':        (127, 140, 160),
    'settings_active': (52,  152, 219),
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'miniprogram', 'assets', 'icons')

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"图标输出目录: {OUT_DIR}\n")

    for name, (r, g, b) in ICONS.items():
        png_data = make_png(81, 81, r, g, b)
        path = os.path.join(OUT_DIR, f'{name}.png')
        with open(path, 'wb') as f:
            f.write(png_data)
        print(f"  ✓ {name}.png ({len(png_data)} bytes)")

    print(f"\n全部完成！共 {len(ICONS)} 个图标已生成。")
    print("现在可以用微信开发者工具导入 miniprogram/ 目录了。")

if __name__ == '__main__':
    main()
