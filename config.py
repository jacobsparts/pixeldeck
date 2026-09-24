"""Pixeldeck configuration.

The whole application reads its settings from one file, ``config.json``, which
sits next to this module and is not tracked by git. ``config.example.json`` is
the template: it lists every section and every key that exists, so it is also
what the config editor in the web UI renders its fields from. Copy it to
``config.json`` and fill in the credentials of the providers you want; a
provider whose section has no credentials simply does not register itself.
"""
import json
import os
import tempfile

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
EXAMPLE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.example.json')

# A key with one of these names holds a credential. The editor never sends
# those back to the browser, and only reports whether they are set.
SECRET_KEYS = ('api_key', 'api_token', 'password', 'authorization', 'token')


def is_secret(key):
    return key in SECRET_KEYS


def load_config():
    """Read config.json, or an empty config if it is missing or unreadable."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[config] Error loading {CONFIG_FILE}: {e}")
        return {}


def get_config(section=None):
    """The whole config, or one section of it."""
    cfg = load_config()
    if section:
        return cfg.get(section, {})
    return cfg


def field_spec():
    """The sections and keys that config.json may contain, from the example."""
    try:
        with open(EXAMPLE_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[config] Error loading {EXAMPLE_FILE}: {e}")
        return {}


def save_config(cfg):
    """Write config.json, replacing it atomically so readers never see a partial file."""
    directory = os.path.dirname(CONFIG_FILE)
    fd, temp_path = tempfile.mkstemp(dir=directory, prefix='.config-', suffix='.json')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(cfg, f, indent=2)
            f.write('\n')
        os.replace(temp_path, CONFIG_FILE)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    os.chmod(CONFIG_FILE, 0o600)


def update_config(patch):
    """Merge a partial config into config.json and return the result.

    Only sections and keys listed in config.example.json are accepted, so a
    request cannot write arbitrary data into the file. A key set to ``None`` is
    removed; a key that is absent from the patch is left alone.
    """
    spec = field_spec()
    cfg = load_config()
    for section, values in patch.items():
        if section not in spec:
            raise ValueError(f'unknown config section: {section}')
        if not isinstance(values, dict):
            raise ValueError(f'config section {section} must be an object')
        target = cfg.setdefault(section, {})
        for key, value in values.items():
            if key not in spec[section]:
                raise ValueError(f'unknown config key: {section}.{key}')
            if value is None:
                target.pop(key, None)
            elif isinstance(value, str):
                target[key] = value
            else:
                raise ValueError(f'config value {section}.{key} must be a string or null')
    save_config(cfg)
    return cfg
