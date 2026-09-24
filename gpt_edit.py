"""Image editing/generation via OpenAI's Images API."""

import base64
import fcntl
import http.client
import json
import time
import uuid

import config

LOCK_FILE = '/tmp/gpt_edit_ratelimit.lock'
MIN_INTERVAL = 5  # seconds between requests

DEFAULT_MODEL = 'gpt-image-2'


def _api_key():
    """The OpenAI API key, read per request so config edits take effect at once."""
    return config.get_config('openai').get('api_key', '')


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


def _boundary():
    return f'----WebKitFormBoundary{uuid.uuid4().hex}'


def _multipart(fields, files, boundary):
    """Build multipart/form-data body.

    fields: list of (name, value)
    files: list of (name, filename, content_type, data_bytes)
    """
    parts = []
    for name, value in fields:
        parts.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f'{value}\r\n'.encode()
        )
    for name, filename, content_type, data in files:
        parts.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f'Content-Type: {content_type}\r\n\r\n'.encode()
            + data + b'\r\n'
        )
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts)


def _decode_image_response(data):
    images = data.get('data') or []
    if not images or not images[0].get('b64_json'):
        raise RuntimeError(f"No image in OpenAI response: {data}")

    out_bytes = base64.b64decode(images[0]['b64_json'])
    out_fmt = data.get('output_format') or 'png'
    out_mime = {
        'png': 'image/png',
        'jpeg': 'image/jpeg',
        'jpg': 'image/jpeg',
        'webp': 'image/webp',
    }.get(out_fmt, 'image/png')
    return out_bytes, out_mime


def _common_fields(model, prompt, image_config):
    fields = [
        ('model', model),
        ('prompt', prompt),
        ('n', '1'),
    ]
    if size := image_config.get('size'):
        fields.append(('size', size))
    if quality := image_config.get('quality'):
        fields.append(('quality', quality))
    if background := image_config.get('background'):
        fields.append(('background', background))
    fields.append(('output_format', 'png'))
    return fields


def _edit(image_bytes, mime_type, prompt, image_config, model, api_key):
    if not image_bytes:
        raise ValueError('image_bytes is required for mode=edit')
    ext = 'jpg' if mime_type == 'image/jpeg' else 'png'
    fields = _common_fields(model, prompt, image_config)
    if (input_fidelity := image_config.get('input_fidelity')) and model != 'gpt-image-2':
        fields.append(('input_fidelity', input_fidelity))

    boundary = _boundary()
    body = _multipart(
        fields,
        [('image[]', f'image.{ext}', mime_type, image_bytes)],
        boundary,
    )

    conn = http.client.HTTPSConnection('api.openai.com', 443)
    conn.request(
        'POST',
        '/v1/images/edits',
        body=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': f'multipart/form-data; boundary={boundary}',
        },
    )
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    data = json.loads(raw)
    if resp.status != 200:
        raise RuntimeError(f"OpenAI API error {resp.status}: {data}")
    return _decode_image_response(data)


def _generate(prompt, image_config, model, api_key):
    body = {
        'model': model,
        'prompt': prompt,
        'n': 1,
    }
    if size := image_config.get('size'):
        body['size'] = size
    if quality := image_config.get('quality'):
        body['quality'] = quality
    if background := image_config.get('background'):
        body['background'] = background
    body['output_format'] = 'png'

    conn = http.client.HTTPSConnection('api.openai.com', 443)
    conn.request(
        'POST',
        '/v1/images/generations',
        body=json.dumps(body),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
    )
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    data = json.loads(raw)
    if resp.status != 200:
        raise RuntimeError(f"OpenAI API error {resp.status}: {data}")
    return _decode_image_response(data)


def edit_image(image_bytes, mime_type, prompt, image_config=None, model=None, mode='edit'):
    """Edit or generate an image via OpenAI Images API.

    mode='edit' posts to /v1/images/edits with the input image.
    mode='generate' posts to /v1/images/generations with prompt only.
    Returns (image_bytes, mime_type).
    """
    _rate_limit()
    api_key = _api_key()
    model = model or DEFAULT_MODEL
    image_config = image_config or {}
    mode = (mode or 'edit').lower()
    if mode == 'edit':
        return _edit(image_bytes, mime_type, prompt, image_config, model, api_key)
    if mode == 'generate':
        return _generate(prompt, image_config, model, api_key)
    raise ValueError(f"unsupported mode: {mode}")
