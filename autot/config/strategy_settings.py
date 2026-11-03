"""Legacy compatibility view. Runtime scans use the typed Strategy settings."""
from autot.settings.models import Strategies

ENABLED_STRATEGIES = {name: getattr(Strategies(), name).enabled for name in Strategies.model_fields}
