#!/usr/bin/python3
"""Crop the main subject from a product photo using LocateAnything."""

import json
import os
import sys
import io
import subprocess
import tempfile
import urllib.request
import urllib.error
import http.client
import uuid
import math
from PIL import Image, ImageOps
import numpy as np

import gpu_guard

def auto_white_balance(img):
    """Automatic white point correction for product photos on white backgrounds.
    
    Samples the brightest pixels from the outer edge of the image (where the
    white background is), uses their per-channel values as the white reference,
    and scales each channel so that reference becomes 255.
    """
    is_pil = isinstance(img, Image.Image)
    if is_pil:
        arr = np.array(img)
    else:
        arr = img

    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)

    # Strip alpha if present
    has_alpha = arr.ndim == 3 and arr.shape[2] == 4
    if has_alpha:
        alpha = arr[:, :, 3]
        rgb = arr[:, :, :3].astype(np.float64)
    elif arr.ndim == 3:
        rgb = arr[:, :, :3].astype(np.float64)
    else:
        return img

    # Sample only from the outer edge of the image (the background border)
    h, w = rgb.shape[:2]
    border = max(1, min(h, w) // 20)  # 5% of the shorter dimension
    edge_mask = np.zeros((h, w), dtype=bool)
    edge_mask[:border, :] = True   # top
    edge_mask[-border:, :] = True  # bottom
    edge_mask[:, :border] = True   # left
    edge_mask[:, -border:] = True  # right

    edge_pixels = rgb[edge_mask]  # (N, 3)

    # Brightest edge pixels by luminance - the white background reference
    lum = edge_pixels.max(axis=1)
    threshold = np.percentile(lum, 99)
    bright = edge_pixels[lum >= threshold]

    # Per-channel white point from the brightest edge pixels
    white_point = bright.mean(axis=0)

    # Avoid division by zero
    white_point = np.maximum(white_point, 1.0)

    # Scale each channel so the white point maps to 255
    result = np.zeros_like(rgb)
    for c in range(3):
        result[:, :, c] = rgb[:, :, c] * (255.0 / white_point[c])

    result = np.clip(result, 0, 255).astype(np.uint8)

    if has_alpha:
        result = np.dstack([result, alpha])

    if is_pil:
        return Image.fromarray(result)
    return result

MAX_DETECTION_PIXELS = 500000
PROMPT = 'isolated item'

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin')
LOCATE_ANYTHING_BIN = os.path.join(BIN_DIR, 'locate-anything')
LOCATE_ANYTHING_MODEL = os.path.join(BIN_DIR, 'models', 'locate-anything-allq8_0.laqt')


def _enhance_image_bytes(image_bytes):
    """Run image_bytes through exposure fusion (adaptive-enhance) and return new PNG bytes, or None on failure."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        enhanced_img = adaptive_enhance_image(img)
        if enhanced_img is img:
            return None
        buf = io.BytesIO()
        enhanced_img.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        sys.stderr.write(f"Failed to enhance image_bytes: {e}\n")
        return None

def detect_subject(image_bytes, multi=False, prompt=None):
    """Send image to LocateAnything and return (ymin, xmin, ymax, xmax) in 0-1000 range.
    Uses 3 fallback tiers:
      Tier 1: User's selected prompt on original image
      Tier 2: Alternative prompt on original image
      Tier 3: Selected & alternative prompts on exposure fusion enhanced image
    """
    primary_prompt = prompt or PROMPT
    fallback_prompt = 'all foreground object(s)' if primary_prompt == 'isolated item' else 'isolated item'

    # (image_data, prompt_label, is_enhanced)
    attempts = [
        (image_bytes, primary_prompt, False),
        (image_bytes, fallback_prompt, False),
        (image_bytes, 'main subject', False),
    ]

    last_error = None
    for data, p, enhanced in attempts:
        try:
            boxes = detect_subjects(data, multi=multi, prompt=p)
            if not boxes:
                continue
            ymin = min(b[0] for b in boxes)
            xmin = min(b[1] for b in boxes)
            ymax = max(b[2] for b in boxes)
            xmax = max(b[3] for b in boxes)
            # If the box covers >= 98% in both dimensions, treat as full-canvas failure
            if (xmax - xmin) >= 980 and (ymax - ymin) >= 980:
                continue
            return (ymin, xmin, ymax, xmax)
        except Exception as e:
            last_error = e
            continue

    # Tier 3: If standard attempts failed or gave full-canvas, try exposure fusion enhancement
    enhanced_png = _enhance_image_bytes(image_bytes)
    if enhanced_png:
        for p in [primary_prompt, fallback_prompt]:
            try:
                boxes = detect_subjects(enhanced_png, multi=multi, prompt=p)
                if not boxes:
                    continue
                ymin = min(b[0] for b in boxes)
                xmin = min(b[1] for b in boxes)
                ymax = max(b[2] for b in boxes)
                xmax = max(b[3] for b in boxes)
                if (xmax - xmin) >= 980 and (ymax - ymin) >= 980:
                    continue
                return (ymin, xmin, ymax, xmax)
            except Exception as e:
                last_error = e
                continue

    if last_error:
        raise last_error
    raise RuntimeError('No localized objects found (all fallback tiers exhausted).')


def _detection_to_box(detection, img_w, img_h):
    raw_box = detection.get('box')
    if not raw_box or len(raw_box) != 4:
        return None

    x1, y1, x2, y2 = [float(v) for v in raw_box]
    xmin = max(0, min(1000, int(x1 * 1000 / img_w)))
    ymin = max(0, min(1000, int(y1 * 1000 / img_h)))
    xmax = max(0, min(1000, int(x2 * 1000 / img_w)))
    ymax = max(0, min(1000, int(y2 * 1000 / img_h)))
    if xmax <= xmin or ymax <= ymin:
        return None
    return (ymin, xmin, ymax, xmax)


def _combine_boxes(boxes):
    ymin = min(b[0] for b in boxes)
    xmin = min(b[1] for b in boxes)
    ymax = max(b[2] for b in boxes)
    xmax = max(b[3] for b in boxes)
    return (ymin, xmin, ymax, xmax)


def detect_subjects(image_bytes, multi=True, prompt=None, pad_fraction=0.05):
    """Send image to LocateAnything and return list of (ymin, xmin, ymax, xmax) tuples."""
    if pad_fraction and pad_fraction > 0:
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        orig_w, orig_h = img.size
        pad_w = max(1, int(orig_w * pad_fraction))
        pad_h = max(1, int(orig_h * pad_fraction))
        arr = np.array(img)
        edge_pixels = np.concatenate([arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]], axis=0)
        bg_color = tuple(int(c) for c in edge_pixels.mean(axis=0).round())
        padded = ImageOps.expand(img, border=(pad_w, pad_h, pad_w, pad_h), fill=bg_color)
        pw, ph = padded.size
        ptw = max(28, int(math.ceil(pw / 28) * 28))
        pth = max(28, int(math.ceil(ph / 28) * 28))
        if (ptw, pth) != (pw, ph):
            padded = padded.resize((ptw, pth), Image.LANCZOS)
        buf = io.BytesIO()
        padded.save(buf, format='PNG')
        raw_boxes = detect_subjects(buf.getvalue(), multi=multi, prompt=prompt, pad_fraction=0)
        mapped_boxes = []
        for b in raw_boxes:
            y1_pad = (b[0] * ph / 1000.0) - pad_h
            x1_pad = (b[1] * pw / 1000.0) - pad_w
            y2_pad = (b[2] * ph / 1000.0) - pad_h
            x2_pad = (b[3] * pw / 1000.0) - pad_w
            y1 = max(0, min(1000, int(round((y1_pad / orig_h) * 1000.0))))
            x1 = max(0, min(1000, int(round((x1_pad / orig_w) * 1000.0))))
            y2 = max(0, min(1000, int(round((y2_pad / orig_h) * 1000.0))))
            x2 = max(0, min(1000, int(round((x2_pad / orig_w) * 1000.0))))
            if x2 > x1 and y2 > y1:
                mapped_boxes.append((y1, x1, y2, x2))
        return mapped_boxes
    query = prompt or PROMPT
    with gpu_guard.gpu_lock:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(image_bytes)
            local_image_path = f.name

        try:
            cmd = [
                LOCATE_ANYTHING_BIN,
                'detect',
                '--model', LOCATE_ANYTHING_MODEL,
                local_image_path,
                query,
            ]
            proc = subprocess.run(
                cmd,
                cwd=BIN_DIR,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                err = proc.stderr.strip()
                raise RuntimeError(f'locate-anything failed (code {proc.returncode}): {err}')

            try:
                data = json.loads(proc.stdout)
            except Exception as e:
                err = proc.stderr.strip()
                raise RuntimeError(f'locate-anything produced invalid JSON output ({e}): {proc.stdout[:500]} | stderr: {err}')

            img_w, img_h = Image.open(io.BytesIO(image_bytes)).size
            boxes = []
            for detection in data.get('detections', []):
                box = _detection_to_box(detection, img_w, img_h)
                if box is not None:
                    boxes.append(box)

            if not boxes:
                labels = [d.get('label', 'unknown') for d in data.get('detections', [])]
                raise RuntimeError(f'No localized objects found. Detected: {labels}')

            return boxes
        finally:
            try:
                os.unlink(local_image_path)
            except FileNotFoundError:
                pass


BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin')

def adaptive_enhance_image(img, args=()):
    enhance_bin = os.path.join(BIN_DIR, 'adaptive-enhance')
    if not os.path.exists(enhance_bin):
        return img
    try:
        png_buf = io.BytesIO()
        img.save(png_buf, format='PNG')
        proc = subprocess.run(
            [enhance_bin] + list(args),
            input=png_buf.getvalue(),
            capture_output=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            return Image.open(io.BytesIO(proc.stdout)).convert('RGB')
        sys.stderr.write(f"adaptive-enhance failed (code {proc.returncode}): {proc.stderr.decode(errors='replace')}\n")
    except Exception as e:
        sys.stderr.write(f"adaptive-enhance error: {e}\n")
    return img


def iagcwd_image(img, args=()):
    iagcwd_bin = os.path.join(BIN_DIR, 'iagcwd')
    if not os.path.exists(iagcwd_bin):
        return img
    try:
        png_buf = io.BytesIO()
        img.save(png_buf, format='PNG')
        proc = subprocess.run(
            [iagcwd_bin] + list(args),
            input=png_buf.getvalue(),
            capture_output=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            return Image.open(io.BytesIO(proc.stdout)).convert('RGB')
        sys.stderr.write(f"iagcwd failed (code {proc.returncode}): {proc.stderr.decode(errors='replace')}\n")
    except Exception as e:
        sys.stderr.write(f"iagcwd error: {e}\n")
    return img


def light_item_preprocess(img):
    """Exposure Fusion (default knee) followed by two passes of Gamma Correction (iagcwd)."""
    img = adaptive_enhance_image(img)
    img = iagcwd_image(img)
    img = iagcwd_image(img)
    return img


def resize_for_llm(img, max_edge=None, max_pixels=MAX_DETECTION_PIXELS, white_balance=False, autocontrast=True, light_item=False, iagcwd=False):
    """Resize image for detection with each dimension rounded up to a multiple of 28."""
    resized = img.convert('RGB')
    w, h = resized.size
    if max_pixels and w * h > max_pixels:
        scale = (max_pixels / (w * h)) ** 0.5
        target_w = max(28, int(math.ceil((w * scale) / 28) * 28))
        target_h = max(28, int(math.ceil((h * scale) / 28) * 28))
        resized = resized.resize((target_w, target_h), Image.LANCZOS)
    if max_edge:
        resized.thumbnail((max_edge, max_edge))
    if light_item:
        try:
            resized = light_item_preprocess(resized)
        except Exception as e:
            sys.stderr.write(f"light_item preprocess failed: {e}\n")
    elif iagcwd:
        try:
            resized = iagcwd_image(resized)
        except Exception as e:
            sys.stderr.write(f"iagcwd failed: {e}\n")
    elif autocontrast:
        try:
            resized = ImageOps.autocontrast(resized)
        except Exception as e:
            sys.stderr.write(f"autocontrast failed: {e}\n")
    elif white_balance:
        try:
            resized = auto_white_balance(resized)
        except Exception as e:
            sys.stderr.write(f"auto_white_balance failed: {e}\n")
    buf = io.BytesIO()
    resized.save(buf, format='PNG')
    return buf.getvalue()


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_file> <output_file>", file=sys.stderr)
        sys.exit(1)

    input_path, output_path = sys.argv[1], sys.argv[2]

    img = Image.open(input_path)
    orig_w, orig_h = img.size

    image_bytes = resize_for_llm(img)
    ymin, xmin, ymax, xmax = detect_subject(image_bytes)

    px_xmin = int(xmin * orig_w / 1000)
    px_ymin = int(ymin * orig_h / 1000)
    px_xmax = int(xmax * orig_w / 1000)
    px_ymax = int(ymax * orig_h / 1000)
    pad_x = max(50, int((px_xmax - px_xmin) * 0.10))
    pad_y = max(50, int((px_ymax - px_ymin) * 0.10))
    crop_box = (
        max(0, px_xmin - pad_x),
        max(0, px_ymin - pad_y),
        min(orig_w, px_xmax + pad_x),
        min(orig_h, px_ymax + pad_y),
    )
    if crop_box == (0, 0, orig_w, orig_h):
        raise RuntimeError('LocateAnything returned a full-image box; refusing to return the original image as an Auto-Crop result')

    cropped = img.crop(crop_box)
    cropped.save(output_path)
    print(f"Cropped {orig_w}x{orig_h} -> {cropped.size[0]}x{cropped.size[1]} -> {output_path}")


if __name__ == '__main__':
    main()
