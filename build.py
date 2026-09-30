"""
Builds "LoL Scrim Comms.exe" (developer use).

Run with a Python that has the requirements installed plus PyInstaller and
Pillow:
    python build.py

It makes the app icon, packages everything with PyInstaller, then installs
the result into the app folder next to this source folder, replacing only
the program files. Your data (recordings, transcripts, settings, the speech
model) is never touched.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from common import APP_NAME

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
APP_FOLDER = HERE.parent / APP_NAME


def make_icon(path):
    """A simple icon: sound-wave bars on a dark rounded square."""
    from PIL import Image, ImageDraw
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, size - 8, size - 8), radius=52, fill=(26, 26, 25, 255))
    bars = [0.30, 0.55, 0.85, 0.60, 0.95, 0.50, 0.28]
    width, gap = 18, 10
    left = (size - (len(bars) * width + (len(bars) - 1) * gap)) // 2
    for i, h in enumerate(bars):
        height = int(h * 140)
        x = left + i * (width + gap)
        top = size // 2 - height // 2
        color = (57, 135, 229, 255) if i != 4 else (237, 161, 0, 255)
        d.rounded_rectangle((x, top, x + width, top + height), radius=width // 2, fill=color)
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


RUNTIME_DLLS = ["msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll",
                "vcruntime140_1.dll", "concrt140.dll"]


def file_version(path):
    """Windows file version as a tuple, e.g. (14, 44, 35211, 0)."""
    import ctypes
    size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return (0,)
    data = ctypes.create_string_buffer(size)
    ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, data)
    info, length = ctypes.c_void_p(), ctypes.c_uint()
    ctypes.windll.version.VerQueryValueW(data, "\\", ctypes.byref(info), ctypes.byref(length))
    ms, ls = ctypes.cast(info, ctypes.POINTER(ctypes.c_uint32 * 4)).contents[2:4]
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


def refresh_runtime(internal):
    """PyInstaller can bundle an old copy of Microsoft's C++ runtime (it
    picked up a 2017 msvcp140.dll), which makes the speech engine crash on
    load. Replace any bundled copy with the newest one on this PC. These
    files are made to be shipped alongside apps."""
    system = Path(r"C:\Windows\System32")
    for name in RUNTIME_DLLS:
        bundled_copy, newest = internal / name, system / name
        if bundled_copy.exists() and newest.exists() and file_version(newest) > file_version(bundled_copy):
            shutil.copy2(newest, bundled_copy)
            print(f"  Updated {name} to {'.'.join(map(str, file_version(newest)))}")


def main():
    BUILD.mkdir(exist_ok=True)
    icon = BUILD / "icon.ico"
    make_icon(icon)
    sep = ";" if sys.platform == "win32" else ":"
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--name", APP_NAME, "--windowed", "--onedir",
        "--icon", str(icon),
        "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--add-data", f"{HERE / 'dashboard_template.html'}{sep}.",
        "--add-data", f"{HERE / 'defaults'}{sep}defaults",
        "--add-data", f"{icon}{sep}.",
        "--collect-all", "faster_whisper",
        "--collect-all", "ctranslate2",
        "--collect-all", "onnxruntime",
        "--collect-all", "tokenizers",
        "--hidden-import", "poller", "--hidden-import", "transcriber", "--hidden-import", "analytics",
        str(HERE / "app.py"),
    ]
    print("Packaging… (this takes a few minutes)")
    subprocess.run(command, check=True, cwd=HERE)

    built = BUILD / "dist" / APP_NAME
    if sys.platform == "win32":
        refresh_runtime(built / "_internal")
    APP_FOLDER.mkdir(exist_ok=True)
    internal = APP_FOLDER / "_internal"
    if internal.exists():
        shutil.rmtree(internal)
    shutil.copytree(built / "_internal", internal)
    shutil.copy2(built / f"{APP_NAME}.exe", APP_FOLDER / f"{APP_NAME}.exe")
    shutil.copy2(HERE / "How to use.txt", APP_FOLDER / "How to use.txt")
    shutil.copy2(HERE / "CHANGELOG.md", APP_FOLDER / "Changelog.md")
    print(f"Installed into {APP_FOLDER}")


if __name__ == "__main__":
    main()
