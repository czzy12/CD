from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect


_ORIGINAL_OPEN = pdfplumber.open
_PASSWORDS: dict[str, str] = {}
_INSTALLED = False
PASSWORD_ERROR_MARKERS = (
    "password",
    "encrypt",
    "encrypted",
    "decrypt",
    "notallowed",
    "not allowed",
    "text extraction",
    "pdfpasswordincorrect",
    "密码",
    "加密",
    "权限",
)


def _key(path: str | Path) -> str:
    return str(Path(path).resolve()).lower()


def register_pdf_passwords(passwords: dict[str | Path, str]) -> None:
    for path, password in passwords.items():
        if password:
            _PASSWORDS[_key(path)] = password


def password_for(path: str | Path) -> str:
    return _PASSWORDS.get(_key(path), "")


def _open_with_registered_password(*args: Any, **kwargs: Any):
    if args and not kwargs.get("password"):
        candidate = args[0]
        if isinstance(candidate, (str, Path)):
            password = password_for(candidate)
            if password:
                kwargs["password"] = password
    return _ORIGINAL_OPEN(*args, **kwargs)


def install_pdf_password_support() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    pdfplumber.open = _open_with_registered_password
    _INSTALLED = True


def is_pdf_password_error(exc: BaseException, _seen: set[int] | None = None) -> bool:
    _seen = _seen or set()
    if id(exc) in _seen:
        return False
    _seen.add(id(exc))
    if isinstance(exc, PDFPasswordIncorrect):
        return True
    text = f"{type(exc).__name__}: {exc!r}: {getattr(exc, 'args', '')!r}".lower()
    if any(marker in text for marker in PASSWORD_ERROR_MARKERS):
        return True
    for nested in (getattr(exc, "__cause__", None), getattr(exc, "__context__", None), *getattr(exc, "args", ())):
        if isinstance(nested, BaseException) and is_pdf_password_error(nested, _seen):
            return True
    return False


def _touch_pdf(path: str | Path, password: str | None = None) -> bool:
    kwargs = {"password": password} if password else {}
    with _ORIGINAL_OPEN(str(path), **kwargs) as pdf:
        encrypted = getattr(getattr(pdf, "doc", None), "encryption", None) is not None
        if pdf.pages:
            page = pdf.pages[0]
            _ = page.chars
            _ = page.extract_text() or ""
        return encrypted


def pdf_requires_password(path: str | Path) -> bool:
    try:
        return _touch_pdf(path)
    except Exception as exc:
        if not is_pdf_password_error(exc):
            raise
        return True


def validate_pdf_password(path: str | Path, password: str) -> bool:
    try:
        _touch_pdf(path, password=password)
        return True
    except Exception as exc:
        if not is_pdf_password_error(exc):
            raise
        return False
