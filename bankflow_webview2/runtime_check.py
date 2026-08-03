"""Read-only Microsoft Edge WebView2 Runtime detection for Windows."""

from __future__ import annotations

import os
import platform
import struct
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path


WEBVIEW2_CLIENT_IDS = (
    "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",  # Evergreen Runtime
    "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",  # Edge Beta
    "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",  # Edge Dev
    "{65C35B14-6C1D-4122-AC46-7148CC9D6497}",  # Edge Canary
)


class RuntimeStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    VERSION_UNAVAILABLE = "VERSION_UNAVAILABLE"
    INITIALIZATION_FAILED = "INITIALIZATION_FAILED"


@dataclass(frozen=True)
class RuntimeCheckResult:
    status: RuntimeStatus
    version: str | None
    runtime_architecture: str | None
    python_architecture: str
    system_architecture: str
    windows_version: str
    elapsed_ms: float
    source: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


def _registry_candidates() -> list[tuple[object, str, int, str]]:
    import winreg

    candidates: list[tuple[object, str, int, str]] = []
    views = (winreg.KEY_WOW64_64KEY, "64-bit registry view"), (
        winreg.KEY_WOW64_32KEY,
        "32-bit registry view",
    )
    for root, root_name in (
        (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
        (winreg.HKEY_CURRENT_USER, "HKCU"),
    ):
        for view, view_name in views:
            for client_id in WEBVIEW2_CLIENT_IDS:
                path = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client_id}"
                source = f"{root_name} {view_name}\\{path}"
                candidates.append((root, path, winreg.KEY_READ | view, source))
    return candidates


def _pe_architecture(executable: Path) -> str | None:
    machine_names = {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}
    try:
        with executable.open("rb") as handle:
            handle.seek(0x3C)
            pe_offset = struct.unpack("<I", handle.read(4))[0]
            handle.seek(pe_offset + 4)
            machine = struct.unpack("<H", handle.read(2))[0]
        return machine_names.get(machine, f"PE-0x{machine:04X}")
    except (OSError, struct.error):
        return None


def _runtime_architecture(key: object, version: str) -> str | None:
    import winreg

    try:
        location = str(winreg.QueryValueEx(key, "location")[0]).strip()
    except OSError:
        return None
    executable = Path(location) / version / "msedgewebview2.exe"
    return _pe_architecture(executable)


def check_webview2_runtime() -> RuntimeCheckResult:
    started = time.perf_counter()
    python_architecture = f"{struct.calcsize('P') * 8}-bit"
    system_architecture = (
        os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
        or platform.machine()
        or ("x64" if os.environ.get("ProgramFiles(x86)") else python_architecture)
    )
    windows_version = platform.platform()

    if platform.system() != "Windows":
        return RuntimeCheckResult(
            RuntimeStatus.MISSING,
            None,
            None,
            python_architecture,
            system_architecture,
            windows_version,
            round((time.perf_counter() - started) * 1000, 3),
            message="当前系统不是 Windows，无法使用 Microsoft Edge WebView2。",
        )

    import winreg

    found_without_version: str | None = None
    for root, path, access, source in _registry_candidates():
        try:
            with winreg.OpenKey(root, path, 0, access) as key:
                try:
                    version = str(winreg.QueryValueEx(key, "pv")[0]).strip()
                except OSError:
                    found_without_version = source
                    continue
                if version and version != "0.0.0.0":
                    return RuntimeCheckResult(
                        RuntimeStatus.AVAILABLE,
                        version,
                        _runtime_architecture(key, version),
                        python_architecture,
                        system_architecture,
                        windows_version,
                        round((time.perf_counter() - started) * 1000, 3),
                        source=source,
                        message="Microsoft Edge WebView2 Runtime 可用。",
                    )
                found_without_version = source
        except (FileNotFoundError, PermissionError, OSError):
            continue

    if found_without_version:
        source = found_without_version
        architecture = None
        status = RuntimeStatus.VERSION_UNAVAILABLE
        message = "检测到 Microsoft Edge WebView2 Runtime，但无法读取版本。"
    else:
        source = architecture = None
        status = RuntimeStatus.MISSING
        message = "未检测到 Microsoft Edge WebView2 Runtime，请先安装后再启动。"

    return RuntimeCheckResult(
        status,
        None,
        architecture,
        python_architecture,
        system_architecture,
        windows_version,
        round((time.perf_counter() - started) * 1000, 3),
        source=source,
        message=message,
    )
