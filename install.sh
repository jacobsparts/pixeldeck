#!/usr/bin/env bash
#
# Pixeldeck installer.
#
# Creates a virtualenv, downloads the engine binaries and the model weights
# they need, and writes a starter config.json. Everything lands under bin/ and
# .venv/ next to this script; nothing is installed system-wide and nothing is
# fetched from anywhere but the public release pages of the engines themselves.
#
# The weights are downloaded, never mirrored: several of them are licensed for
# non-commercial use only and are not ours to redistribute. See
# THIRD_PARTY_LICENSES.md.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
BIN_DIR=$SCRIPT_DIR/bin
MODEL_DIR=$BIN_DIR/models
VENV_DIR=$SCRIPT_DIR/.venv
CONFIG_FILE=$SCRIPT_DIR/config.json
EXAMPLE_FILE=$SCRIPT_DIR/config.example.json

# The release each engine is installed from.
REALESRGAN_VERSION=v0.1.0
LAMA_VERSION=v0.2.4
RMBG_VERSION=v0.1.0
LOCATE_VERSION=v0.1.0
ENHANCE_VERSION=v0.1.0

CPU_ONLY=0
WITH_RMBG=1
WITH_LOCATE=1
WITH_SERVICE=0
FORCE=0

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Install Pixeldeck into this directory.

  ./install.sh [options]

  --cpu-only     download the CPU-only engine builds instead of the CUDA ones
                 (smaller, and slower on a machine with a GPU)
  --no-rmbg      skip the gated RMBG-2.0 checkpoint (background removal)
  --no-locate    skip the LocateAnything-3B container (Auto-Crop); it is a
                 7.7 GB download that is then quantized, so it needs ~12 GB free
  --service      also install and enable the systemd user unit
  --force        re-download everything, even what is already there
  -h, --help     this text

Re-running is cheap: a file that is already present is left alone unless
--force is given.
EOF
}

while (( $# )); do
    case $1 in
        --cpu-only)  CPU_ONLY=1 ;;
        --no-rmbg)   WITH_RMBG=0 ;;
        --no-locate) WITH_LOCATE=0 ;;
        --service)   WITH_SERVICE=1 ;;
        --force)     FORCE=1 ;;
        -h|--help)   usage; exit 0 ;;
        *)           die "unknown option: $1 (try --help)" ;;
    esac
    shift
done

# ---------------------------------------------------------------- utilities

have() { command -v "$1" >/dev/null 2>&1; }

# fetch <url> <destination>
fetch() {
    local url=$1 dest=$2
    if [[ -s $dest && $FORCE -eq 0 ]]; then
        say "$(basename "$dest") is already there"
        return 0
    fi
    mkdir -p "$(dirname "$dest")"
    say "downloading $(basename "$dest")"
    curl -fL --retry 3 --retry-delay 2 -o "$dest.part" "$url" \
        || { rm -f "$dest.part"; die "could not download $url"; }
    mv "$dest.part" "$dest"
}

# github <repo> <tag> <asset>
github() {
    printf 'https://github.com/jacobsparts/%s/releases/download/%s/%s' "$1" "$2" "$3"
}

# engine <asset-name-in-bin> <url>
engine() {
    local name=$1 url=$2
    fetch "$url" "$BIN_DIR/$name"
    chmod +x "$BIN_DIR/$name"
}

# run_abortable <what> <command...>
#
# Run a long download that the user is allowed to give up on. Ctrl-C kills the
# command but not the install: we report it and carry on with the rest.
run_abortable() {
    local what=$1 rc=0
    shift
    trap 'rc=130' INT
    "$@" || rc=$?
    trap - INT
    if (( rc != 0 )); then
        warn "$what did not finish (exit $rc) -- continuing without it"
    fi
    return $rc
}

# ------------------------------------------------------------------- checks

say "checking prerequisites"
have python3 || die "python3 is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "python3 3.10 or newer is required (found $(python3 -V 2>&1))"
have curl || die "curl is required"
[[ -f $EXAMPLE_FILE ]] || die "config.example.json is missing; is this the whole checkout?"

# ---------------------------------------------------------------- virtualenv

if [[ ! -d $VENV_DIR ]]; then
    say "creating .venv"
    python3 -m venv "$VENV_DIR" \
        || die "python3 -m venv failed; on Debian or Ubuntu, install python3-venv"
fi
VENV_PY=$VENV_DIR/bin/python3
say "installing Python packages"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"

# ------------------------------------------------------------------ engines

say "downloading the image engines"
if (( CPU_ONLY )); then
    suffix=-cpu-only
else
    suffix=
fi

# The CUDA builds probe the driver at start-up and fall back to the CPU
# backend, so they are what we install unless --cpu-only was asked for.
engine realesrgan-linux-x86_64 \
    "$(github realesrgan-rs "$REALESRGAN_VERSION" "realesrgan-linux-x86_64$suffix")"
engine lama-inpaint \
    "$(github lama-inpaint-rs "$LAMA_VERSION" "lama-inpaint-linux-x86_64$suffix")"
engine rmbg-linux-x86_64 \
    "$(github rmbg-rs "$RMBG_VERSION" "rmbg-linux-x86_64$suffix")"
engine locate-anything \
    "$(github locate-anything-rs "$LOCATE_VERSION" "locate-anything-linux-x86_64$suffix")"

for tool in adaptive-enhance iagcwd white-balance; do
    engine "$tool" "$(github adaptive-enhance "$ENHANCE_VERSION" "$tool")"
done

# ------------------------------------------------------------------- models

say "downloading the model weights"

# Real-ESRGAN: super resolution. These are release assets of realesrgan-rs.
for weights in RealESRGAN_x4plus.safetensors RealESRGAN_x2plus.safetensors \
               RealESRNet_x4plus.safetensors 4x_RealisticRescaler_100000_G.safetensors; do
    fetch "$(github realesrgan-rs "$REALESRGAN_VERSION" "$weights")" "$MODEL_DIR/$weights"
done

# LaMa: inpainting. The repacked checkpoint is a release asset of
# lama-inpaint-rs.
fetch "$(github lama-inpaint-rs "$LAMA_VERSION" big-lama.safetensors)" \
      "$MODEL_DIR/big-lama.safetensors"

# ------------------------------------------------------- gated / built models
#
# Two of the models cannot be release assets: RMBG-2.0 is behind a license
# gate on Hugging Face, and the LocateAnything container is over GitHub's
# per-file limit and has to be built from NVIDIA's checkpoint. Each engine
# ships the script that does it, and each is optional.

rmbg_model=$MODEL_DIR/RMBG-2.0.safetensors
if (( WITH_RMBG )); then
    if [[ -s $rmbg_model && $FORCE -eq 0 ]]; then
        say "RMBG-2.0.safetensors is already there"
    else
        say "fetching the RMBG-2.0 checkpoint (gated: you need a Hugging Face token)"
        rmbg_script=$BIN_DIR/get-model.py
        fetch "$(printf 'https://raw.githubusercontent.com/jacobsparts/rmbg-rs/%s/get-model.py' "$RMBG_VERSION")" "$rmbg_script"
        rmbg_args=("$rmbg_model")
        # Ask for the token here and hand it straight to the downloader: it is
        # used once, never written to disk and never kept in this shell.
        if [[ -t 0 ]]; then
            printf 'Hugging Face access token for the gated RMBG-2.0 checkpoint (input hidden, not saved): '
            read -rs hf_token
            printf '\n'
            if [[ -n $hf_token ]]; then
                rmbg_args+=(--token "$hf_token")
            fi
            unset hf_token
        fi
        run_abortable "the RMBG-2.0 download" "$VENV_PY" "$rmbg_script" "${rmbg_args[@]}" \
            || warn "background removal will be unavailable until $rmbg_model exists"
        unset rmbg_args
    fi
else
    say "skipping RMBG-2.0 (--no-rmbg)"
fi

locate_model=$MODEL_DIR/locate-anything-allq8_0.laqt
if (( WITH_LOCATE )); then
    if [[ -s $locate_model && $FORCE -eq 0 ]]; then
        say "locate-anything-allq8_0.laqt is already there"
    else
        say "building the LocateAnything container (about 7.7 GB down, 4.2 GB out)"
        locate_script=$BIN_DIR/get-model.sh
        fetch "$(printf 'https://raw.githubusercontent.com/jacobsparts/locate-anything-rs/%s/get-model.sh' "$LOCATE_VERSION")" "$locate_script"
        # The script fetches its own converter from the same tag, needs numpy
        # (hence the venv on PATH), and keeps its 7.7 GB intermediate in
        # bin/model-source, which we delete once the container is built.
        if run_abortable "the LocateAnything container build" \
                env PATH="$VENV_DIR/bin:$PATH" LA_REF="$LOCATE_VERSION" \
                    bash "$locate_script" "$locate_model"; then
            rm -rf "$BIN_DIR/model-source"
        else
            warn "Auto-Crop will be unavailable until $locate_model exists"
            warn "the partial download is in $BIN_DIR/model-source and can be resumed by re-running"
        fi
    fi
else
    say "skipping LocateAnything (--no-locate)"
fi

# ------------------------------------------------------------------- config

if [[ -f $CONFIG_FILE ]]; then
    say "config.json already exists; leaving it alone"
else
    cp "$EXAMPLE_FILE" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    say "wrote config.json from config.example.json"
    say "add your API keys there, or from the Config button in the web UI"
fi

# ------------------------------------------------------------------ service

if (( WITH_SERVICE )); then
    unit_dir=$HOME/.config/systemd/user
    mkdir -p "$unit_dir"
    sed "s|@PIXELDECK_DIR@|$SCRIPT_DIR|g" "$SCRIPT_DIR/pixeldeck.service" > "$unit_dir/pixeldeck.service"
    say "installed $unit_dir/pixeldeck.service"
    if have systemctl; then
        systemctl --user daemon-reload || true
        say "start it with: systemctl --user enable --now pixeldeck.service"
    fi
fi

# --------------------------------------------------------------------- done

cat <<EOF

$(say "Pixeldeck is installed")

  start it:   $VENV_PY $SCRIPT_DIR/server.py
  then open:  http://127.0.0.1:8081/

  ./server.py --help   to bind somewhere else or change the port
EOF
