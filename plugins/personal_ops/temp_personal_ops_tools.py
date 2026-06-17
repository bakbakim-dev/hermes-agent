from __future__ import annotations

from typing import Any, Dict

from . import legacy_shared as _legacy_shared

globals().update({
    name: value
    for name, value in _legacy_shared.__dict__.items()
    if not name.startswith("__")
})
from . import adaptive_focus_runtime as _adaptive_focus_runtime
from . import integration_handlers as _integration_handlers
from . import location_briefing_runtime as _location_briefing_runtime
from . import operator_runtime as _operator_runtime
from . import runtime_status as _runtime_status
from . import todoist_runtime as _todoist_runtime
from . import tool_schemas as _tool_schemas

_LEGACY_DOMAIN_MODULES = (
    _adaptive_focus_runtime,
    _runtime_status,
    _todoist_runtime,
    _operator_runtime,
    _integration_handlers,
    _tool_schemas,
    _location_briefing_runtime,
)

_FACADE_DELEGATE_NAMES = {
    "handle_weather",
    "handle_focus_guard",
    "handle_runtime",
    "handle_adaptive_companion",
    "handle_todoist",
    "handle_clickup",
    "handle_twilio",
    "handle_security",
    "handle_location_slash_command",
    "handle_briefing_slash_command",
    "on_pre_approval_request",
    "on_post_approval_response",
}


def _exportable_module_names(module: Any) -> Dict[str, Any]:
    return {
        name: value
        for name, value in module.__dict__.items()
        if not name.startswith("__") and name not in {"annotations"}
    }


def _shared_globals_for_domains() -> Dict[str, Any]:
    shared: Dict[str, Any] = {}
    for name, value in globals().items():
        if name.startswith("__"):
            continue
        if name in _FACADE_DELEGATE_NAMES and getattr(value, "__module__", None) == __name__:
            continue
        shared[name] = value
    return shared


def _wire_legacy_domain_modules() -> None:
    shared = _shared_globals_for_domains()
    for module in _LEGACY_DOMAIN_MODULES:
        module.__dict__.update(shared)
    for module in _LEGACY_DOMAIN_MODULES:
        globals().update(_exportable_module_names(module))
    shared = _shared_globals_for_domains()
    for module in _LEGACY_DOMAIN_MODULES:
        module.__dict__.update(shared)


_wire_legacy_domain_modules()

_DOMAIN_HANDLER_FUNCS = {
    "handle_weather": _integration_handlers.handle_weather,
    "handle_focus_guard": _integration_handlers.handle_focus_guard,
    "handle_runtime": _integration_handlers.handle_runtime,
    "handle_adaptive_companion": _integration_handlers.handle_adaptive_companion,
    "handle_todoist": _integration_handlers.handle_todoist,
    "handle_clickup": _integration_handlers.handle_clickup,
    "handle_twilio": _integration_handlers.handle_twilio,
    "handle_security": _integration_handlers.handle_security,
    "handle_location_slash_command": _location_briefing_runtime.handle_location_slash_command,
    "handle_briefing_slash_command": _location_briefing_runtime.handle_briefing_slash_command,
    "on_pre_approval_request": _integration_handlers.on_pre_approval_request,
    "on_post_approval_response": _integration_handlers.on_post_approval_response,
}


def _sync_legacy_domain_modules() -> None:
    shared = _shared_globals_for_domains()
    for module in _LEGACY_DOMAIN_MODULES:
        module.__dict__.update(shared)


def handle_weather(args: Dict[str, Any], **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_weather"](args, **kwargs)


def handle_focus_guard(args: Dict[str, Any], **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_focus_guard"](args, **kwargs)


def handle_runtime(args: Dict[str, Any], **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_runtime"](args, **kwargs)


def handle_adaptive_companion(args: Dict[str, Any], **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_adaptive_companion"](args, **kwargs)


def handle_todoist(args: Dict[str, Any], **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_todoist"](args, **kwargs)


def handle_clickup(args: Dict[str, Any], **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_clickup"](args, **kwargs)


def handle_twilio(args: Dict[str, Any], **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_twilio"](args, **kwargs)


def handle_security(args: Dict[str, Any], **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_security"](args, **kwargs)


def handle_location_slash_command(*args: Any, **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_location_slash_command"](*args, **kwargs)


def handle_briefing_slash_command(*args: Any, **kwargs: Any) -> str:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["handle_briefing_slash_command"](*args, **kwargs)


def on_pre_approval_request(**kwargs: Any) -> None:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["on_pre_approval_request"](**kwargs)


def on_post_approval_response(**kwargs: Any) -> None:
    _sync_legacy_domain_modules()
    return _DOMAIN_HANDLER_FUNCS["on_post_approval_response"](**kwargs)


def _make_legacy_callable(func: Any) -> Any:
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        _sync_legacy_domain_modules()
        return func(*args, **kwargs)

    _wrapped.__name__ = getattr(func, "__name__", "_wrapped")
    _wrapped.__doc__ = getattr(func, "__doc__", None)
    _wrapped.__module__ = __name__
    return _wrapped


for _module in _LEGACY_DOMAIN_MODULES:
    for _name, _value in list(_module.__dict__.items()):
        if _name in _FACADE_DELEGATE_NAMES:
            continue
        if getattr(_value, "__module__", None) == _module.__name__ and callable(_value):
            globals()[_name] = _make_legacy_callable(_value)
