# anomaly-watcher (Foundries Compose app)

Sidecar app that runs a visual-anomaly `.eim` against the camera and, on anomalies, uploads frames to the Edge Impulse training/testing dataset of the *target* project (typically the object-detection project, not the anomaly project).

## Files

| File | Purpose |
|------|---------|
| [`Dockerfile`](Dockerfile) | `debian:bookworm-slim` + `python3-opencv` + `pip install edge_impulse_linux`. Bakes in `anomaly.eim`, `anomaly-watcher.py`, and `capture-and-upload.sh`. |
| [`docker-compose.yml`](docker-compose.yml) | `__FACTORY__` / `__ANOMALY_APP_NAME__` placeholders substituted at deploy time. Maps `/dev/video0` and reads `EI_API_KEY` etc. from the device's environment. |
| [`docker-build.conf`](docker-build.conf) | Foundries CI hint (`ARCHITECTURES="linux/arm64"`). |
| `anomaly.eim` | The anomaly model. Refreshed by [`ei-anomaly-watch-and-retrain.yml`](../../.github/workflows/ei-anomaly-watch-and-retrain.yml) whenever the EI anomaly project gets new data. |
| `anomaly-watcher.py` | Long-running watcher; same code as [`scripts/anomaly-watcher.py`](../../scripts/anomaly-watcher.py). |
| `capture-and-upload.sh` | Same code as [`scripts/capture-and-upload.sh`](../../scripts/capture-and-upload.sh) (used in `IMAGE_FILE` mode). |

## Camera conflict with `ei-vision`

Both apps want `/dev/video0`. Pick one of:

- Run only one at a time via fioup's `pacman.compose_apps` setting (see [the main README](../../README.md#setup-register-your-uno-q-with-the-factory)).
- Attach a second UVC camera and override `ANOMALY_DEVICE=/dev/video1` in the device's compose env.

## Required device env

Set on the device (e.g. via `fioconfig` config-set, or `/var/sota/sota.toml [pacman.compose_apps_env]`):

| Var | Required | Purpose |
|---|---|---|
| `EI_API_KEY` | yes | EI key for the **target** project (the one receiving uploaded samples) |
| `ANOMALY_THRESHOLD` | no | default `5.0` |
| `ANOMALY_COOLDOWN` | no | default `10` (s) |
| `ANOMALY_CATEGORY` | no | `training` (default) or `testing` |
| `ANOMALY_LABEL` | no | default `anomaly` |
| `ANOMALY_DEVICE` | no | default `/dev/video0` |
