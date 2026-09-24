import json
import base64
import asyncio
import aiohttp
from aiohttp import web

async def ailabtools(request, post, deliver_bin_image, api_key):
    url = {
        'Product Background Removal': 'https://www.ailabapi.com/api/cutout/general/commodity-background-removal',
        'Image Upscaler 2x': 'https://www.ailabapi.com/api/image/enhance/image-lossless-enlargement',
        'Image Upscaler 2x + Enhance': 'https://www.ailabapi.com/api/image/enhance/image-lossless-enlargement',
        'Image Upscaler 4x': 'https://www.ailabapi.com/api/image/enhance/image-lossless-enlargement',
        'Image Upscaler 4x + Enhance': 'https://www.ailabapi.com/api/image/enhance/image-lossless-enlargement',
        'Image Erasure': 'https://www.ailabapi.com/api/image/editing/image-erase',
        'Image Sharpness': 'https://www.ailabapi.com/api/image/enhance/image-sharpness-enhancement',
        'Image Contrast Enhancement': 'https://www.ailabapi.com/api/image/enhance/image-contrast-enhancement',
        'Image Dehaze': 'https://www.ailabapi.com/api/image/enhance/image-defogging',
        'Image Color Enhancement LogC': 'https://www.ailabapi.com/api/image/enhance/image-color-enhancement',
        'Image Color Enhancement Rec709': 'https://www.ailabapi.com/api/image/enhance/image-color-enhancement',
        'Image Color Enhancement ln17_256': 'https://www.ailabapi.com/api/image/enhance/image-color-enhancement',
    }[post['model']]

    image_bin = post['image'].file.read()
    form = aiohttp.FormData()
    form.add_field('image', image_bin, filename='image.png', content_type='image/png')
    if post['model'] == 'Product Background Removal':
        form.add_field('return_type', '1')
    elif post['model'] == 'Image Upscaler 2x':
        form.add_field('scale', '2')
        form.add_field('enhance', '0')
    elif post['model'] == 'Image Upscaler 2x + Enhance':
        form.add_field('scale', '2')
        form.add_field('enhance', '1')
    elif post['model'] == 'Image Upscaler 4x':
        form.add_field('scale', '4')
        form.add_field('enhance', '0')
    elif post['model'] == 'Image Upscaler 4x + Enhance':
        form.add_field('scale', '4')
        form.add_field('enhance', '1')
    elif post['model'] == 'Image Erasure':
        mask_bin = post['mask'].file.read()
        form.add_field('mask_image', mask_bin, filename='mask.png', content_type='image/png')
    elif post['model'] == 'Image Color Enhancement LogC':
        form.add_field('type', 'LogC')
    elif post['model'] == 'Image Color Enhancement Rec709':
        form.add_field('type', 'Rec709')
    elif post['model'] == 'Image Color Enhancement ln17_256':
        form.add_field('type', 'ln17_256')

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers={'ailabapi-api-key': api_key},
            data=form
        ) as response:
            resp = await response.json()
            if 'error_code' in resp and resp['error_code'] != 0:
                print('AILabTools error:', resp)
                raise web.HTTPInternalServerError(text=json.dumps(resp))

    if 'image' in resp['data']:
        bin_image = base64.b64decode(resp['data']['image'])
    elif 'image_url' in resp['data']:
        async with aiohttp.ClientSession() as session:
            async with session.get(resp['data']['image_url']) as resp:
                bin_image = await resp.read()
    else:
        raise web.HTTPInternalServerError(text='no image returned')

    await deliver_bin_image(bin_image)

def register_provider(register, get_config):
    cfg = get_config('ailabtools')
    api_key = cfg.get('api_key')
    if not api_key:
        return False

    handler = lambda req, post, deliver: ailabtools(req, post, deliver, api_key)

    register('AILabTools', 'Background Removal', {
        'model': {
            'options': ['Product Background Removal'],
            'default': 'Product Background Removal',
        },
    })(handler)

    register('AILabTools', 'Super Resolution', {
        'model': {
            'options': [
                'Image Upscaler 2x',
                'Image Upscaler 2x + Enhance',
                'Image Upscaler 4x',
                'Image Upscaler 4x + Enhance',
            ],
            'default': 'Image Upscaler 2x',
        },
    })(handler)

    register('AILabTools', 'Inpainting', {
        'model': {
            'options': ['Image Erasure'],
            'default': 'Image Erasure',
        },
    })(handler)

    register('AILabTools', 'Contrast', {
        'model': {
            'options': ['Image Contrast Enhancement'],
            'default': 'Image Contrast Enhancement',
        },
    })(handler)

    register('AILabTools', 'Enhance', {
        'model': {
            'options': [
                'Image Sharpness',
                'Image Dehaze',
                'Image Color Enhancement LogC',
                'Image Color Enhancement Rec709',
                'Image Color Enhancement ln17_256',
            ],
            'default': 'Image Sharpness',
        },
    })(handler)

    return True
