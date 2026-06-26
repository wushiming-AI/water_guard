#!/usr/bin/env python3
"""
软件著作权申请材料生成器
为 water_guard v4.0 项目生成 3 份源代码 PDF 文档
"""
import os
import sys
from fpdf import FPDF

PROJECT_DIR = r"C:\Users\AA\Desktop\water_guard"
OUTPUT_DIR = os.path.join(PROJECT_DIR, "软著申请材料")
FONT_PATH = r"C:\Windows\Fonts\simfang.ttf"

# ─── 3 个软著的文件分组 ──────────────────────────────────────────────────
COPYRIGHTS = [
    {
        "name": "水域溺水防控AI预警系统",
        "version": "V4.0",
        "files": [
            "backend.py",
            "drowning_yolo.py",
            "pool_map_routes.py",
            "notify_api.py",
            "init.sql",
            "generate_demo.py",
            "generate_icons.py",
            "index.html",
            "dashboard.html",
            "alarms.html",
            "devices.html",
            "users.html",
            "settings.html",
            "pool_map.html",
        ],
    },
    {
        "name": "多模态水域安全智能检测系统",
        "version": "V1.0",
        "files": [
            "trackers/__init__.py",
            "trackers/deep_sort.py",
            "trackers/trajectory.py",
            "models/__init__.py",
            "models/cbam.py",
            "models/cbam_yolo.py",
            "train_cbam.py",
            "fusion/__init__.py",
            "fusion/dual_modal.py",
            "fusion/dual_modal_config.py",
            "fusion/dual_stream.py",
            "fusion/ir_camera_simulator.py",
            "fusion/ir_preprocess.py",
            "ir_fusion.py",
        ],
    },
    {
        "name": "水域安全监控移动端管理系统",
        "version": "V1.0",
        "files": [
            "notify/__init__.py",
            "notify/channels.py",
            "notify/manager.py",
            "notify/settings.py",
            "miniprogram/app.js",
            "miniprogram/app.json",
            "miniprogram/app.wxss",
            "miniprogram/sitemap.json",
            "miniprogram/project.config.json",
            "miniprogram/utils/api.js",
            "miniprogram/custom-tab-bar/index.js",
            "miniprogram/custom-tab-bar/index.json",
            "miniprogram/custom-tab-bar/index.wxml",
            "miniprogram/custom-tab-bar/index.wxss",
            "miniprogram/pages/alarms/alarms.js",
            "miniprogram/pages/alarms/alarms.json",
            "miniprogram/pages/alarms/alarms.wxml",
            "miniprogram/pages/alarms/alarms.wxss",
            "miniprogram/pages/dashboard/dashboard.js",
            "miniprogram/pages/dashboard/dashboard.json",
            "miniprogram/pages/dashboard/dashboard.wxml",
            "miniprogram/pages/dashboard/dashboard.wxss",
            "miniprogram/pages/devices/devices.js",
            "miniprogram/pages/devices/devices.json",
            "miniprogram/pages/devices/devices.wxml",
            "miniprogram/pages/devices/devices.wxss",
            "miniprogram/pages/login/login.js",
            "miniprogram/pages/login/login.json",
            "miniprogram/pages/login/login.wxml",
            "miniprogram/pages/login/login.wxss",
            "miniprogram/pages/settings/settings.js",
            "miniprogram/pages/settings/settings.json",
            "miniprogram/pages/settings/settings.wxml",
            "miniprogram/pages/settings/settings.wxss",
        ],
    },
]

LINES_PER_PAGE = 50
MAX_PAGES = 60  # 不超过60页时全部提交；超过则前30页+后30页


class SourceCodePDF(FPDF):
    """源代码PDF文档，含页眉页脚"""

    def __init__(self, software_name, version):
        super().__init__(format="A4")
        self.software_name = software_name
        self.version = version
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(15, 20, 15)

    def header(self):
        self.set_font("FangSong", "", 9)
        self.cell(0, 6, f"{self.software_name} {self.version} 源程序", align="C")
        self.ln(3)
        self.set_draw_color(100)
        self.set_line_width(0.3)
        self.line(15, 16, 195, 16)
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("FangSong", "", 8)
        self.cell(0, 10, f"第 {self.page_no()} 页", align="C")


def read_all_lines(copyright_info):
    """读取一个软著分组内所有源文件，返回行列表"""
    all_lines = []
    for filepath in copyright_info["files"]:
        full_path = os.path.join(PROJECT_DIR, filepath.replace("/", os.sep))
        if not os.path.exists(full_path):
            print(f"  [跳过] 文件不存在: {filepath}")
            continue
        all_lines.append(f"# ===== 文件: {filepath} =====")
        all_lines.append("")
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n\r")
                if len(line) > 110:
                    line = line[:110] + " ..."
                all_lines.append(line)
        all_lines.append("")
        all_lines.append("")
    return all_lines


def generate_source_code_pdf(copyright_info, index):
    """生成单个软著的源代码PDF"""
    print(f"[{index}/3] {copyright_info['name']} {copyright_info['version']}")

    all_lines = read_all_lines(copyright_info)
    total_lines = len(all_lines)
    total_pages = (total_lines + LINES_PER_PAGE - 1) // LINES_PER_PAGE
    print(f"  总行数: {total_lines}, 总页数: {total_pages}")

    pdf = SourceCodePDF(copyright_info["name"], copyright_info["version"])
    pdf.add_font("FangSong", "", FONT_PATH)

    # 确定页范围
    if total_pages <= MAX_PAGES:
        ranges = [(0, total_lines)]
    else:
        first_end = 30 * LINES_PER_PAGE
        last_start = total_lines - 30 * LINES_PER_PAGE
        ranges = [(0, first_end), (last_start, total_lines)]

    for ri, (start, end) in enumerate(ranges):
        if ri > 0:
            pdf.add_page()
            pdf.set_font("FangSong", "", 14)
            pdf.ln(60)
            pdf.cell(0, 10, "（以下为源程序最后部分）", align="C", ln=True)

        for i in range(start, end, LINES_PER_PAGE):
            page_lines = all_lines[i:i + LINES_PER_PAGE]
            pdf.add_page()
            pdf.set_font("FangSong", "", 7.5)
            for line in page_lines:
                safe = line.replace("\t", "    ")
                try:
                    pdf.cell(0, 4.0, safe, ln=True)
                except Exception:
                    pdf.cell(0, 4.0, safe.encode("ascii", "replace").decode(), ln=True)

    output_name = f"软著{index}_{copyright_info['name']}{copyright_info['version']}_源代码.pdf"
    output_path = os.path.join(OUTPUT_DIR, output_name)
    pdf.output(output_path)
    print(f"  -> {output_path}")
    return output_path


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"输出目录: {OUTPUT_DIR}\n")

    results = []
    for i, cr in enumerate(COPYRIGHTS, 1):
        path = generate_source_code_pdf(cr, i)
        results.append(path)
        print()

    print("=== 3 份源代码 PDF 全部生成完成 ===")
    for p in results:
        size = os.path.getsize(p) / 1024
        print(f"  {os.path.basename(p)}  ({size:.0f} KB)")


if __name__ == "__main__":
    main()
