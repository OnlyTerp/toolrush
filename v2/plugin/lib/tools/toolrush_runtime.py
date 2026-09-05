"""ToolRush configuration shared by compatible local acceleration lanes.

No result/permission cache. Read-only config view preserves profile scoping
without deepcopying the complete provider configuration per tool call.
"""
import os


def enabled(key: str, legacy_env: str = '') -> bool:
    """Behavior lives in config.yaml; legacy env gates remain for rollback."""
    if legacy_env and os.environ.get(legacy_env, '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    try:
        from hermes_cli.config import load_config_readonly
        section = load_config_readonly().get('toolrush', {})
        if not isinstance(section, dict):
            return False
        return section.get('enabled', True) is True and section.get(key, True) is True
    except Exception:
        # Config failures should retain the established fallback, not silently
        # enable an optimization whose behavior the operator cannot control.
        return False
