"""Per-user service coordination primitives.

No object in this package is mounted into the public API.  Runtime composition
must supply a correctly secured Windows named-mutex adapter before coordinator
mode can be used.
"""

from .control import (
    APPLICATION_ID,
    BUSY_TIMEOUT_MS,
    CONTROL_DATABASE_NAME,
    SCHEMA_VERSION,
    ControlDataCorruption,
    ControlError,
    ControlEvent,
    ControlSnapshot,
    CoordinatorBusy,
    CoordinatorConflict,
    CoordinatorStatus,
    GenerationFence,
    IdentityMismatch,
    MutexProtocolError,
    ServiceControl,
    ServiceMode,
    ShadowModeViolation,
    StoragePolicyViolation,
)
from .ports import (
    CurrentIdentityPort,
    MutexAcquireResult,
    NamedMutexFactoryPort,
    NamedMutexHandlePort,
    StoragePolicyPort,
    WindowsCurrentIdentity,
    WindowsLocalNtfsStorage,
)
from .windows_mutex import (
    WindowsMutexError,
    WindowsMutexSecurityError,
    WindowsMutexStateError,
    WindowsMutexWaitFailed,
    WindowsNamedMutexFactory,
    WindowsNamedMutexHandle,
    current_user_mutex_name,
    secure_windows_mutex_factory,
)

__all__ = [
    "APPLICATION_ID",
    "BUSY_TIMEOUT_MS",
    "CONTROL_DATABASE_NAME",
    "SCHEMA_VERSION",
    "ControlDataCorruption",
    "ControlError",
    "ControlEvent",
    "ControlSnapshot",
    "CoordinatorBusy",
    "CoordinatorConflict",
    "CoordinatorStatus",
    "CurrentIdentityPort",
    "GenerationFence",
    "IdentityMismatch",
    "MutexAcquireResult",
    "MutexProtocolError",
    "NamedMutexFactoryPort",
    "NamedMutexHandlePort",
    "ServiceControl",
    "ServiceMode",
    "ShadowModeViolation",
    "StoragePolicyPort",
    "StoragePolicyViolation",
    "WindowsCurrentIdentity",
    "WindowsLocalNtfsStorage",
    "WindowsMutexError",
    "WindowsMutexSecurityError",
    "WindowsMutexStateError",
    "WindowsMutexWaitFailed",
    "WindowsNamedMutexFactory",
    "WindowsNamedMutexHandle",
    "current_user_mutex_name",
    "secure_windows_mutex_factory",
]
