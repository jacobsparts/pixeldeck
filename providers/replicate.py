import json
import uuid
import asyncio
import aiohttp
from aiohttp import web

def bin_filetype(image_bin):
    if image_bin.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    elif image_bin.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    else:
        raise web.HTTPBadRequest(text='Error: file must be jpg or png')

def bin_datauri(image_bin):
    filetype = bin_filetype(image_bin)
    import base64
    b64 = base64.b64encode(image_bin).decode()
    return f"data:image/{filetype};base64,{b64}"

class ReplicateImageInput:
    def __init__(self, image_bin, api_token):
        self.image_bin = image_bin
        self.api_token = api_token
        self.file_id = None

    async def __aenter__(self):
        if len(self.image_bin) <= 1_000_000:
            return bin_datauri(self.image_bin)
        filetype = bin_filetype(self.image_bin)
        mime = 'image/jpeg' if filetype == 'jpg' else 'image/png'
        filename = f'{uuid.uuid4().hex}.{filetype}'
        form = aiohttp.FormData()
        form.add_field('content', self.image_bin, filename=filename, content_type=mime)
        form.add_field('filename', filename)
        form.add_field('type', mime)
        form.add_field('metadata', '{}')
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://api.replicate.com/v1/files',
                headers={'Authorization': f'Token {self.api_token}'},
                data=form
            ) as resp:
                if resp.status != 201:
                    text = await resp.text()
                    raise web.HTTPInternalServerError(text=f'Replicate file upload failed: {text}')
                data = await resp.json()
                self.file_id = data.get('id')
                return data['urls']['get']

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.file_id:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.delete(
                        f'https://api.replicate.com/v1/files/{self.file_id}',
                        headers={'Authorization': f'Token {self.api_token}'}
                    ):
                        pass
            except Exception:
                pass

async def replicate(req, api_token):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            'https://api.replicate.com/v1/predictions',
            headers={
                'Authorization': f"Token {api_token}",
                'Content-Type': 'application/json',
            },
            json=req
        ) as response:
            resp = await response.json()
    while resp['status'] in ('starting', 'processing'):
        await asyncio.sleep(0.2)
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'https://api.replicate.com/v1/predictions/{resp["id"]}',
                headers={'Authorization': f"Token {api_token}"}
            ) as response:
                resp = await response.json()
    if not resp['status'] == 'succeeded':
        raise web.HTTPInternalServerError(text=json.dumps(resp))
    return resp

async def replicate_download(url, api_token):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={'Authorization': f"Token {api_token}"}) as resp:
            if not resp.status == 200:
                print("error downloading completed image")
                raise web.Response(
                    body=await resp.read(),
                    content_type=resp.headers['Content-Type'],
                    status=resp.status
                )
            return await resp.read()

async def go_replicate(request, post, deliver_bin_image, api_token):
    def replicate_req(model, url, mask_url=None):
        return {
            'latent-sr': { "version": "80a827435f187a2d4808381dd003ca2871144a1e944d18fa1c4d9bc899ea2fa8", "input": { "image": url } },
        }[model]

    image_bin = post['image'].file.read()
    async with ReplicateImageInput(image_bin, api_token) as url:
        resp = await replicate(replicate_req(post['model'], url), api_token)
    output_url = resp['output']
    if isinstance(output_url, list):
        output_url = output_url[0]
    bin_image = await replicate_download(output_url, api_token)
    await deliver_bin_image(bin_image)

def register_provider(register, get_config):
    cfg = get_config('replicate')
    api_token = cfg.get('api_token')
    if not api_token:
        return False

    handler = lambda req, post, deliver: go_replicate(req, post, deliver, api_token)

    register('Replicate', 'Super Resolution', {
        'model': {
            'options': [
                'latent-sr',
            ],
            'description': {
                'latent-sr': 'latent diffusion superresolution, good with texture, use 512x512 input',
            },
            'default': 'latent-sr',
        },
    })(handler)

    # Defocus deblurring used to be offered here, through the Replicate model
    # `ifan-defocus-deblur`, and super resolution used to include the Replicate
    # `swin2sr` and `xpixelgroup/hat` models. None is any more: all run locally -
    # IFAN as `Enhance > IFAN Defocus Deblur`, Swin2SR and HAT as entries in
    # `Super Resolution` in the `local` provider - with no API key, no upload and
    # no per-image cost.
    #
    # `controlnet` (batouresearch's high-resolution-controlnet-tile) and
    # `stable-diffusion-upscaler` were removed from Super Resolution as well.
    return True
