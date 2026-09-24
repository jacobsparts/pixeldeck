"""
Provider auto-discovery and registration for Pixeldeck.
"""
import importlib
import os
import sys

def register_all_providers(register_fn, config_getter):
    """
    Discovers all provider modules in this package and calls their `register_provider` function.
    `register_fn` is the `@register` decorator or equivalent registration function.
    `config_getter` is a function(section) returning the section dict.
    """
    providers_dir = os.path.dirname(__file__)
    for filename in sorted(os.listdir(providers_dir)):
        if filename.endswith('.py') and not filename.startswith('__'):
            module_name = filename[:-3]
            try:
                mod = importlib.import_module(f'providers.{module_name}')
                if hasattr(mod, 'register_provider'):
                    enabled = mod.register_provider(register_fn, config_getter)
                    status = "enabled" if enabled else "disabled (missing API key/config)"
                    print(f"[providers] {module_name}: {status}")
            except Exception as e:
                import traceback
                print(f"[providers] Failed to load {module_name}: {e}")
                traceback.print_exc()
