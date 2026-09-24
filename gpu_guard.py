"""Serialized access to the shared GPU for Pixeldeck's local GPU tools.

Every GPU binary Pixeldeck runs -- realesrgan, lama-inpaint, rmbg,
locate-anything -- is spawned by this server, so one process-wide lock is all
that is needed to keep two of them from competing for the same VRAM. It is a
plain `threading.Lock`: each run happens in a worker thread (`run_in_executor`)
and holds the lock for the whole subprocess.
"""

import threading

gpu_lock = threading.Lock()
