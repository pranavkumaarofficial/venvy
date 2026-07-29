# Demo assets

`demo.gif` in the repo root README is generated from `demo.tape` with
[vhs](https://github.com/charmbracelet/vhs). It is fully reproducible: the demo
environment is built from package **metadata only** (`demo/build_demo_env.py`), so
nothing is ever installed and no third-party code runs.

## Render the GIF

Needs Docker running. One command, no local vhs/ttyd install:

```bash
docker build -t venvy-vhs -f assets/demo/Dockerfile .
docker run --rm -v "$PWD:/vhs" venvy-vhs assets/demo.tape
```

This writes `assets/demo.gif`. The first run downloads the ~30MB advisory database
inside the container (hidden in the recording); the visible part is only the scan.

## What the demo shows

`venvy audit` against a small environment containing one known-malicious typosquat
(`requestts`), three genuinely vulnerable versions, and one clean package — so the
scan is dramatic without being all-red. Exit code 21 (malicious found).

To preview the exact output locally without rendering:

```bash
python assets/demo/build_demo_env.py demo/.venv
venvy audit --env demo/.venv
```
