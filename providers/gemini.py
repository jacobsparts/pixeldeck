import asyncio
from aiohttp import web
import gemini_edit

def bin_filetype(image_bin):
    if image_bin.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    elif image_bin.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    else:
        raise web.HTTPBadRequest(text='Error: file must be jpg or png')

async def go_gemini_edit(request, post, deliver_bin_image):
    mode = (post.get('mode') or 'edit').lower()
    if mode not in ('edit', 'generate'):
        raise web.HTTPBadRequest(text='mode must be edit or generate')
    prompt = post.get('prompt', '')
    if not prompt:
        raise web.HTTPBadRequest(text='prompt is required')
    image_bin = None
    mime_type = None
    if mode == 'edit':
        image_bin = post['image'].file.read()
        filetype = bin_filetype(image_bin)
        mime_type = 'image/jpeg' if filetype == 'jpg' else 'image/png'
    image_config = {}
    if post.get('aspect_ratio'):
        image_config['aspect_ratio'] = post['aspect_ratio']
    if post.get('image_size'):
        image_config['image_size'] = post['image_size']
    loop = asyncio.get_event_loop()
    model = post.get('model')
    out_bytes, _ = await loop.run_in_executor(
        None, gemini_edit.edit_image, image_bin, mime_type, prompt, image_config, model, mode
    )
    await deliver_bin_image(out_bytes)

def register_provider(register, get_config):
    cfg = get_config('gemini')
    api_key = cfg.get('api_key')
    if not api_key:
        return False

    handler = lambda req, post, deliver: go_gemini_edit(req, post, deliver)
    register('gemini', 'AI Edit', {
        'model': {
            'options': ['gemini-3.1-flash-image', 'gemini-3-pro-image'],
            'default': 'gemini-3.1-flash-image',
        },
        'mode': {
            'options': ['edit', 'generate'],
            'default': 'edit',
        },
        'prompt': {
            'type': 'string',
            'default': '',
            'presets': {
                'White Background': 'Replace the background with a clean white background',
                'Enhance Colors': 'Enhance the colors to make this product photo more vibrant and appealing',
                'Studio Lighting': 'Adjust the lighting to look like professional studio photography',
                'Remove Shadows': 'Remove all shadows from the image',
                'Lifestyle Scene': 'Place this product in a natural lifestyle setting',
            },
        },
        'aspect_ratio': {
            'options': ['', '1:1', '16:9', '9:16', '3:2', '2:3', '3:4', '4:3', '4:5', '5:4', '21:9', '1:4', '4:1', '1:8', '8:1'],
            'default': '',
        },
        'image_size': {
            'options': ['', '512', '1K', '2K', '4K'],
            'default': '',
        },
    })(handler)
    return True
