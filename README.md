# LifeAfter Image Clicker

Windows desktop tool for matching user-selected image templates in titled windows and sending mouse messages to matching positions. The source is included; the Windows executable can be built locally or downloaded from the GitHub Actions artifact after a successful build.

## Features

- List windows whose title contains `明日之后`; bind multiple windows.
- Add image templates and use OpenCV template matching.
- Adjust the match threshold and scan interval.
- Adjust repeat-click interval, random pixel offset, and randomized pre-click delay.
- Save preferences beside the program.

## Requirements

- Windows 10/11
- Python 3.11 or newer (Windows)

## Run from source

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

## Build the executable

The default build is a folder bundle. It is easier to troubleshoot and avoids extracting every dependency on each launch.

```powershell
.\build_windows.bat
```

The executable and its support files will be in `dist/LifeAfterImageClicker/`. Distribute the entire folder, not just the `.exe`.

To create a single-file executable instead, run `build_onefile_windows.bat`. The one-file build takes longer to start because it unpacks bundled files at launch.

Build on Windows for Windows. PyInstaller does not cross-compile Windows applications from other operating systems.

## GitHub Actions

Push this repository to GitHub. The workflow in `.github/workflows/build-windows.yml` builds the directory bundle on Windows and uploads it as an Actions artifact named `LifeAfterImageClicker-windows`. Download the entire artifact folder.

## Use

1. Start the app and the target game window.
2. Click **刷新窗口**, select one or more matching windows, then click **绑定所选**.
3. Add image templates, adjust threshold and scan interval, and start recognition.
4. Random offset is applied independently to X and Y within `±N` pixels. Delay is sampled uniformly from the configured minimum to maximum milliseconds before each click. Set both delay bounds to `0` to disable the delay.

## Limitations

- The app filters by window title text. If the game uses another title, change the `明日之后` filter in `refresh_windows()` in `main.py`.
- `PrintWindow` may return a blank image for some GPU-rendered windows. Background mouse messages may also be ignored by some games.
- This project is an image-matching desktop utility. Use it only where automation is permitted. The user is responsible for compliance with the target application's rules.

## License

MIT. See [LICENSE](LICENSE).

