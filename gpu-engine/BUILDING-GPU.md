# Building the graphics-card speech engine

The app transcribes on the graphics card using **whisper.cpp built with
Vulkan**, through the **pywhispercpp** Python bridge. Vulkan works with AMD,
NVIDIA and Intel cards. No official Windows Vulkan build is published, so it's
built from source. `build.py` bundles it into the `.exe` automatically when
it's installed in the Python doing the build. Without it, the app builds and
runs processor-only.

These steps were used on 2026-10-08 (Windows 11, AMD RX 7900 GRE,
Python 3.14).

## 1. Tools (one time)

```
winget install --id Kitware.CMake -e
winget install --id KhronosGroup.VulkanSDK -e
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--wait --quiet --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

Into the Python you build with:
`pip install faster-whisper requests pyinstaller pillow ninja platformdirs tqdm`.

## 2. Source

- pywhispercpp at commit `f7bf62118c0a33a43cf8aabb58eef16cea5d16c4`.
- Its `whisper.cpp` submodule at commit
  `f24588a272ae8e23280d9c220536437164e6ed28`.

On Windows, clone with `git config core.longpaths true`. whisper.cpp has very
long paths in its Android examples.

Then apply `pywhispercpp-bytes-and-no-speech.patch`, from this folder, inside
the pywhispercpp folder:

```
git apply pywhispercpp-bytes-and-no-speech.patch
```

The patch makes two changes:
- **Token text comes back as raw bytes.** A token can carry half of a Chinese
  character, and decoding each token on its own garbled it ("�").
- **It exposes `whisper_full_get_segment_no_speech_prob`,** so text invented
  over background noise (Whisper's habit of hearing "Thank you.") can be
  filtered.

## 3. Build

Build from a **short folder** such as `C:\Users\<you>\lscb\pw`. The
Vulkan-shader tool builds deep inside the build tree, and from a long path the
compiler hits Windows' 260-character limit. From a "Developer" environment
(`vcvars64.bat`), with the Vulkan SDK's `Bin` folder on `PATH`:

```
set CMAKE_GENERATOR=Ninja
set CC=cl
set CXX=cl
set GGML_VULKAN=1
set CMAKE_ARGS=-DGGML_VULKAN=ON -DWHISPER_BUILD_EXAMPLES=OFF -DWHISPER_BUILD_TESTS=OFF
python -m pip wheel . -w dist --no-deps -v
```

- **Ninja instead of the Visual Studio generator:** CMake couldn't find the
  freshly installed Build Tools through the Visual Studio generator, but the
  `vcvars64` environment works fine with Ninja.
- **The last step ("repair_wheel") fails** unless the optional `repairwheel`
  tool is installed. The compiled engine is fine regardless.

## 4. Install into the build Python

Copy these into the Python's `site-packages`:
- `build\lib.win-amd64-cpython-3xx\pywhispercpp\` (the package)
- `build\lib.win-amd64-cpython-3xx\_pywhispercpp.cp3xx-win_amd64.pyd`
- `build\temp.win-amd64-cpython-3xx\Release\_pywhispercpp\bin\*.dll`
  (`whisper.dll`, `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll`, `ggml-vulkan.dll`)

Then add a minimal `pywhispercpp-<version>.dist-info\METADATA` (Name and
Version lines). The package looks up its own version.

## 5. Check

```python
import sys
from pywhispercpp.model import Model
Model("ggml-small.bin", redirect_whispercpp_logs_to=sys.stdout)
```

The log should say `ggml_vulkan: 0 = <your graphics card>` and
`using Vulkan0 backend`.

The model file is `ggml-small.bin` from
`https://huggingface.co/ggerganov/whisper.cpp`. The app downloads it into
`_data\models` by itself if it's missing.
