# Pixeldeck

Pixeldeck is a local web app for cleaning up product photographs: crop the
subject out of a white sweep, take the background away, upscale, inpaint,
white-balance and brighten, or hand the image to an AI editor — all from one
page, with undo.

It runs on your own machine. The heavy work is done by small standalone Rust
binaries that Pixeldeck downloads on install and runs as subprocesses, so there
is no Python image-processing stack to fight with and no build step for the
front end. Those engines are built on
[lightgpu](https://github.com/jacobsparts/lightgpu), our dependency-light CUDA
toolkit: hand-written CUDA kernels with matching pure-Rust implementations, and
a driver layer `dlopen`ed at run time. They need nothing at run time but libc
and, on a GPU, the CUDA driver — no toolkit, no cuDNN, no PyTorch, no Python.
Cloud image APIs are supported as well, but only if you put your own
credentials in `config.json`; without them those tools simply do not appear.

The server binds to `127.0.0.1` and has no authentication. Do not expose it to
a network.

## Tools

| menu | tools |
| --- | --- |
| Super Resolution | local RealESRGAN x2plus / x4plus, RealESRNet x4plus, 4x-RealisticRescaler; AILabTools upscalers; Replicate swin2sr, HAT, latent-sr and others |
| Inpainting | local LaMa, with optional tile and section modes; AILabTools erasure |
| Background Removal | local RMBG-2.0; Pixian; AILabTools; Replicate rembg, modnet, dis |
| Auto-Crop | local LocateAnything-3B, prompted for single items, kits or light items |
| Contrast | local exposure fusion, adaptive enhancement, white balance, gamma correction; AILabTools contrast |
| Enhance | AILabTools sharpness, dehaze and colour; Replicate scunet, NAFNet, night enhancement |
| AI Edit | Gemini image models, [OI] image models |
| Maxim | Replicate's Maxim models (denoise, deblur, derain, dehaze, low-light) |

Photo Box 2048 runs the whole product-photo sequence in one go: auto-crop, then
background removal, then a crop to the subject and a resize to 2048.

Everything else in the menubar is local and needs no credentials: rotate,
resize (with a high-quality Lanczos resampler), crop to the painted mask, erase
to the mask, undo and redo, PNG and JPG export.

## Requirements

- Linux on x86_64
- Python 3.10 or newer, with `venv`
- `curl`
- About 1.4 GB of disk, or about 5.6 GB with Auto-Crop (whose model is built
  from a 7.7 GB download, so that step wants ~13 GB free)

A GPU is optional. The engine binaries are CUDA builds that probe the driver at
start-up and fall back to the CPU backend, so they work either way. Run
`./install.sh --cpu-only` to fetch the smaller CPU-only builds instead.

## Install

```console
git clone https://github.com/jacobsparts/pixeldeck.git
cd pixeldeck
./install.sh
```

The installer creates `.venv`, downloads the engines and their weights into
`bin/`, and writes a `config.json` from `config.example.json`. It never mirrors
the weights: several of them are licensed for non-commercial use only and are
not ours to redistribute, so they are fetched from the release pages of the
engines that publish them, or built by the scripts those engines ship.

| option | effect |
| --- | --- |
| `--cpu-only` | download the CPU-only engine builds |
| `--no-rmbg` | skip the gated RMBG-2.0 checkpoint |
| `--no-locate` | skip the LocateAnything container (the big one) |
| `--service` | install and enable the systemd user unit |
| `--force` | re-download everything |

RMBG-2.0 is behind a licence gate on Hugging Face. Accept its terms on the
model page, then let the installer ask you for a read token on the terminal —
the token is passed straight to the downloader and is not written anywhere.
Ctrl-C is safe at any point: an aborted download is reported and the install
carries on, and re-running picks up what is missing.

## Run

```console
.venv/bin/python3 server.py
```

then open <http://127.0.0.1:8081/>.

`/` redirects to the main page, `static/index.html`, which is the batch editor:
drop a folder of images on it and work through them. `static/single-image.html`
is the same editor with a single image in it, for one-off edits.

```console
.venv/bin/python3 server.py --help
.venv/bin/python3 server.py --port 9000
.venv/bin/python3 server.py --host 0.0.0.0      # only if you know why
```

To run it as a service, `./install.sh --service` writes a systemd user unit
pointing at this directory:

```console
systemctl --user enable --now pixeldeck.service
journalctl --user -u pixeldeck.service -f
```

## Configure

`config.json` is the only place settings live. `config.example.json` is the
template and lists every section and key there is; the installer copies it, and
the **Config** button in the menubar edits it from the browser.

```json
{
  "gemini": { "api_key": "" },
  "pixian": { "username": "", "password": "" }
}
```

A section with no credentials is simply not registered, so those tools are
absent from the menus. Saving a change rebuilds the tool list on the spot —
paste a key and the menu appears, clear it and the menu goes away. Keys are
never sent back to the browser, and `config.json` is written mode 600.

Editing `config.json` in a text editor works too, but the tool list is built at
start-up, so restart the server afterwards to pick the change up.

Which section enables what is in [THIRD_PARTY.md](THIRD_PARTY.md).

## The local engines

`install.sh` puts these in `bin/`, and `bin/models/` holds their weights. Each
one is a plain command-line program that Pixeldeck runs with `subprocess`; you
can run them by hand the same way.

| engine | repository | binary | weights | tool |
| --- | --- | --- | --- | --- |
| Real-ESRGAN | [realesrgan-rs](https://github.com/jacobsparts/realesrgan-rs) | `realesrgan-linux-x86_64` | `models/RealESRGAN_*.safetensors`, `4x_RealisticRescaler_100000_G.safetensors` | Super Resolution |
| LaMa | [lama-inpaint-rs](https://github.com/jacobsparts/lama-inpaint-rs) | `lama-inpaint` | `models/big-lama.safetensors` | Inpainting |
| BiRefNet / RMBG-2.0 | [rmbg-rs](https://github.com/jacobsparts/rmbg-rs) | `rmbg-linux-x86_64` | `models/RMBG-2.0.safetensors` | Background Removal |
| LocateAnything-3B | [locate-anything-rs](https://github.com/jacobsparts/locate-anything-rs) | `locate-anything` | `models/locate-anything-allq8_0.laqt` | Auto-Crop |
| OpenCE exposure fusion, IAGCWD, white balance | [adaptive-enhance](https://github.com/jacobsparts/adaptive-enhance) | `adaptive-enhance`, `iagcwd`, `white-balance` | none | Contrast |

They are all built on [lightgpu](https://github.com/jacobsparts/lightgpu), our
dependency-light CUDA toolkit for inference engines: the CUDA driver API is
`dlopen`ed at run time, and every CUDA kernel has a matching pure-Rust
implementation, so `--no-default-features` yields a CPU build with no CUDA
toolchain at all. What that buys you is in `ldd` — the binaries link against
nothing but libc (plus the driver, if there is one):

```console
$ ldd bin/realesrgan-linux-x86_64
        linux-vdso.so.1  libgcc_s.so.1  libm.so.6  libc.so.6
```

All of them are GPU tools when a GPU is present, so only one may run at a time:
they are serialized by a single process-wide lock in `gpu_guard.py`, which is
enough because the server is the only thing that ever starts them.

Sources, versions and licences are in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

## Layout

```
server.py              the aiohttp app: routes, tool registry, config API
config.py              config.json and config.example.json
providers/             one module per image source, each registering its tools
plugins/               optional plugins (plugins/private/ is git-ignored)
static/                the front end: no build step, no bundler
static/index.html      the main page (batch editor)
static/single-image.html  the same editor for one image
crop_subject_vision.py Auto-Crop: prompts the detector and picks the box
gpu_guard.py           the lock that serializes the GPU binaries
gemini_edit.py         AI Edit against the Gemini image API
gpt_edit.py            AI Edit against the [OI] image API
bin/                   engines and weights, all downloaded (git-ignored)
```

## Plugins

A plugin is a Python module in `plugins/` (or in the git-ignored
`plugins/private/`) with a `setup(app, route, get_config)` function that can
register extra routes. A `plugins/<name>.js` next to it is concatenated into
`/pixeldeck/plugins.js` and loaded by the page, so a plugin can add UI as well
as endpoints. See [plugins/README.md](plugins/README.md).

## Licence

MIT, see [LICENSE](LICENSE). The engines and models it downloads, the vendored
front-end libraries, and the optional cloud services all have their own terms:
see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) and
[THIRD_PARTY.md](THIRD_PARTY.md).
