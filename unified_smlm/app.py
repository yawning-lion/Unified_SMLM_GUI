from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .models import build_default_settings


_DLL_HANDLES = []


def _discover_qt_runtime_paths() -> tuple[list[Path], list[Path], list[Path]]:
    env_root = Path(sys.executable).resolve().parent
    dll_dirs = [
        env_root / "Library" / "bin",
        env_root / "Library" / "mingw-w64" / "bin",
        env_root / "Library" / "usr" / "bin",
        env_root / "Scripts",
        env_root / "Lib" / "site-packages" / "PyQt5" / "Qt5" / "bin",
    ]
    plugin_roots = [
        env_root / "Library" / "plugins",
        env_root / "Lib" / "site-packages" / "PyQt5" / "Qt5" / "plugins",
    ]

    existing_dll_dirs = [path for path in dll_dirs if path.exists()]
    existing_plugin_roots = [path for path in plugin_roots if path.exists()]
    platform_dirs = [path / "platforms" for path in existing_plugin_roots if (path / "platforms").exists()]
    return existing_dll_dirs, existing_plugin_roots, platform_dirs


def _configure_qt_runtime_environment() -> tuple[list[Path], list[Path], list[Path]]:
    existing_dll_dirs, existing_plugin_roots, platform_dirs = _discover_qt_runtime_paths()

    for path in reversed(existing_dll_dirs):
        os.environ["PATH"] = str(path) + os.pathsep + os.environ.get("PATH", "")

    if hasattr(os, "add_dll_directory"):
        for path in existing_dll_dirs:
            try:
                _DLL_HANDLES.append(os.add_dll_directory(str(path)))
            except OSError:
                pass

    if existing_plugin_roots:
        os.environ.setdefault("QT_PLUGIN_PATH", str(existing_plugin_roots[0]))

    if platform_dirs:
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(platform_dirs[0]))

    return existing_dll_dirs, existing_plugin_roots, platform_dirs


def _configure_qt_runtime() -> None:
    _dll_dirs, existing_plugin_roots, _platform_dirs = _configure_qt_runtime_environment()
    from PyQt5 import QtCore

    if existing_plugin_roots:
        QtCore.QCoreApplication.setLibraryPaths([str(path) for path in existing_plugin_roots])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified SMLM control GUI with embedded Micro-Manager backend")
    parser.add_argument("--inspection", action="store_true", help="Force inspection mode on")
    parser.add_argument("--live", action="store_true", help="Request live mode")
    parser.add_argument("--cfg", default="", help="Optional Micro-Manager config file to pre-select")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_qt_runtime()

    from PyQt5 import QtCore, QtWidgets
    from .main_window import UnifiedSMLMMainWindow

    app = QtWidgets.QApplication(argv or sys.argv)
    app.setApplicationName("Unified SMLM Control")
    app.setStyle("Fusion")

    settings = build_default_settings()
    if args.inspection:
        settings.state.inspection_mode = True
    if args.live:
        settings.state.inspection_mode = False
    if args.cfg:
        settings.paths.micromanager_cfg = Path(args.cfg)

    window = UnifiedSMLMMainWindow(settings=settings)
    window.showMaximized()

    auto_close_ms = int(os.environ.get("SMLM_GUI_AUTOCLOSE_MS", "0") or "0")
    if auto_close_ms > 0:
        def _shutdown_for_test() -> None:
            window.close()
            QtCore.QTimer.singleShot(150, app.quit)

        QtCore.QTimer.singleShot(auto_close_ms, _shutdown_for_test)

    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
