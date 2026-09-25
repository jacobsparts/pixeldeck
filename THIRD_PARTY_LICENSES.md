# Third-party licenses and attribution

Pixeldeck itself is MIT-licensed (see [LICENSE](LICENSE)). It is a front end:
almost everything it does with an image is done by something else, and those
somethings have their own terms.

## Vendored front-end libraries

These are checked into `static/` and served as-is.

| library | version | license | copyright |
| --- | --- | --- | --- |
| [Vue](https://github.com/vuejs/core) | 3.2.47 | MIT | (c) 2013-present, Yuxi (Evan) You |
| [pica](https://github.com/nodeca/pica) | 9.x | MIT | (c) 2014-2024 Vitaly Puzrin |
| [JSZip](https://github.com/Stuk/jszip) | 3.10.1 | MIT or GPLv3 | (c) 2009-2016 Stuart Knightley |

`static/dropdown-menu.js`, `static/masker.js`, `static/pixeldeck-editor.js`,
`static/pixeldeck-editor.css`, `static/index.html` and
`static/single-image.html` are part of Pixeldeck.

## Engine binaries

`install.sh` downloads prebuilt binaries from the release pages of these
repositories. They are not distributed with Pixeldeck.

The five inference engines are built on
[lightgpu](https://github.com/jacobsparts/lightgpu), our dependency-light CUDA
toolkit for inference engines: hand-written CUDA kernels with matching pure-Rust
implementations, and a driver layer that is `dlopen`ed at run time. The contrast
tools are plain Rust, with no CUDA in them. That is why the binaries have no
runtime dependencies beyond libc (and an optional CUDA driver) — no CUDA
toolkit, no cuDNN, no PyTorch, no Python.

| engine | repository | license |
| --- | --- | --- |
| Real-ESRGAN upscaling | [jacobsparts/realesrgan-rs](https://github.com/jacobsparts/realesrgan-rs) | MIT (c) 2026 Jacob Stoner |
| LaMa inpainting | [jacobsparts/lama-inpaint-rs](https://github.com/jacobsparts/lama-inpaint-rs) | Apache-2.0 |
| RMBG-2.0 background removal | [jacobsparts/rmbg-rs](https://github.com/jacobsparts/rmbg-rs) | MIT (c) 2026 Jacob Stoner |
| LocateAnything detection | [jacobsparts/locate-anything-rs](https://github.com/jacobsparts/locate-anything-rs) | MIT (c) 2026 Ettore Di Giacinto and the LocalAI team |
| NAFNet deblurring and denoising | [jacobsparts/nafnet-rs](https://github.com/jacobsparts/nafnet-rs) | MIT (c) 2026 Jacob Stoner |
| exposure, tone and color correction | [jacobsparts/adaptive-enhance](https://github.com/jacobsparts/adaptive-enhance) | MIT (c) 2017 Zhenqiang Ying |

`adaptive-enhance` is a port of the `adaptiveImageEnhancement` module of
[OpenCE](https://github.com/baidut/OpenCE) (MIT) and implements the CAIP 2017
exposure-fusion method; `iagcwd` implements the improved adaptive gamma
correction of Cao et al., 2018. Its `NOTICE` file carries the original
attribution and is included in its release tarball.

`lama-inpaint-rs` reimplements the [saicinpainting](https://github.com/advimman/lama)
network; `rmbg-rs` reimplements the BiRefNet architecture, whose Swin
Transformer backbone is MIT-licensed (Microsoft Research); `nafnet-rs`
reimplements [NAFNet](https://github.com/megvii-research/NAFNet) (MIT,
(c) 2022 megvii-model).

## Model weights

`install.sh` downloads these too, or builds them from the upstream checkpoint.
**None of them are distributed with Pixeldeck**, and two of them are licensed
for non-commercial use only — read the terms before you download them.

| model | used for | license |
| --- | --- | --- |
| RealESRGAN_x4plus / x2plus / RealESRNet_x4plus | Super Resolution | BSD-3-Clause, (c) 2021 Xintao Wang ([Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)) |
| 4x_RealisticRescaler_100000_G | Super Resolution | see `MODEL_LICENSE-RealisticRescaler.txt` in the realesrgan-rs release |
| big-lama | Inpainting | Apache-2.0, [saicinpainting](https://github.com/advimman/lama) |
| RMBG-2.0 | Background Removal | **non-commercial only**, (c) [BRIA](https://bria.ai) — [model card](https://huggingface.co/briaai/RMBG-2.0) |
| LocateAnything-3B | Auto-Crop | **non-commercial research and evaluation only**, NVIDIA — [model card](https://huggingface.co/nvidia/LocateAnything-3B) |
| NAFNet-GoPro / NAFNet-REDS / NAFNet-SIDD, widths 32 and 64 | Enhance | MIT, (c) 2022 megvii-model ([NAFNet](https://github.com/megvii-research/NAFNet)), converted to `.safetensors` |

## Image APIs

The cloud providers are entirely optional and are used only if you put your own
credentials in `config.json`. Each request goes to the provider under their
terms; see [THIRD_PARTY.md](THIRD_PARTY.md) for the endpoints Pixeldeck talks
to.
