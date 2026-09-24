import asyncio
from aiohttp import web
import gpt_edit

def bin_filetype(image_bin):
    if image_bin.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    elif image_bin.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    else:
        raise web.HTTPBadRequest(text='Error: file must be jpg or png')

async def go_gpt_edit(request, post, deliver_bin_image):
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
    for key in ('size', 'quality', 'background', 'input_fidelity'):
        val = post.get(key)
        if val and val != 'auto':
            image_config[key] = val
    loop = asyncio.get_event_loop()
    model = post.get('model')
    out_bytes, _ = await loop.run_in_executor(
        None, gpt_edit.edit_image, image_bin, mime_type, prompt, image_config, model, mode
    )
    await deliver_bin_image(out_bytes)

def register_provider(register, get_config):
    cfg = get_config('openai')
    api_key = cfg.get('api_key')
    if not api_key:
        return False

    handler = lambda req, post, deliver: go_gpt_edit(req, post, deliver)
    register('openai', 'AI Edit', {
        'model': {
            'options': ['gpt-image-2'],
            'default': 'gpt-image-2',
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
        'size': {
            'options': ['auto', '1024x1024', '1536x1024', '1024x1536'],
            'default': 'auto',
        },
        'quality': {
            'options': ['auto', 'low', 'medium', 'high'],
            'default': 'auto',
        },
        'background': {
            'options': ['auto', 'transparent', 'opaque'],
            'default': 'auto',
            'exclude_models': ['gpt-image-2'],
        },
        'input_fidelity': {
            'options': ['high', 'low'],
            'default': 'high',
            'exclude_models': ['gpt-image-2'],
        },
    })(handler)
    return True
