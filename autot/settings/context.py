"""One immutable configuration per scan, including worker threads."""
from contextvars import ContextVar
from functools import wraps
from autot.settings.store import SettingsStore

_analysis_settings = ContextVar('autot_analysis_settings', default=None)


def analysis_settings():
    return _analysis_settings.get() or SettingsStore().load().settings


def bind_analysis(function, settings):
    @wraps(function)
    def bound(*args, **kwargs):
        token = _analysis_settings.set(settings)
        try:
            return function(*args, **kwargs)
        finally:
            _analysis_settings.reset(token)
    return bound
