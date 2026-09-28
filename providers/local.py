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
SCUNET_BIN = os.path.join(BIN_DIR, 'scunet-linux-x86_64')
IFAN_BIN = os.path.join(BIN_DIR, 'ifan-linux-x86_64')
IFAN_WEIGHTS = os.path.join(BIN_DIR, 'models', 'IFAN.safetensors')
NIGHTENH_BIN = os.path.join(BIN_DIR, 'nightenh-linux-x86_64')
SWIN2SR_BIN = os.path.join(BIN_DIR, 'swin2sr-linux-x86_64')

SUPER_RESOLUTION_MODELS = {
    'RealESRGAN x2plus': ('RealESRGAN_x2plus.safetensors', 2),
    'RealESRGAN x4plus': ('RealESRGAN_x4plus.safetensors', 4),
    'RealESRNet x4plus': ('RealESRNet_x4plus.safetensors', 4),
    '4x-RealisticRescaler': ('4x_RealisticRescaler_100000_G.safetensors', 4),
}

# Swin2SR: the second engine in the Super Resolution menu. The file decides both
# the task and the scale - there is no flag for either - so the menu labels name
# the checkpoint and this table says which file each label means. The names are
# the authors': classical is an image that was resized down with a plain
# resampler, real-world is one from a camera (real sensor noise, JPEG), and
# compressed is one that has been through a codec. The lightweight x2 is the
# small, fast model.
SWIN2SR_MODELS = {
    'Swin2SR Classical x4': 'swin2sr-classical-x4.safetensors',
    'Swin2SR Classical x2': 'swin2sr-classical-x2.safetensors',
    'Swin2SR Real-World x4': 'swin2sr-realworld-x4.safetensors',
    'Swin2SR Lightweight x2': 'swin2sr-lightweight-x2.safetensors',
    'Swin2SR Compressed x4': 'swin2sr-compressed-x4.safetensors',
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

# SCUNet: denoising, and the checkpoint alone says which kind. The two `real`
# models are the authors' blind ones - trained on a shuffled sequence of blur,
# noise, resampling and compression rather than a fixed amount of noise - and
# are what to reach for on a photograph from a camera. The sigma-numbered ones
# expect the amount of Gaussian noise they are named for. These are the five
# colour checkpoints the authors publish. The three grayscale ones are not
# offered: they take a single-channel image, and pairing one with a colour
# picture is an error the engine refuses by name, so an entry for them would be
# a trap rather than a tool.
SCUNET_MODELS = {
    'SCUNet Denoise (real photos)': 'scunet-color-real-psnr.safetensors',
    'SCUNet Denoise (real photos, sharper)': 'scunet-color-real-gan.safetensors',
    'SCUNet Denoise (sigma 15)': 'scunet-color-15.safetensors',
    'SCUNet Denoise (sigma 25)': 'scunet-color-25.safetensors',
    'SCUNet Denoise (sigma 50)': 'scunet-color-50.safetensors',
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

def run_scunet(image_bin, model):
    if model not in SCUNET_MODELS:
        raise RuntimeError(f'unhandled SCUNet model: {model}')
    weights = os.path.join(REALESRGAN_MODELS_DIR, SCUNET_MODELS[model])
    png_bytes = _ensure_png_bytes(image_bin)

    with gpu_guard.gpu_lock:
        tmpdir = tempfile.mkdtemp(prefix='pixeldeck-scunet-')
        try:
            in_path = os.path.join(tmpdir, 'input.png')
            out_path = os.path.join(tmpdir, 'output.png')
            with open(in_path, 'wb') as f:
                f.write(png_bytes)

            # Unlike NAFNet and MAXIM, this engine takes file paths rather than
            # streaming a PNG on stdin, so it needs the temporary directory the
            # Real-ESRGAN path also uses.
            cmd = [SCUNET_BIN, '-m', weights, '-i', in_path, '-o', out_path]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode != 0 or not os.path.exists(out_path):
                err = res.stderr.decode('utf-8', 'replace')
                raise EngineError(_engine_message('scunet', res.returncode, err))
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

# IFAN is the one engine here that will not run from a bare command line on a
# machine with no CUDA driver: every other engine picks its device at parse time
# and falls back to its CPU path by itself, while IFAN answers the default with
# "this build has no CUDA backend ...; pass --cpu". Detect it from the ONE
# message that means it, once, and remember the answer rather than re-running the
# pass to find out again.
_IFAN_WANTS_CPU = [False]

def run_ifan(image_bin):
    # IFAN restores a defocused photo by predicting a per-pixel filter tensor and
    # applying it with an adaptive convolution, rather than predicting the image
    # itself, so there is one checkpoint and no option to choose - `-m` is the
    # whole configuration. It takes its PNG on stdin and writes it to stdout, so
    # it needs no temporary directory; the GPU is used when a driver is there and
    # the CPU path when it is not. `--cpu` is passed before `-m` because the flag
    # position the engine accepts is `-m <weights> [--cpu]` and the weights path
    # is the only argument that takes a value.
    args = ['-m', IFAN_WEIGHTS]
    if _IFAN_WANTS_CPU[0]:
        args.append('--cpu')
    with gpu_guard.gpu_lock:
        try:
            return _run_png_filter(IFAN_BIN, 'ifan', image_bin, args)
        except EngineError as e:
            if _IFAN_WANTS_CPU[0] or 'has no CUDA backend' not in str(e):
                raise
            _IFAN_WANTS_CPU[0] = True
            return _run_png_filter(IFAN_BIN, 'ifan', image_bin, args + ['--cpu'])
# nightenh: one architecture, two released checkpoints, and the checkpoint
# alone picks what the model was trained for. `-m` is the whole configuration.
# The two cases are not interchangeable and the engine cannot tell you that you
# picked the wrong one - the light-effects suppression model brightens a night
# photo 1.21x where the low-light one brightens it 2.51x - so the labels say
# which is which.
NIGHTENH_MODELS = {
    'Night Enhancement (low light)': 'nightenh-lol.safetensors',
    'Light Effects Suppression': 'nightenh-delighteffects.safetensors',
}

def run_nightenh(image_bin, model):
    if model not in NIGHTENH_MODELS:
        raise RuntimeError(f'unhandled nightenh model: {model}')
    weights = os.path.join(REALESRGAN_MODELS_DIR, NIGHTENH_MODELS[model])
    with gpu_guard.gpu_lock:
        return _run_png_filter(NIGHTENH_BIN, 'nightenh', image_bin, ['-m', weights])

def run_swin2sr(image_bin, model):
    # Swin2SR streams like NAFNet and MAXIM: `-m` is the whole configuration
    # (the file decides the task and the scale) and the PNG comes in on stdin and
    # goes out on stdout. Like every engine here it falls back to the CPU when
    # there is no usable driver, and it says so on stderr; `--device gpu` typed
    # by hand is what turns that into an error, and nothing here types it.
    if model not in SWIN2SR_MODELS:
        raise RuntimeError(f'unhandled Swin2SR model: {model}')
    weights = os.path.join(REALESRGAN_MODELS_DIR, SWIN2SR_MODELS[model])
    # `--tile auto` IS NOT OPTIONAL FOR ORDINARY PHOTOS. The whole-image pass the
    # engine defaults to is the exact one, but a 1024-pixel-tall photo pads to
    # 1032 and one token per padded pixel runs into `grid.y`'s 65535 blocks of 16
    # rows - a LAUNCH limit of 1023 pixels a side, not a memory one - so the
    # default refuses an image of perfectly ordinary size. `auto` runs one pass
    # when it fits and sizes a tile when it does not, and says which it chose.
    with gpu_guard.gpu_lock:
        return _run_png_filter(SWIN2SR_BIN, 'swin2sr', image_bin, ['-m', weights, '--tile', 'auto'])

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

            # `--tile 512` KEEPS A 4x PASS INSIDE THE CARD. The engine sizes its
            # activation arena from what will actually run, and a whole-image 4x
            # pass on a 725x1024 photo wants about 9 GiB of head planes - more
            # than the 8 GiB card this runs on, and more than most. A 512-pixel
            # tile with the engine's 10 pixels of context costs a fraction of the
            # seamed area and turns a hard `cuMemAlloc` failure into a result;
            # the tile seams are measured in the engine's README. The CPU path
            # ignores the flag (only the GPU path tiles), so this is free there.
            cmd = [
                REALESRGAN_BIN,
                '--model', model_path,
                '--tile', '512',
                '-i', in_path,
                '-o', out_path,
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode != 0:
                # The engine's own lines are written for this reader, so they are
                # shown as they stand rather than behind a Python exception name.
                raise EngineError(_engine_message(
                    'realesrgan', res.returncode, res.stderr.decode('utf-8', 'replace')))
            if not os.path.exists(out_path):
                raise EngineError('realesrgan produced no output file')
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
    if post['model'] in SCUNET_MODELS:
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_scunet, image_bin, post['model'])
        await deliver_bin_image(bin_image)
        return
    if post['model'] == 'IFAN Defocus Deblur':
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_ifan, image_bin)
        await deliver_bin_image(bin_image)
        return
    if post['model'] in NIGHTENH_MODELS:
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_nightenh, image_bin, post['model'])
        await deliver_bin_image(bin_image)
        return
    if post['model'] in SWIN2SR_MODELS:
        image_bin = post['image'].file.read()
        loop = asyncio.get_event_loop()
        bin_image = await loop.run_in_executor(None, run_swin2sr, image_bin, post['model'])
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

    # Two engines share this menu. The engine is named in every label because
    # that is what tells the implementations apart, and the checkpoint names are
    # the authors' own: Real-ESRGAN trained on a clean downsample, Swin2SR's
    # real-world checkpoint on real sensor damage and JPEG artefacts, and its
    # compressed one on an image whose detail a codec has already thrown away.
    register('local', 'Super Resolution', {
        'model': {
            'options': [
                'RealESRGAN x2plus',
                'RealESRGAN x4plus',
                'RealESRNet x4plus',
                '4x-RealisticRescaler',
                'Swin2SR Classical x4',
                'Swin2SR Classical x2',
                'Swin2SR Real-World x4',
                'Swin2SR Lightweight x2',
                'Swin2SR Compressed x4',
            ],
            'description': {
                'Swin2SR Classical x4': 'for an image that was simply resized down 4x',
                'Swin2SR Classical x2': 'the same, for a 2x upscale',
                'Swin2SR Real-World x4': 'for a photograph: trained on real camera damage and JPEG artefacts',
                'Swin2SR Lightweight x2': 'a sixth of the size and about ten times faster, visibly softer',
                'Swin2SR Compressed x4': 'for an image that has been through a codec, where the detail has been thrown away',
            },
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

    # The menus below are the FUNCTIONS, not the engines. Three of these
    # functions have more than one implementation here, and which one is right
    # is a property of the picture rather than of the engine: NAFNet is trained
    # on a fixed degradation and is the one to reach for when the blur or noise
    # is uniform, SCUNet's `real` checkpoints are blind models for a photograph
    # from a camera, MAXIM covers the weather and the harder motion blurs, and
    # IFAN predicts a per-pixel filter tensor so it is the only one that handles
    # defocus specifically. The engine is named in every label because that is
    # what tells the implementations apart; the menu is named for the job.
    #
    # Rain and haze are in this menu rather than in one of their own: both are a
    # degraded view rather than a separate restoration task - rain streaks and
    # droplets are blur across a differently-shaped kernel, and haze is a
    # veiling glare whose removal restores local contrast - so the question a
    # user is answering ("what is wrong with this picture?") puts them here, and
    # MAXIM is the engine that covers them.
    register('local', 'Deblur', {
        'model': {
            'options': [
                'NAFNet Deblur (fast)',
                'NAFNet Deblur (best)',
                'NAFNet Video Deblur (best)',
                'IFAN Defocus Deblur',
                'Maxim Deblur (GoPro)',
                'Maxim Deblur (REDS)',
                'Maxim Deblur (RealBlur-R)',
                'Maxim Deblur (RealBlur-J)',
                'Maxim Derain (Rain13k)',
                'Maxim Derain (Raindrop)',
                'Maxim Dehaze (Indoor)',
                'Maxim Dehaze (Outdoor)',
            ],
            'default': 'NAFNet Deblur (fast)',
        },
    })(handler)

    register('local', 'Denoise', {
        'model': {
            'options': [
                'NAFNet Denoise (fast)',
                'NAFNet Denoise (best)',
                'SCUNet Denoise (real photos)',
                'SCUNet Denoise (real photos, sharper)',
                'SCUNet Denoise (sigma 15)',
                'SCUNet Denoise (sigma 25)',
                'SCUNet Denoise (sigma 50)',
                'Maxim Denoise (SIDD)',
            ],
            'default': 'SCUNet Denoise (real photos)',
        },
    })(handler)

    register('local', 'Low-Light', {
        'model': {
            'options': [
                'Maxim Low-light (LOL)',
                'Maxim Enhance (FiveK)',
                'Night Enhancement (low light)',
                'Light Effects Suppression',
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
