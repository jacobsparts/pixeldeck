"""
Provider auto-discovery and registration for Pixeldeck.
"""
import importlib
import os
import sys

class EngineError(RuntimeError):
    """A local engine refused the job, or failed it, and said why.

    The message is written for the person looking at the editor rather than for
    a log: what could not be done, the arithmetic behind it, and what would fit.
    The server shows it as it stands - no Python exception type in front of it -
    so a memory refusal reads as a sentence instead of a traceback. It lives
    here, and not in the provider that raises it, because the provider modules
    are loaded on demand and this class has to be importable either way.
    """

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
