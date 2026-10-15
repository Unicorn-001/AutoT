"""Small runtime helpers shared by local and hosted entry points."""

import os
from pathlib import Path
import tempfile

import certifi


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_UNIVERSE = PROJECT_ROOT / "autot" / "universe" / "us_stocks.csv"
CERTIFICATE_VARIABLES = ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE")


def project_path(path):
    path = Path(path).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def data_dir():
    """Relative overrides are relative to the app, never the launching shell."""
    return project_path(os.environ.get("AUTOT_DATA_DIR") or "data_storage")


def configure_certificates():
    """Preserve operator trust settings; use certifi only for an unset setup.

    If any CA override exists, leave the whole configuration to the operator.
    This avoids shadowing one library's existing fallback with another variable.
    """
    if any(name in os.environ for name in (*CERTIFICATE_VARIABLES, "SSL_CERT_DIR")):
        return
    bundle = certifi.where()
    for name in CERTIFICATE_VARIABLES:
        os.environ.setdefault(name, bundle)


def initialize_runtime():
    """Create/probe scan storage. A read-only host must set AUTOT_DATA_DIR."""
    configure_certificates()
    root = data_dir()
    for path in (root, root / "yfinance_cache", root / "universe_cache"):
        path.mkdir(parents=True, exist_ok=True)
        # Probe actual writes rather than relying on permission bits/ACL guesses.
        with tempfile.TemporaryFile(dir=path):
            pass
    return root
