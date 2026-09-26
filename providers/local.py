import os
import io
import tempfile
import subprocess
import asyncio
from aiohttp import web
from PIL import Image, ImageOps

import gpu_guard
from providers import EngineError

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(SCRIPT_DIR, 'bin')
ADAPTIVE_ENHANCE_BIN = os.path.join(BIN_DIR, 'adaptive-enhance')
IAGCWD_BIN = os.path.join(BIN_DIR, 'iagcwd')
WHITE_BALANCE_BIN = os.path.join(BIN_DIR, 'white-balance')
LAMA_INPAINT_BIN = os.path.join(BIN_DIR, 'lama-inpaint')
LAMA_WEIGHTS = os.path.join(BIN_DIR, 'models', 'big-lama.safetensors')
RMBG_BIN = os.path.join(BIN_DIR, 'rmbg-linux-x86_64')
RMBG_WEIGHTS = os.path.join(BIN_DIR, 'models', 'RMBG-2.0.safetensors')
REALESRGAN_BIN = os.path.join(BIN_DIR, 'realesrgan-linux-x86_64')
REALESRGAN_MODELS_DIR = os.path.join(BIN_DIR, 'models')
NAFNET_BIN = os.path.join(BIN_DIR, 'nafnet-linux-x86_64')
MAXIM_BIN = os.path.join(BIN_DIR, 'maxim-linux-x86_64')

SUPER_RESOLUTION_MODELS = {
    'RealESRGAN x2plus': ('RealESRGAN_x2plus.safetensors', 2),
    'RealESRGAN x4plus': ('RealESRGAN_x4plus.safetensors', 4),
    'RealESRNet x4plus': ('RealESRNet_x4plus.safetensors', 4),
    '4x-RealisticRescaler': ('4x_RealisticRescaler_100000_G.safetensors', 4),
}

# NAFNet: the checkpoint alone picks both the task and the width (32 = the
# speed model, 64 = the quality one), so the menu labels say which is which and
# this table says which file each label means. The five weights the engine
# publishes are all here; the width-32 quality gap is what the 64s buy.
NAFNET_MODELS = {
    'NAFNet Deblur (fast)': 'nafnet-gopro-width32.safetensors',
    'NAFNet Deblur (best)': 'nafnet-gopro-width64.safetensors',
    'NAFNet Denoise (fast)': 'nafnet-sidd-width32.safetensors',
    'NAFNet Denoise (best)': 'nafnet-sidd-width64.safetensors',
    'NAFNet Video Deblur (best)': 'nafnet-reds-width64.safetensors',
}

# MAXIM: eleven checkpoints, one per task and dataset, and the file alone picks
# the architecture - a two-stage model for enhancement, deraining and dehazing,
# a three-stage one for denoising and deblurring. So the menu labels name the
# task and the dataset, and this table says which file each label means.
MAXIM_MODELS = {
    'Maxim Low-light (LOL)': 'maxim-lol.safetensors',
    'Maxim Enhance (FiveK)': 'maxim-fivek.safetensors',
    'Maxim Denoise (SIDD)': 'maxim-sidd.safetensors',
    'Maxim Deblur (GoPro)': 'maxim-gopro.safetensors',
    'Maxim Deblur (REDS)': 'maxim-reds.safetensors',
    'Maxim Deblur (RealBlur-R)': 'maxim-realblur-r.safetensors',
    'Maxim Deblur (RealBlur-J)': 'maxim-realblur-j.safetensors',
    'Maxim Derain (Rain13k)': 'maxim-rain13k.safetensors',
    'Maxim Derain (Raindrop)': 'maxim-raindrop.safetensors',
    'Maxim Dehaze (Indoor)': 'maxim-sots-indoor.safetensors',
    'Maxim Dehaze (Outdoor)': 'maxim-sots-outdoor.safetensors',
}

def _engine_message(label, code, stderr):
    """What an engine said that is worth showing a user, and nothing else.

    Every engine in this project prefixes its own lines with its own name -
    `nafnet: not enough device memory for a 2048x2048 pass` - so those lines ARE
    the engine talking to whoever is looking at the editor, and the prefix is
    dropped so they read as sentences. Anything else on stderr is a panic, a
    loader message or a build detail, none of which belongs in front of a user;
    the last such line is kept only when there was no prefixed line at all,
    because a segfault still has to say something.
    """
    said = []
    for line in stderr.splitlines():
        head, sep, rest = line.rstrip().partition(': ')
        if sep and rest and head.islower() and ' ' not in head:
            said.append(rest)
    if said:
        return '\n'.join(said[:6])
    tail = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    detail = f' - {tail[-1]}' if tail else ''
    return f'{label} failed (exit code {code}){detail}'


def _run_png_filter(binary, label, image_bin, args=()):
    """Pipe a PNG through one of the adaptive-enhance binaries."""
    if not image_bin.startswith(b'\x89PNG\r\n\x1a\n'):
        img = Image.open(io.BytesIO(image_bin))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ('RGB', 'RGBA', 'L', 'LA'):
            img = img.convert('RGBA' if 'A' in img.mode else 'RGB')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        png_bytes = buf.getvalue()
    else:
        png_bytes = image_bin

    proc = subprocess.run(
        [binary] + list(args),
        input=png_bytes,
        capture_output=True,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode(errors='replace')
        raise EngineError(_engine_message(label, proc.returncode, err))
    return proc.stdout

def run_adaptive_enhance(image_bin, args=()):
    return _run_png_filter(ADAPTIVE_ENHANCE_BIN, 'adaptive-enhance', image_bin, args)

def run_iagcwd(image_bin, args=()):
    return _run_png_filter(IAGCWD_BIN, 'iagcwd', image_bin, args)

def run_white_balance(image_bin, args=()):
    return _run_png_filter(WHITE_BALANCE_BIN, 'white-balance', image_bin, args)

def run_nafnet(image_bin, model):
    if model not in NAFNET_MODELS:
        raise RuntimeError(f'unhandled NAFNet model: {model}')
    weights = os.path.join(REALESRGAN_MODELS_DIR, NAFNET_MODELS[model])
    with gpu_guard.gpu_lock:
        return _run_png_filter(NAFNET_BIN, 'nafnet', image_bin, ['-m', weights])

def run_maxim(image_bin, model):
    if model not in MAXIM_MODELS:
        raise RuntimeError(f'unhandled Maxim model: {model}')
    weights = os.path.join(REALESRGAN_MODELS_DIR, MAXIM_MODELS[model])
    with gpu_guard.gpu_lock:
        return _run_png_filter(MAXIM_BIN, 'maxim', image_bin, ['-m', weights])

def _sr_decode_png(image_bin):
    try:
        im = Image.open(io.BytesIO(image_bin))
        im.load()
    except Exception as e:
        raise ValueError(f"cannot decode image: {e}") from e
    im = ImageOps.exif_transpose(im)
    if im.mode != 'RGB':
        im = im.convert('RGB')
    width, height = im.size
    buf = io.BytesIO()
    im.save(buf, format='PNG')
    return buf.getvalue(), width, height

def run_super_resolution(image_bin, model):
    if model not in SUPER_RESOLUTION_MODELS:
        raise RuntimeError(f'unhandled super resolution model: {model}')
    model_filename, _scale = SUPER_RESOLUTION_MODELS[model]
    model_path = os.path.join(REALESRGAN_MODELS_DIR, model_filename)
    png_bytes, _width, _height = _sr_decode_png(image_bin)

    with gpu_guard.gpu_lock:
        tmpdir = tempfile.mkdtemp(prefix='pixeldeck-sr-')
        try:
            in_path = os.path.join(tmpdir, 'input.png')
            out_path = os.path.join(tmpdir, 'output.png')
            with open(in_path, 'wb') as f:
                f.write(png_bytes)

            cmd = [
                REALESRGAN_BIN,
                '--model', model_path,
                '-i', in_path,
                '-o', out_path,
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode != 0:
                raise RuntimeError(
                    f"realesrgan failed (exit {res.returncode}): "
                    f"{res.stderr.decode('utf-8', 'replace')}"
                )
            if not os.path.exists(out_path):
                raise RuntimeError('realesrgan produced no output file')
            with open(out_path, 'rb') as f:
                return f.read()
        finally:
            for fname in os.listdir(tmpdir):
                try:
                    os.unlink(os.path.join(tmpdir, fname))
                except OSError:
                    pass
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass

def _ensure_png_bytes(image_bin):
    try:
        im = Image.open(io.BytesIO(image_bin))
        im.load()
    except Exception as e:
        raise ValueError(f"cannot decode image: {e}") from e
    im = ImageOps.exif_transpose(im)
    buf = io.BytesIO()
    im.save(buf, format='PNG')
    return buf.getvalue()

def run_lama_inpaint(image_bin, mask_bin, mode=None):
    png_bytes = _ensure_png_bytes(image_bin)
    mask_png = _ensure_png_bytes(mask_bin)

    with gpu_guard.gpu_lock:
        tmpdir = tempfile.mkdtemp(prefix='pixeldeck-lama-')
        try:
            image_path = os.path.join(tmpdir, 'image.png')
            mask_path = os.path.join(tmpdir, 'mask.png')
            output_path = os.path.join(tmpdir, 'output.png')
            with open(image_path, 'wb') as f:
                f.write(png_bytes)
            with open(mask_path, 'wb') as f:
                f.write(mask_png)

            cmd = [
                LAMA_INPAINT_BIN,
                '--image', image_path,
                '--mask', mask_path,
                '--output', output_path,
                '--weights', LAMA_WEIGHTS,
            ]
            if mode:
                cmd.append(f'--{mode}')

            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode != 0:
                raise RuntimeError(
                    f"lama-inpaint failed (exit {res.returncode}): "
                    f"{res.stderr.decode('utf-8', 'replace')}"
                )
            if not os.path.exists(output_path):
                raise RuntimeError('lama-inpaint produced no output file')
            with open(output_path, 'rb') as f:
                return f.read()
        finally:
            for fname in os.listdir(tmpdir):
                try:
                    os.unlink(os.path.join(tmpdir, fname))
                except OSError:
                    pass
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass

def run_rmbg(image_bin):
    in_png = _ensure_png_bytes(image_bin)
    with gpu_guard.gpu_lock:
        tmpdir = tempfile.mkdtemp(prefix='pixeldeck-rmbg-')
        in_path = os.path.join(tmpdir, 'in.png')
        out_path = os.path.join(tmpdir, 'out.png')
        try:
            with open(in_path, 'wb') as fh:
                fh.write(in_png)
            cmd = [
                RMBG_BIN,
                '--weights', RMBG_WEIGHTS,
                '-i', in_path,
                '-o', out_path,
            ]
            proc = subprocess.run(
                cmd,
                cwd=BIN_DIR,
                capture_output=True,
            )
            if not os.path.exists(out_path):
                raise RuntimeError(
                    'rmbg produced no output '
                    f'(code {proc.returncode}): ' + proc.stderr.decode(errors='replace')[-2000:]
                )
            with open(out_path, 'rb') as fh:
                return fh.read()
        finally:
            for fname in os.listdir(tmpdir):
                try:
                    os.unlink(os.path.join(tmpdir, fname))
                except OSError:
                    pass
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass

async def go_local(request, post, deliver_bin_image):
    if post['model'] in ('LaMa', 'LaMa (tile)', 'LaMa (sections)'):
        image_bin = post['image'].file.read()
        mask_bin = post['mask'].file.read()
        mode_map = {
            'LaMa': None,
            'LaMa (tile)': 'tile',
            'LaMa (sections)': 'sections',
        }
        mode = mode_map.get(post['model'])
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(
            None, run_lama_inpaint, image_bin, mask_bin, mode)
        await deliver_bin_image(bin_image)
        return
    if post['model'] in SUPER_RESOLUTION_MODELS:
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_super_resolution, image_bin, post['model'])
        await deliver_bin_image(bin_image)
        return
    if post['model'] in NAFNET_MODELS:
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_nafnet, image_bin, post['model'])
        await deliver_bin_image(bin_image)
        return
    if post['model'] in MAXIM_MODELS:
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_maxim, image_bin, post['model'])
        await deliver_bin_image(bin_image)
        return
    if post['model'] in (
        'Exposure Fusion',
        'Exposure Fusion Knee 0.95',
        'Exposure Fusion Knee 0.2',
        'Adaptive Enhancement',
    ):
        model_args = {
            'Exposure Fusion': [],
            'Exposure Fusion Knee 0.95': ['-k', '0.95'],
            'Exposure Fusion Knee 0.2': ['-k', '0.2'],
            'Adaptive Enhancement': ['--adaptive'],
        }[post['model']]
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_adaptive_enhance, image_bin, model_args)
        await deliver_bin_image(bin_image)
    elif post['model'] == 'Gamma Correction':
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_iagcwd, image_bin)
        await deliver_bin_image(bin_image)
    elif post['model'] in ('White Balance', 'White Balance (No Clip)'):
        model_args = ['--safe'] if post['model'] == 'White Balance (No Clip)' else []
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_white_balance, image_bin, model_args)
        await deliver_bin_image(bin_image)
    elif post['model'] == 'RMBG-2.0':
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_rmbg, image_bin)
        await deliver_bin_image(bin_image)
    else:
        raise web.HTTPBadRequest(text=f"unhandled model: {post['model']}")

def register_provider(register, get_config):
    handler = lambda req, post, deliver: go_local(req, post, deliver)

    register('local', 'Super Resolution', {
        'model': {
            'options': [
                'RealESRGAN x2plus',
                'RealESRGAN x4plus',
                'RealESRNet x4plus',
                '4x-RealisticRescaler',
            ],
            'default': 'RealESRGAN x2plus'
        }
    })(handler)

    register('local', 'Inpainting', {
        'model': {
            'options': ['LaMa', 'LaMa (tile)', 'LaMa (sections)'],
            'default': 'LaMa',
        },
    })(handler)

    register('local', 'Contrast', {
        'model': {
            'options': [
                'Exposure Fusion',
                'Exposure Fusion Knee 0.95',
                'Exposure Fusion Knee 0.2',
                'Adaptive Enhancement',
                'White Balance',
                'White Balance (No Clip)',
                'Gamma Correction',
            ],
            'default': 'Exposure Fusion',
        },
    })(handler)

    register('local', 'Enhance', {
        'model': {
            'options': [
                'NAFNet Deblur (fast)',
                'NAFNet Deblur (best)',
                'NAFNet Denoise (fast)',
                'NAFNet Denoise (best)',
                'NAFNet Video Deblur (best)',
            ],
            'default': 'NAFNet Deblur (fast)',
        },
    })(handler)

    register('local', 'Maxim', {
        'model': {
            'options': [
                'Maxim Low-light (LOL)',
                'Maxim Enhance (FiveK)',
                'Maxim Denoise (SIDD)',
                'Maxim Deblur (GoPro)',
                'Maxim Deblur (REDS)',
                'Maxim Deblur (RealBlur-R)',
                'Maxim Deblur (RealBlur-J)',
                'Maxim Derain (Rain13k)',
                'Maxim Derain (Raindrop)',
                'Maxim Dehaze (Indoor)',
                'Maxim Dehaze (Outdoor)',
            ],
            'default': 'Maxim Low-light (LOL)',
        },
    })(handler)

    register('local', 'Background Removal', {
        'model': {
            'options': [
                'RMBG-2.0',
            ],
            'default': 'RMBG-2.0',
        },
    })(handler)

    return True
