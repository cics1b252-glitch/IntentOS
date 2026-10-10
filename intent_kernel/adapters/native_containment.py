"""FRONT-M35: native handle-relative filesystem containment (Windows / POSIX).

    PREVENTIVE_CONTAINMENT != POST_EFFECT_DETECTION

M34 could only DETECT a write that a concurrent hostile process had already
redirected: it resolved a path string, checked it, then wrote by path. Between
those steps the path could be re-pointed. This module removes the race by
never resolving the target from a path string at write time. Instead it opens
the authorized root ONCE into an OS directory HANDLE and creates the file
*relative to that handle*. A rename/replacement of any parent directory
component after the handle is opened cannot redirect the subsequent create,
because the kernel resolves the operation against the handle's identity, not
against the name.

MECHANISM BY PLATFORM
    POSIX : ``openat(dirfd, name, O_NOFOLLOW|O_CREAT|O_EXCL)``.
             Handle-relative, refuses to traverse a symlink at the final
             component, exclusive create.
    WINDOWS: ``NtCreateFile`` (ntdll) with ``OBJECT_ATTRIBUTES.RootDirectory``
             bound to an opened directory handle, plus
             ``FILE_OPEN_REPARSE_POINT | FILE_NON_DIRECTORY_FILE`` and
             ``FILE_CREATE``. Handle-relative, refuses to traverse a reparse
             point (symlink/junction), exclusive create.

CONTAINMENT MODEL
    The relative name is restricted to a SINGLE path component. With no
    intermediate components there is nothing for the resolver to walk, so
    symlink/junction redirection has no component to exploit - and
    FILE_OPEN_REPARSE_POINT additionally prevents the leaf itself from being
    traversed.

FAIL-CLOSED
    Where the platform cannot supply the primitives, construction of the
    containment raises. There is no silent fallback to a weaker mode.

STABILITY DISCLOSURE
    ``NtCreateFile`` is a native ntdll export and is UNDOCUMENTED. It is
    stable in practice across supported Windows releases but carries no
    Microsoft API-compatibility guarantee. Callers requiring a documented
    surface must treat this as a risk, not as an API contract.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

IS_WINDOWS = sys.platform == "win32"


class NativeContainmentUnavailable(RuntimeError):
    """The platform cannot provide handle-relative containment. Fail closed."""


class ContainmentViolation(RuntimeError):
    """A native containment precondition was violated. No effect occurred."""


# ---------------------------------------------------------------------------
# Capability matrix (probed, never assumed)
# ---------------------------------------------------------------------------

def probe_windows() -> dict:
    if not IS_WINDOWS:
        return {}
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    return {
        "CreateFileW": hasattr(k32, "CreateFileW"),
        "GetFileInformationByHandle": hasattr(k32, "GetFileInformationByHandle"),
        "GetFileInformationByHandleEx": hasattr(k32, "GetFileInformationByHandleEx"),
        "NtCreateFile": hasattr(ntdll, "NtCreateFile"),
        "NtQueryInformationFile": hasattr(ntdll, "NtQueryInformationFile"),
    }


def probe_posix() -> dict:
    if IS_WINDOWS:
        return {}
    return {
        "openat_dir_fd": os.open in os.supports_dir_fd,
        "O_NOFOLLOW": hasattr(os, "O_NOFOLLOW"),
        "O_DIRECTORY": hasattr(os, "O_DIRECTORY"),
    }


def platform_capabilities() -> dict:
    """Machine-checked capability matrix for THIS interpreter/platform."""
    if IS_WINDOWS:
        caps = probe_windows()
        caps["mechanism"] = "NtCreateFile(OBJECT_ATTRIBUTES.RootDirectory)"
        caps["preventive"] = bool(
            caps.get("NtCreateFile") and caps.get("CreateFileW")
        )
    else:
        caps = probe_posix()
        caps["mechanism"] = "openat(dirfd, O_NOFOLLOW|O_CREAT|O_EXCL)"
        caps["preventive"] = bool(
            caps.get("openat_dir_fd") and caps.get("O_NOFOLLOW")
        )
    caps["platform"] = sys.platform
    return caps


#: What this platform can genuinely PREVENT (not merely detect).
PREVENTIVE_CONTAINMENT: bool = bool(platform_capabilities().get("preventive"))


# ---------------------------------------------------------------------------
# Windows native bindings
# ---------------------------------------------------------------------------

FILE_GENERIC_READ = 0x00120089
FILE_GENERIC_WRITE = 0x00120116
#: FILE_READ_ATTRIBUTES is NOT part of FILE_GENERIC_WRITE, but both
#: GetFileInformationByHandle and GetFileInformationByHandleEx require it.
#: Without it the identity/reparse proofs would be unable to run.
FILE_READ_ATTRIBUTES = 0x00000080
CREATE_ACCESS = FILE_GENERIC_WRITE | FILE_READ_ATTRIBUTES
GENERIC_READ = 0x80000000
OBJ_CASE_INSENSITIVE = 0x40
FILE_CREATE, FILE_OPEN = 2, 1
FILE_SYNCHRONOUS_IO_NONALERT = 0x20
FILE_NON_DIRECTORY_FILE = 0x40
FILE_OPEN_REPARSE_POINT = 0x00200000
FILE_DIRECTORY_FILE = 0x00000001
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_ATTRIBUTE_NORMAL = 0x00000080
SHARE_READ = 0x00000001
OPEN_EXISTING = 3
STATUS_OBJECT_NAME_COLLISION = 0xC0000035
STATUS_OBJECT_PATH_NOT_FOUND = 0xC0000033
STATUS_OBJECT_NAME_INVALID = 0xC0000033
STATUS_DIRECTORY_NOT_EMPTY = 0xC0000101


if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as _w

    class _UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", _w.USHORT),
            ("MaximumLength", _w.USHORT),
            ("Buffer", ctypes.c_wchar_p),
        ]

    class _OBJECT_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("Length", _w.ULONG),
            ("RootDirectory", _w.HANDLE),
            ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
            ("Attributes", _w.ULONG),
            ("SecurityDescriptor", ctypes.c_void_p),
            ("SecurityQualityOfService", ctypes.c_void_p),
        ]

    class _IO_STATUS_BLOCK(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", _w.DWORD),
            ("ftCreationTime", _w.FILETIME),
            ("ftLastAccessTime", _w.FILETIME),
            ("ftLastWriteTime", _w.FILETIME),
            ("dwVolumeSerialNumber", _w.DWORD),
            ("nFileSizeHigh", _w.DWORD),
            ("nFileSizeLow", _w.DWORD),
            ("nNumberOfLinks", _w.DWORD),
            ("nFileIndexHigh", _w.DWORD),
            ("nFileIndexLow", _w.DWORD),
        ]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(_w.HANDLE), _w.DWORD, ctypes.POINTER(_OBJECT_ATTRIBUTES),
        ctypes.POINTER(_IO_STATUS_BLOCK), ctypes.c_void_p, _w.ULONG, _w.ULONG,
        _w.ULONG, _w.ULONG, ctypes.c_void_p, _w.ULONG,
    ]
    _ntdll.NtCreateFile.restype = ctypes.c_long
    _k32.GetFileInformationByHandle.argtypes = [
        _w.HANDLE, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)
    ]
    _k32.GetFileInformationByHandle.restype = _w.BOOL


# ---------------------------------------------------------------------------
# Handle-relative identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FileIdentity:
    """(volume serial, file index high, file index low) - stable per object."""

    volume_serial: int
    file_index_high: int
    file_index_low: int

    def same_object(self, other: "FileIdentity") -> bool:
        return self == other


def _identity_from_handle(handle) -> FileIdentity:
    if IS_WINDOWS:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not _k32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ContainmentViolation("cannot read file identity")
        return FileIdentity(
            info.dwVolumeSerialNumber, info.nFileIndexHigh, info.nFileIndexLow
        )
    st = os.fstat(handle)
    return FileIdentity(st.st_dev, (st.st_ino >> 32) & 0xFFFFFFFF, st.st_ino & 0xFFFFFFFF)


def _is_reparse_point_windows(handle) -> bool:
    """True when the opened object is a reparse point (symlink/junction)."""
    import ctypes

    class _FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", ctypes.c_ulong),
            ("ReparseTag", ctypes.c_ulong),
        ]

    _k32.GetFileInformationByHandleEx.argtypes = [
        _w.HANDLE, ctypes.c_int, ctypes.c_void_p, _w.DWORD
    ]
    _k32.GetFileInformationByHandleEx.restype = _w.BOOL
    _k32.WriteFile.argtypes = [
        _w.HANDLE, ctypes.c_void_p, _w.DWORD, ctypes.c_void_p, ctypes.c_void_p
    ]
    _k32.WriteFile.restype = _w.BOOL
    _k32.CreateFileW.restype = _w.HANDLE
    _k32.CloseHandle.argtypes = [_w.HANDLE]
    _k32.CloseHandle.restype = _w.BOOL

    info = _FILE_ATTRIBUTE_TAG_INFO()
    ok = _k32.GetFileInformationByHandleEx(
        handle, 0x9, ctypes.byref(info), ctypes.sizeof(info)
    )
    if not ok:
        raise ContainmentViolation("cannot query reparse tag")
    return info.ReparseTag != 0


# ---------------------------------------------------------------------------
# The containment primitive
# ---------------------------------------------------------------------------

class NativeContainment:
    """Handle-relative, reparse-refusing, exclusive create.

    Construction opens and pins the authorized root as an OS handle. Every
    subsequent create is issued RELATIVE TO THAT HANDLE, so no parent
    directory replacement can redirect it.
    """

    def __init__(self, authorized_root: Path) -> None:
        caps = platform_capabilities()
        if not caps.get("preventive"):
            raise NativeContainmentUnavailable(
                f"platform lacks handle-relative containment primitives: {caps}"
            )
        self._root = Path(authorized_root).resolve()
        if not self._root.is_dir():
            raise ContainmentViolation("authorized root is not a directory")
        self.caps = caps
        self._root_handle = None
        self.root_identity: Optional[FileIdentity] = None
        self._open_root()

    # -- root handle lifecycle ------------------------------------------
    def _open_root(self) -> None:
        if IS_WINDOWS:
            handle = _k32.CreateFileW(
                str(self._root), GENERIC_READ, SHARE_READ, None, OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS, None,
            )
            invalid = ctypes.c_void_p(-1).value
            if handle is None or handle == invalid:
                raise ContainmentViolation("cannot open authorized root handle")
            self._root_handle = handle
            if _is_reparse_point_windows(handle):
                _k32.CloseHandle(handle)
                raise ContainmentViolation("authorized root is a reparse point")
        else:
            self._root_handle = os.open(
                self._root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
        self.root_identity = _identity_from_handle(self._root_handle)

    def assert_root_unchanged(self) -> None:
        """Detect root replacement. PREVENTION does not rely on this; it is a
        secondary assertion that the pinned handle still refers to the same
        directory object we authorized."""
        if IS_WINDOWS:
            current = _identity_from_handle(self._root_handle)
        else:
            current = _identity_from_handle(self._root_handle)
        if not self.root_identity.same_object(current):
            raise ContainmentViolation("authorized root handle identity changed")

    # -- the contained effect -------------------------------------------
    @staticmethod
    def _validate_leaf(name: str) -> None:
        """Single-component relative name only. No separators, no drive, no dot."""
        if not name or name in (".", ".."):
            raise ContainmentViolation("empty or dot-relative leaf")
        if "/" in name or "\\" in name:
            raise ContainmentViolation(
                "multi-component relative name is refused: intermediate "
                "resolution would reintroduce a traversal surface"
            )
        if os.path.isabs(name) or ":" in name:
            raise ContainmentViolation("absolute or drive-qualified leaf refused")
        if "\x00" in name:
            raise ContainmentViolation("NUL in leaf")

    def create_exclusive(self, leaf: str, content: bytes) -> FileIdentity:
        """Create ``leaf`` relative to the pinned root handle, exclusively.

        Returns the identity of the handle the kernel actually gave us.
        Raises ContainmentViolation on any refusal - the caller must treat
        that as "no effect occurred".
        """
        self._validate_leaf(leaf)
        if IS_WINDOWS:
            return self._create_exclusive_windows(leaf, content)
        return self._create_exclusive_posix(leaf, content)

    def _create_exclusive_windows(self, leaf: str, content: bytes) -> FileIdentity:
        import ctypes

        buf = ctypes.create_unicode_buffer(leaf)
        us = _UNICODE_STRING(
            len(leaf) * 2, len(leaf) * 2 + 2, ctypes.cast(buf, ctypes.c_wchar_p)
        )
        oa = _OBJECT_ATTRIBUTES(
            ctypes.sizeof(_OBJECT_ATTRIBUTES), self._root_handle,
            ctypes.pointer(us), OBJ_CASE_INSENSITIVE, None, None,
        )
        iosb = _IO_STATUS_BLOCK()
        handle = ctypes.wintypes.HANDLE()
        status = _ntdll.NtCreateFile(
            ctypes.byref(handle), CREATE_ACCESS, ctypes.byref(oa),
            ctypes.byref(iosb), None, FILE_ATTRIBUTE_NORMAL, 0, FILE_CREATE,
            FILE_NON_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT
            | FILE_SYNCHRONOUS_IO_NONALERT,
            None, 0,
        )
        unsigned = status & 0xFFFFFFFF
        if unsigned == STATUS_OBJECT_NAME_COLLISION:
            raise ContainmentViolation("target-exists-exclusive-create-refused")
        if unsigned != 0:
            raise ContainmentViolation(f"NtCreateFile refused status=0x{unsigned:08X}")
        try:
            if _is_reparse_point_windows(handle):
                raise ContainmentViolation("refused: created object is a reparse point")
            identity = _identity_from_handle(handle)
            payload = ctypes.create_string_buffer(content, len(content))
            written = _w.DWORD(0)
            ok = _k32.WriteFile(
                handle, payload, len(content), ctypes.byref(written), None
            )
            if not ok or written.value != len(content):
                raise ContainmentViolation(
                    f"short write: ok={bool(ok)} wrote={written.value} "
                    f"expected={len(content)}"
                )
        except Exception:
            _k32.CloseHandle(handle)
            raise
        _k32.CloseHandle(handle)
        return identity

    def _create_exclusive_posix(self, leaf: str, content: bytes) -> FileIdentity:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(leaf, flags, 0o600, dir_fd=self._root_handle)
        try:
            identity = _identity_from_handle(fd)
            os.write(fd, content)
        except Exception:
            os.close(fd)
            raise
        os.close(fd)
        return identity

    def open_existing_relative(self, leaf: str) -> FileIdentity:
        """Open an existing leaf relative to the pinned handle (no reparse)."""
        self._validate_leaf(leaf)
        if IS_WINDOWS:
            import ctypes

            buf = ctypes.create_unicode_buffer(leaf)
            us = _UNICODE_STRING(
                len(leaf) * 2, len(leaf) * 2 + 2, ctypes.cast(buf, ctypes.c_wchar_p)
            )
            oa = _OBJECT_ATTRIBUTES(
                ctypes.sizeof(_OBJECT_ATTRIBUTES), self._root_handle,
                ctypes.pointer(us), OBJ_CASE_INSENSITIVE, None, None,
            )
            iosb = _IO_STATUS_BLOCK()
            handle = ctypes.wintypes.HANDLE()
            status = _ntdll.NtCreateFile(
                ctypes.byref(handle), FILE_GENERIC_READ, ctypes.byref(oa),
                ctypes.byref(iosb), None, 0, SHARE_READ, FILE_OPEN,
                FILE_NON_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT
                | FILE_SYNCHRONOUS_IO_NONALERT,
                None, 0,
            )
            unsigned = status & 0xFFFFFFFF
            if unsigned != 0:
                raise ContainmentViolation(
                    f"NtCreateFile(FILE_OPEN) refused status=0x{unsigned:08X}"
                )
            try:
                if _is_reparse_point_windows(handle):
                    raise ContainmentViolation("leaf is a reparse point")
                return _identity_from_handle(handle)
            finally:
                _k32.CloseHandle(handle)
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self._root_handle)
        try:
            return _identity_from_handle(fd)
        finally:
            os.close(fd)

    def close(self) -> None:
        if self._root_handle is None:
            return
        if IS_WINDOWS:
            _k32.CloseHandle(self._root_handle)
        else:
            os.close(self._root_handle)
        self._root_handle = None

    def __enter__(self) -> "NativeContainment":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
# ---------------------------------------------------------------------------
# Experimental governed executor (M35-C).  Binds native containment to the
# M34 authority model WITHOUT altering the M34 adapter.
# ---------------------------------------------------------------------------

class NativeEffectDenied(RuntimeError):
    """Effect refused before any host mutation. Carries a stable code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class NativeCreateTestFileExecutor:
    """CREATE_TEST_FILE via PREVENTIVE handle-relative containment.

    Authority is re-proven at effect time exactly as in M34 (same ceiling,
    same digest binding, same validity window). What changes is the write
    mechanism: it is issued against a pinned directory handle, so a
    concurrent replacement of any parent path component cannot redirect it.
    """

    CAPABILITY = "m34.create_test_file"
    OPERATION = "CREATE_TEST_FILE"

    def __init__(self, grant: Any, containment: Optional[NativeContainment] = None):
        from intent_kernel.adapters.local_filesystem import CreateTestFileAuthority

        if not isinstance(grant, CreateTestFileAuthority):
            raise NativeEffectDenied("grant-type-invalid")
        self._grant = grant
        self._leaf = Path(grant.authorized_target).name
        self._owns_containment = containment is None
        self.containment = containment or NativeContainment(grant.authorized_root)
        self.effect_calls = 0
        self.denials: list = []

    def prove(self) -> bytes:
        """Re-prove the M34 authority chain. Raises NativeEffectDenied."""
        from intent_kernel.adapters.local_filesystem import (
            CreateTestFileDenied,
            CreateTestFileAuthority,
        )

        try:
            self._grant.prove(self._leaf, self._expected)
        except CreateTestFileDenied as exc:
            raise NativeEffectDenied(exc.code, exc.detail) from exc

    def execute(self, content: bytes) -> FileIdentity:
        from intent_kernel.adapters.local_filesystem import CreateTestFileDenied

        self._expected = content
        if self._grant.revoked:
            self.denials.append("authority-revoked")
            raise NativeEffectDenied("authority-revoked")
        if self._grant.authority is None:
            self.denials.append("authority-missing")
            raise NativeEffectDenied("authority-missing")
        try:
            # Same authority proof as M34: capability, operation, window,
            # digest, exact target, overwrite.
            self._grant.prove(self._leaf, content)
        except CreateTestFileDenied as exc:
            self.denials.append(exc.code)
            raise NativeEffectDenied(exc.code, exc.detail) from exc

        try:
            identity = self.containment.create_exclusive(self._leaf, content)
        except ContainmentViolation as exc:
            self.denials.append(str(exc))
            raise NativeEffectDenied("containment-violation", str(exc)) from exc
        self.effect_calls += 1
        return identity

    def close(self) -> None:
        if self._owns_containment:
            self.containment.close()

    def __enter__(self) -> "NativeCreateTestFileExecutor":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
