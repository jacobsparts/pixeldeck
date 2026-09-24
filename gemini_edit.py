"""Image editing/generation via Gemini Interactions API."""

import base64
import fcntl
import http.client
import json
import time
import urllib.request

import config

LOCK_FILE = '/tmp/gemini_edit_ratelimit.lock'
MIN_INTERVAL = 5  # seconds between requests

DEFAULT_MODEL = 'gemini-3.1-flash-image'


def _api_key():
    """The Gemini API key, read per request so config edits take effect at once."""
    return config.get_config('gemini').get('api_key', '')


def _rate_limit():
    """Ensure at least MIN_INTERVAL seconds between API requests across processes."""
    fd = open(LOCK_FILE, 'a+')
    fcntl.flock(fd, fcntl.LOCK_EX)
    fd.seek(0)
    raw = fd.read().strip()
    last = float(raw) if raw else 0
    wait = MIN_INTERVAL - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    fd.seek(0)
    fd.truncate()
    fd.write(str(time.monotonic()))
    fd.flush()
    fcntl.flock(fd, fcntl.LOCK_UN)
    fd.close()


def _extract_image(data):
    """Find the first image content block in an Interactions response."""
    output_image = data.get('output_image')
    if isinstance(output_image, dict) and (output_image.get('data') or output_image.get('uri')):
        return output_image

    for step in data.get('steps') or []:
        if step.get('type') != 'model_output':
            continue
        for part in step.get('content') or []:
            if part.get('type') == 'image' and (part.get('data') or part.get('uri')):
                return part
    return None


def _download_uri(uri, api_key):
    req = urllib.request.Request(uri, headers={'x-goog-api-key': api_key})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read(), resp.headers.get('Content-Type')


def edit_image(image_bytes, mime_type, prompt, image_config=None, model=None, mode='edit'):
    """Send a prompt (and optionally an image) to Gemini Interactions.

    mode='edit' includes the input image; mode='generate' is prompt-only.
    Returns (image_bytes, mime_type).
    """
    _rate_limit()
    api_key = _api_key()
    model = model or DEFAULT_MODEL
    image_config = image_config or {}
    mode = (mode or 'edit').lower()
    if mode not in ('edit', 'generate'):
        raise ValueError(f"unsupported mode: {mode}")

    response_format = {'type': 'image'}
    if aspect_ratio := image_config.get('aspect_ratio') or image_config.get('aspectRatio'):
        response_format['aspect_ratio'] = aspect_ratio
    if image_size := image_config.get('image_size') or image_config.get('imageSize'):
        response_format['image_size'] = image_size
    if out_mime := image_config.get('mime_type') or image_config.get('mimeType'):
        response_format['mime_type'] = out_mime

    input_parts = [{'type': 'text', 'text': prompt}]
    if mode == 'edit':
        if not image_bytes:
            raise ValueError('image_bytes is required for mode=edit')
        input_parts.append({
            'type': 'image',
            'data': base64.b64encode(image_bytes).decode(),
            'mime_type': mime_type,
        })

    body = {
        'model': model,
        'input': input_parts,
        'response_format': response_format,
        'store': False,
    }

    conn = http.client.HTTPSConnection('generativelanguage.googleapis.com', 443)
    conn.request(
        'POST',
        '/v1beta/interactions',
        body=json.dumps(body),
        headers={
            'Content-Type': 'application/json',
            'x-goog-api-key': api_key,
        },
    )
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    data = json.loads(raw)

    if resp.status != 200:
        raise RuntimeError(f"Gemini Interactions API error {resp.status}: {data}")

    image = _extract_image(data)
    if not image:
        raise RuntimeError(f"No image in Gemini Interactions response: {data}")

    out_mime = image.get('mime_type') or 'image/png'
    if image.get('data'):
        out_bytes = base64.b64decode(image['data'])
        return out_bytes, out_mime

    if image.get('uri'):
        out_bytes, header_mime = _download_uri(image['uri'], api_key)
        return out_bytes, header_mime or out_mime

    raise RuntimeError(f"Image content missing data/uri: {image}")
