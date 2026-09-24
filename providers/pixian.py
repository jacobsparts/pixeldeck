import io
import asyncio
import base64
from PIL import Image
import aiohttp
from aiohttp import web

def get_auth_header(cfg):
    if 'authorization' in cfg:
        return cfg['authorization']
    username = cfg.get('username')
    password = cfg.get('password')
    if username and password:
        encoded = base64.b64encode(f'{username}:{password}'.encode()).decode()
        return f'Basic {encoded}'
    return None

async def pixian_remove_bg(image_bin, auth_header):
    """Call Pixian API to remove background. Returns result image bytes."""
    form = aiohttp.FormData()
    form.add_field('image', image_bin, filename='image.png', content_type='image/png')
    async with aiohttp.ClientSession() as session:
        async with session.post(
            'https://api.pixian.ai/api/v2/remove-background',
            headers={'Authorization': auth_header},
            data=form
        ) as response:
            if response.status != 200:
                err_text = await response.text()
                raise web.HTTPInternalServerError(text=f'Pixian API error ({response.status}): {err_text}')
            return await response.read()

async def go_pixian(request, post, deliver_bin_image, auth_header):
    image_bin = post['image'].file.read()
    bin_image = await pixian_remove_bg(image_bin, auth_header)
    await deliver_bin_image(bin_image)


def register_provider(register, get_config):
    pixian_cfg = get_config('pixian')
    auth_header = get_auth_header(pixian_cfg)
    if not auth_header:
        return False

    pixian_handler = lambda req, post, deliver: go_pixian(req, post, deliver, auth_header)
    register('Pixian', 'Background Removal', {
        'model': {
            'options': ['remove-background'],
            'default': 'remove-background',
        },
    })(pixian_handler)


    return True
