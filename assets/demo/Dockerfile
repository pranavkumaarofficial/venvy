# Toolchain image for rendering assets/demo.gif: the official vhs recorder
# plus Python and venvy, so the whole GIF renders from one command with no
# local vhs/ttyd install. See assets/README.md.
FROM ghcr.io/charmbracelet/vhs:latest

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
 && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir --break-system-packages venvy

# Bake the demo env AND the advisory database into the image, so the recording
# needs no setup and no network — the tape just runs the scan.
COPY assets/demo/build_demo_env.py /seed/build_demo_env.py
RUN python3 /seed/build_demo_env.py /demo/.venv \
 && (venvy audit --env /demo/.venv >/dev/null 2>&1 || true)

ENTRYPOINT ["vhs"]
