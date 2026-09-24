"""
Plugin loader for Pixeldeck.

Scans ``plugins/`` for public plugin modules and ``plugins/private/`` for
optional or private ones, and calls the ``setup(app, route, get_config)``
function of each. Private plugins are loaded by file path rather than as part of
the ``plugins`` package, so that the directory can stay untracked (it is in
``.gitignore``) without needing an ``__init__.py`` in it.
"""
import importlib
import importlib.util
import os

PLUGINS_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_DIR = os.path.join(PLUGINS_DIR, 'private')


def _load(plugin_name, module_path, package_name, app, route_decorator_fn, get_config_fn):
    try:
        if package_name:
            mod = importlib.import_module(f'{package_name}.{plugin_name}')
        else:
            spec = importlib.util.spec_from_file_location(plugin_name, module_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        if hasattr(mod, 'setup'):
            mod.setup(app, route_decorator_fn, get_config_fn)
            print(f"[plugins] Loaded plugin: {plugin_name}")
    except Exception as e:
        import traceback
        print(f"[plugins] Failed to load {plugin_name}: {e}")
        traceback.print_exc()


def load_plugins(app, route_decorator_fn, get_config_fn):
    """Load every plugin in plugins/ and plugins/private/."""
    for directory, package_name in ((PLUGINS_DIR, 'plugins'), (PRIVATE_DIR, None)):
        if not os.path.isdir(directory):
            continue
        for item in sorted(os.listdir(directory)):
            if item.startswith('.') or item.startswith('__'):
                continue
            path = os.path.join(directory, item)
            if item.endswith('.py'):
                _load(item[:-3], path, package_name, app, route_decorator_fn, get_config_fn)
            elif os.path.isfile(os.path.join(path, '__init__.py')):
                _load(item, path, package_name, app, route_decorator_fn, get_config_fn)
