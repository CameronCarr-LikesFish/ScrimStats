"""
Builds "ScrimStats.exe" (developer use).

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


def download_champion_icons(folder):
    """Every champion's square icon from Riot's Data Dragon, shipped inside
    the app so the dashboard has them offline from the start. (Riot's art:
    downloaded at build time, never committed to the repository.)"""
    import json
    from concurrent.futures import ThreadPoolExecutor
    import requests
    version = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10).json()[0]
    data = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json",
                        timeout=20).json()["data"]
    folder.mkdir(parents=True, exist_ok=True)
    ids = {c["name"]: c["id"] for c in data.values()}

    def fetch(champ_id):
        target = folder / f"{champ_id}.png"
        if not target.exists():
            image = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champ_id}.png",
                                 timeout=20)
            if image.ok and image.content[:4] == b"\x89PNG":
                target.write_bytes(image.content)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(fetch, ids.values()))
    (folder / "ids.json").write_text(json.dumps({"version": version, "ids": ids}, indent=0), encoding="utf-8")
    print(f"  Champion icons: {sum(1 for _ in folder.glob('*.png'))} (patch {version})")


def gpu_engine_args(sep):
    """Bundle the graphics-card engine (pywhispercpp: whisper.cpp built with
    Vulkan) when it's installed in this Python. It's built from source; see
    BUILDING-GPU.md. Without it the app simply uses the processor."""
    try:
        import _pywhispercpp
        import pywhispercpp  # noqa: F401
    except ImportError:
        print("  Graphics-card engine (pywhispercpp) not installed: building processor-only.")
        return []
    engine_dir = Path(_pywhispercpp.__file__).parent
    dlls = [p for p in engine_dir.glob("*.dll") if p.name.startswith(("whisper", "ggml"))]
    print("  Bundling graphics-card engine:", ", ".join(sorted(p.name for p in dlls)))
    args = ["--collect-all", "pywhispercpp", "--hidden-import", "_pywhispercpp",
            "--collect-all", "platformdirs",
            "--add-binary", f"{_pywhispercpp.__file__}{sep}."]
    for dll in dlls:
        args += ["--add-binary", f"{dll}{sep}."]
    return args


def main():
    icons = BUILD / "champions"
    download_champion_icons(icons)
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
        "--add-data", f"{HERE / 'ui'}{sep}ui",
        "--add-data", f"{icons}{sep}champions",
        # The app window: pywebview, using Windows' built-in WebView2 browser
        # engine through pythonnet.
        "--collect-all", "webview", "--collect-all", "pythonnet", "--collect-all", "clr_loader",
        "--collect-all", "faster_whisper",
        "--collect-all", "ctranslate2",
        "--collect-all", "onnxruntime",
        "--collect-all", "tokenizers",
        "--hidden-import", "poller", "--hidden-import", "transcriber", "--hidden-import", "analytics", "--hidden-import", "display",
    ]
    command += gpu_engine_args(sep)
    command.append(str(HERE / "app.py"))
    print("Packaging… (this takes a few minutes)")
    subprocess.run(command, check=True, cwd=HERE)

    built = BUILD / "dist" / APP_NAME
    if sys.platform == "win32":
        refresh_runtime(built / "_internal")
    if sys.platform == "win32" and app_running():
        # Replacing files the open app is using fails halfway and leaves the
        # installed app broken, so stop before touching anything.
        sys.exit(f"{APP_NAME} is open. Close it, then run this again (the build itself is done, "
                 f"in {built}).")
    APP_FOLDER.mkdir(exist_ok=True)
    internal = APP_FOLDER / "_internal"
    if internal.exists():
        shutil.rmtree(internal)
    shutil.copytree(built / "_internal", internal)
    shutil.copy2(built / f"{APP_NAME}.exe", APP_FOLDER / f"{APP_NAME}.exe")
    shutil.copy2(HERE / "How to use.txt", APP_FOLDER / "How to use.txt")
    shutil.copy2(HERE / "CHANGELOG.md", APP_FOLDER / "Changelog.md")
    print(f"Installed into {APP_FOLDER}")


def app_running():
    found = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {APP_NAME}.exe"],
                           capture_output=True, text=True).stdout
    return f"{APP_NAME}.exe".lower() in found.lower()


if __name__ == "__main__":
    main()
