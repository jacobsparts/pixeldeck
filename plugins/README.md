# Pixeldeck Plugins

Place optional plugins in this directory as `plugins/<plugin_name>.py` or
`plugins/<plugin_name>/__init__.py`, and private ones in `plugins/private/`
(which is ignored by `.gitignore`).

Each plugin can define a `setup(app, route, get_config)` function:

```python
def setup(app, route, get_config):
    get = lambda path: route("GET", path)
    post = lambda path: route("POST", path)

    @get('/pixeldeck/my_endpoint')
    async def my_endpoint(request):
        ...
```

A plugin can also ship frontend code as `plugins/<plugin_name>.js`; the files
are concatenated and served from `/pixeldeck/plugins.js` for the page to load.
Private plugins are loaded from `plugins/private/` the same way, by file path,
so the directory needs no `__init__.py` and stays out of source control.
