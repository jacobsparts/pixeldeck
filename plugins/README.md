# Pixeldeck Plugins

Place optional plugins in this directory as `plugins/<plugin_name>.py` or
`plugins/<plugin_name>/__init__.py`, and private ones in `plugins/private/`
(which is ignored by `.gitignore`).

## Server side

Each plugin can define a `setup(app, route, get_config)` function:

```python
def setup(app, route, get_config):
    get = lambda path: route("GET", path)
    post = lambda path: route("POST", path)

    @get('/pixeldeck/my_endpoint')
    async def my_endpoint(request):
        ...
```

`route(method, path)` registers a handler on the aiohttp app, and
`get_config("my_plugin")` returns that section of `config.json` (add it to
`config.example.json` to make it editable from the Config dialog).

## Front end

A plugin can also ship frontend code as `plugins/<plugin_name>.js`. Those files
are concatenated into `/pixeldeck/plugins.js`, which the page loads before it
starts, so a plugin script sees `window.pixeldeckPlugins` and pushes itself onto
it:

```javascript
(function() {
    window.pixeldeckPlugins = window.pixeldeckPlugins || [];
    window.pixeldeckPlugins.push({
        name: 'my_plugin',
        install(app, api) {
            app.methods.my_method = async function() { ... };
            api.addMenuComponent({
                name: 'my-toolbar',
                props: ['app'],
                template: `<span class="shortcut" @click="app.my_method()">Mine</span>`
            });
        }
    });
})();
```

`install(app, api)` is called once with the page's Vue options object (`app`) and
a small api:

| api | what it does |
| --- | --- |
| `api.addMenuComponent(component)` | renders `component` at the end of the menubar, with `app` as a prop |
| `api.addImageControl(component)` | renders `component` in the controls under every thumbnail, with `app`, `image` and `index` as props |

A plugin may extend `app` (methods, data, `created`, computed), but everything
that is not a documented extension point belongs in the plugin: the page knows
nothing about any particular plugin.

Private plugins are loaded from `plugins/private/` the same way, by file path,
so the directory needs no `__init__.py` and stays out of source control.
