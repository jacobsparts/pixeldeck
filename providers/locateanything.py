import io
import asyncio
from PIL import Image
import crop_subject_vision as crop_subject

async def go_auto_crop(request, post, deliver_bin_image):
    image_bin = post['image'].file.read()
    model = post.get('model', 'Single Item')
    prompt = 'all foreground object(s)' if model == 'Kit / Multi-Item' else 'isolated item'
    use_light_item = (model == 'Light Item')
    loop = asyncio.get_event_loop()

    def do_crop():
        img = Image.open(io.BytesIO(image_bin))
        orig_w, orig_h = img.size
        image_bytes = crop_subject.resize_for_llm(img, light_item=use_light_item)
        ymin, xmin, ymax, xmax = crop_subject.detect_subject(image_bytes, multi=True, prompt=prompt)
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
        buf = io.BytesIO()
        cropped.save(buf, format='PNG')
        return buf.getvalue()

    bin_image = await loop.run_in_executor(None, do_crop)
    await deliver_bin_image(bin_image)

def register_provider(register, get_config):
    handler = lambda req, post, deliver: go_auto_crop(req, post, deliver)
    register('locateanything', 'Auto-Crop', {
        'model': {
            'options': [
                'Single Item',
                'Kit / Multi-Item',
                'Light Item',
            ],
            'default': 'Single Item',
        },
    })(handler)
    return True
