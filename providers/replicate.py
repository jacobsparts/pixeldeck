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
            'rembg': { "version": "fb8af171cfa1616ddcf1242c093f9c46bcada5ad4cf6f2fbe8b81b330ec5c003", "input": { "image": url } },
            'modnet': { "version": "da7d45f3b836795f945f221fc0b01a6d3ab7f5e163f13208948ad436001e2255", "input": { "image": url } },
            'rembg-enhance': { "version": "4067ee2a58f6c161d434a9c077cfa012820b8e076efa2772aa171e26557da919", "input": { "image": url } },
            'remove-bg': { "version": "95fcc2a26d3899cd6c2691c900465aaeff466285a65c14638cc5f36f34befaf1", "input": { "image": url } },
            'dis-v1': { "version": "4bdb324f7d2547aef96ca0704a94c0b25ab2805b9afecc2d24e68f7a01f87297", "input": { "image": url } },
            'controlnet': { "version": "3a3d5371ef3b64c0516314f8846ecc3e56a7356230f898de50a5eb578a74e645", "input": { "image": url, "steps": 50, "denoise": 0.4 } },
            'swin2sr classical': { "version": "a01b0512004918e67d4022780360a3d54f8de8cb375737f12ac1b0de3f3cf15b", "input": { "image": url, "task": "classical_sr" } },
            'swin2sr real-world': { "version": "a01b0512004918e67d4022780360a3d54f8de8cb375737f12ac1b0de3f3cf15b", "input": { "image": url, "task": "real_sr" } },
            'swin2sr compressed': { "version": "a01b0512004918e67d4022780360a3d54f8de8cb375737f12ac1b0de3f3cf15b", "input": { "image": url, "task": "compressed_sr" } },
            'latent-sr': { "version": "80a827435f187a2d4808381dd003ca2871144a1e944d18fa1c4d9bc899ea2fa8", "input": { "image": url } },
            'hcflow-sr': { "version": "5b4c102a77a9cf58a5beab5ebf36118d0526920fb630132b851b4f4c8038b304", "input": { "image": url } },
            'stable-diffusion-upscaler': { "version": "f178f4e343c57e21a880da3e1e08b30bf1f91746073da213453d5ada7f7b4ac4", "input": { "image": url } },
            'xpixelgroup/hat': { "version": "0a976378413b6326bf3b63198cf982e5645511b858f96e578c2eef0f329910d9", "input": { "image": url } },
            'scunet (denoise)': { "version": "3a005085d7b53f65b4c3ee70c17a565a046c8230ea0e599b52a512702bba689d", "input": { "image": url } },
            'ifan-defocus-deblur': { "version": "efdf547cf20ce745c11d0442345ef130f14654b9d03c6e9389201a08b5e679ee", "input": { "image": url } },
            'night-enhancement': { "version": "3c0aa136005ae6587c693a393e8e29a4a7541f6f69527cf634ff1f32a77764d8", "input": { "image": url } },
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

    register('Replicate', 'Background Removal', {
        'model': {
            'options': [
                'rembg',
                'dis-v1',
                'modnet',
                'rembg-enhance',
                'remove-bg',
            ],
            'default': 'rembg',
        },
    })(handler)

    register('Replicate', 'Super Resolution', {
        'model': {
            'options': [
                'controlnet',
                'swin2sr classical',
                'swin2sr real-world',
                'swin2sr compressed',
                'latent-sr',
                'hcflow-sr',
                'stable-diffusion-upscaler',
                'xpixelgroup/hat',
            ],
            'description': {
                'controlnet': 'batouresearch / high-resolution-controlnet-tile',
                'latent-sr': 'latent diffusion superresolution, good with texture, use 512x512 input',
            },
            'default': 'hcflow-sr',
        },
    })(handler)

    register('Replicate', 'Enhance', {
        'model': {
            'options': [
                'scunet (denoise)',
                'ifan-defocus-deblur',
                'night-enhancement',
            ],
            'default': 'scunet (denoise)',
        },
    })(handler)

    return True
