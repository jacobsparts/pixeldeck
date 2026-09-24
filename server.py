#!/usr/bin/env python3
"""Pixeldeck: a local image-processing web app.

Serves a small single-page editor that runs images through a pipeline of
tools. Each tool is either a local GPU binary under ``bin/`` (installed by
``install.sh``) or a third-party image API; which ones are offered depends on
which credentials are present in ``config.json``.

The server binds to the loopback interface only. It has no authentication and
is not meant to be exposed to a network.
"""
import argparse
import asyncio
import os
import sys

import aiohttp
from aiohttp import web
from aiohttp.web_exceptions import HTTPException

import config
from plugins import PRIVATE_DIR, PLUGINS_DIR, load_plugins
from providers import register_all_providers

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(SCRIPT_DIR, 'static')


def image_content_type(image_bin):
    """The content type of a JPEG or PNG body, from its magic number."""
    if image_bin.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if image_bin.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    raise web.HTTPBadRequest(text='Error: file must be jpg or png')


class ImageDelivery(Exception):
    """An image on its way back to the client.

    A provider ends a request by calling the ``deliver_bin_image`` callable it
    was handed at registration, from wherever it happens to be in its own code,
    rather than by returning a response. That keeps every provider free to do
    its work in its own shape: it raises this, ``process`` turns it into the
    response body.
    """

    def __init__(self, body, content_type):
        super().__init__(content_type)
        self.body = body
        self.content_type = content_type


async def deliver_bin_image(bin_image):
    raise ImageDelivery(bin_image, image_content_type(bin_image))


# =================
# Tool Registration
# =================

# The tool categories the UI offers, in menu order. A category with no provider
# registered against it is simply not shown.
CATEGORIES = (
    'Super Resolution',
    'Inpainting',
    'Background Removal',
    'Auto-Crop',
    'Contrast',
    'Enhance',
    'AI Edit',
)
schema = {category: {} for category in CATEGORIES}
model_fn = {}


def _normalize_schema(_schema):
    normalized = {}
    for key, field in _schema.items():
        field = dict(field)
        if 'type' not in field:
            field['type'] = 'enum' if 'options' in field else 'string'
        normalized[key] = field
    return normalized


def register(provider, model_type, _schema):
    def decorator(fn):
        schema.setdefault(model_type, {})[provider] = _normalize_schema(_schema)

        async def wrapped(request, post):
            return await fn(request, post, deliver_bin_image)

        for model in _schema['model']['options']:
            model_fn[model] = wrapped
        return fn
    return decorator


def register_tools():
    """(Re)build the tool schema from the provider modules and the config.

    Providers register themselves only if their credentials are present, so this
    is re-run whenever the config changes: a provider that was just given a key
    appears, and one whose key was removed disappears.
    """
    schema.clear()
    schema.update({category: {} for category in CATEGORIES})
    model_fn.clear()
    register_all_providers(register, config.get_config)


register_tools()


# ==========
# Web Server
# ==========

routes = {}


def route(method, path):
    def _a(_b, *args, **kwargs):
        routes[(method, path)] = _b
        return _b
    return _a


get = lambda path: route("GET", path)
post = lambda path: route("POST", path)
put = lambda path: route("PUT", path)


@get('/')
async def root(request):
    raise web.HTTPFound('/pixeldeck/')


@get('/pixeldeck/')
async def index(request):
    return web.FileResponse(os.path.join(STATIC_DIR, 'index.html'))


@get('/favicon.ico')
async def favicon_root(request):
    return web.FileResponse(os.path.join(STATIC_DIR, 'pixeldeck.svg'))


@get('/pixeldeck/favicon.ico')
async def favicon(request):
    return web.FileResponse(os.path.join(STATIC_DIR, 'pixeldeck.svg'))


@get('/pixeldeck/static/{filename}')
async def static(request):
    filename = request.match_info['filename']
    filepath = os.path.join(STATIC_DIR, os.path.basename(filename))
    if not os.path.exists(filepath):
        raise aiohttp.web.HTTPNotFound()
    return web.FileResponse(filepath)


@get('/pixeldeck/plugins.js')
async def plugins_js(request):
    """The JavaScript of every plugin, public ones first."""
    js_parts = []
    for directory in (PLUGINS_DIR, PRIVATE_DIR):
        if not os.path.isdir(directory):
            continue
        for filename in sorted(os.listdir(directory)):
            if filename.endswith('.js'):
                with open(os.path.join(directory, filename), 'r') as fh:
                    js_parts.append(fh.read())
    return web.Response(text="\n\n".join(js_parts), content_type='application/javascript')


@post('/pixeldeck/process')
async def process(request):
    post = await request.post()
    try:
        fn = model_fn[post['model']]
    except KeyError:
        return web.Response(status=400, text='invalid request')
    try:
        return await fn(request, post)
    except ImageDelivery as delivery:
        return web.Response(body=delivery.body, content_type=delivery.content_type)
    except HTTPException:
        raise
    except Exception as e:
        return web.Response(status=500, text=f'{type(e).__name__}: {e}')


@get('/pixeldeck/schema')
async def get_schema(request):
    return web.json_response(schema)


def config_view():
    """Every configurable setting, with secrets reported but never sent.

    The shape of the view comes from config.example.json, so a section or key
    that the file does not list cannot be edited (or written) from the UI.
    """
    values = config.get_config()
    sections = []
    for section, fields in config.field_spec().items():
        entries = []
        for key in fields:
            value = values.get(section, {}).get(key)
            secret = config.is_secret(key)
            entries.append({
                'key': key,
                'secret': secret,
                # A secret is write-only: the UI is told whether it is set, not
                # what it is.
                'value': None if secret else (value or ''),
                'set': bool(value),
            })
        sections.append({'name': section, 'fields': entries})
    return {'sections': sections}


@get('/pixeldeck/config')
async def get_config(request):
    return web.json_response(config_view())


@put('/pixeldeck/config')
async def put_config(request):
    try:
        patch = await request.json()
    except Exception:
        return web.Response(status=400, text='body must be JSON')
    if not isinstance(patch, dict):
        return web.Response(status=400, text='body must be an object of sections')
    try:
        config.update_config(patch)
    except ValueError as e:
        return web.Response(status=400, text=str(e))
    register_tools()
    return web.json_response(config_view())


# Load optional/private plugins
load_plugins(None, route, config.get_config)

app = web.Application(client_max_size=1024 * 1024 * 100)
for (method, path), handler in routes.items():
    app.router.add_route(method, path, handler)


async def run(app, host, port):
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, host, port)
        await site.start()
        print(f'Pixeldeck listening on http://{host}:{port}/pixeldeck/')
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description='Run the Pixeldeck server.')
    parser.add_argument('--host', default='127.0.0.1',
                        help='address to bind to (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8081,
                        help='port to listen on (default: 8081)')
    args = parser.parse_args()
    try:
        asyncio.run(run(app, args.host, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
