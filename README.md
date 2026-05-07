# ei-vision-uno-q-foundries

End-to-end **object detection on an Arduino UNO Q**, trained with **Edge Impulse**, packaged as an OCI container, and delivered over-the-air via a **Foundries.io** factory.

> Detects `coffee` and `lamp` from a USB camera at 320×320, float32 FOMO, on the UNO Q's aarch64 CPU.

## Architecture

```
                       ┌─────────────────────────────────────────────────────┐
                       │ GitHub repo  yennster/ei-vision-uno-q-foundries     │
                       │                                                     │
   new training data   │  ┌──────────────────────────────────────────────┐   │
   ┌──────────────┐ ◄──┼──┤ ① ei-data-watch-and-retrain.yml  (hourly)    │   │
   │ Edge Impulse │    │  │   • compares EI sample count vs              │   │
   │ project 25483│ ───┼─►│     .dataset-state.json                      │   │
   │ (FOMO 320x320)│   │  │   • POST /jobs/retrain → poll                │   │
   └──────────────┘    │  │   • POST /jobs/build-ondevice-model          │   │
        ▲              │  │   • download .eim → commit → push vX.Y.Z tag │   │
        │              │  └─────────────────────┬────────────────────────┘   │
   EI_API_KEY secret   │                        │ tag push                   │
                       │                        ▼                            │
                       │  ┌──────────────────────────────────────────────┐   │
                       │  │ ② foundries-deploy.yml  (on v* tag)          │   │
                       │  │   • clone factory containers.git             │   │
                       │  │   • sync containers/ei-vision/ → ei-vision/  │   │
                       │  │   • git push                                 │   │
                       │  └─────────────────────┬────────────────────────┘   │
                       └────────────────────────┼────────────────────────────┘
                                                │ FOUNDRIES_API_TOKEN
                                                ▼
                                ┌────────────────────────────┐
                                │ Foundries factory: jenny   │
                                │ container-main CI builds   │
                                │ arm64 OTA target           │
                                └────────────┬───────────────┘
                                             │ aktualizr-lite poll
                                             ▼
                                ┌────────────────────────────┐
                                │ Arduino UNO Q              │
                                │ pulls + runs ei-vision     │
                                │ edge-impulse-linux-runner  │
                                │ on /dev/video0  →  :4912   │
                                └────────────────────────────┘
```

Two GitHub Actions workflows form the closed loop. ① watches EI for new data and produces a tagged release; ② reacts to that tag and pushes to the factory. From there Foundries' own CI takes over and the device polls for the new target.

## Repo layout

```
.
├── app/                         # Arduino App Lab source-of-truth
│   ├── app.yaml                 # video_object_detection brick + web_ui
│   └── model/
│       └── object-detection.eim # aarch64 ELF, ~25 MB, float32 FOMO
└── containers/
    └── ei-vision/               # mirrored into source.foundries.io/.../containers.git
        ├── Dockerfile           # debian:bookworm + edge-impulse-linux-runner
        ├── docker-compose.yml   # /dev/video0 passthrough, port 4912
        ├── docker-build.conf
        └── README.md
```

## Setup: GitHub secrets

The two automation workflows below need credentials. Set them once on your fork:

| Secret                 | Used by                                  | Where to get it                                                                 |
|------------------------|------------------------------------------|---------------------------------------------------------------------------------|
| `EI_API_KEY`           | `ei-data-watch-and-retrain.yml`          | EI Studio → your project → **Dashboard → Keys** → copy the `ei_…` API key       |
| `FOUNDRIES_API_TOKEN`  | `foundries-deploy.yml`                   | https://app.foundries.io/settings/tokens/ → **New API Token** with `source:readwrite` scope |

Set them via the GitHub UI **or** the `gh` CLI:

**UI:** Repo → *Settings* → *Secrets and variables* → *Actions* → *New repository secret* → paste the name above and the value.

**CLI:**

```bash
gh secret set EI_API_KEY          --repo <owner>/<repo>   # paste EI key when prompted
gh secret set FOUNDRIES_API_TOKEN --repo <owner>/<repo>   # paste Foundries token
gh secret list                    --repo <owner>/<repo>   # verify both are present
```

These secrets are encrypted and only exposed to workflow runs at execution time. Rotate them in Edge Impulse / Foundries first, then re-run `gh secret set` to update GitHub.

## Setup: Register your UNO Q with the factory

Before any OTA target can land on the device, the UNO Q has to enroll itself with the factory using **fioup** (Foundries' container-only OTA client). Once registered, the device polls for new targets and runs whatever the factory has built — including `ei-vision`. Reference: <https://docs.foundries.io/96/getting-started/fioup-registration/index.html>.

Run these on the **UNO Q itself** (over SSH or a serial console; the UNO Q runs Debian on aarch64):

**1. Install fioup from the official apt repo**

```bash
sudo apt update && sudo apt install -y apt-transport-https ca-certificates curl gnupg

curl -L https://fioup.foundries.io/pkg/deb/dists/stable/Release.gpg \
  | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/fioup-stable.gpg

echo 'deb [signed-by=/etc/apt/trusted.gpg.d/fioup-stable.gpg] https://fioup.foundries.io/pkg/deb stable main' \
  | sudo tee /etc/apt/sources.list.d/fioup.list

sudo apt update && sudo apt install -y fioup
```

You also need a recent Docker stack on the device:

```bash
sudo apt install -y docker.io docker-compose-v2
```

**2. Register the device against your factory**

```bash
sudo fioup register --factory jenny --name uno-q-01
```

`fioup` prints a one-time URL and user code. Open it in your browser and authorize the device (link expires in 15 minutes). When it returns `Device is now registered.`, registration is complete and the mTLS material is stored under `/var/sota/`.

**3. Verify connectivity**

```bash
sudo fioup check
```

The device should now appear at <https://app.foundries.io/factories/jenny/devices/>.

**4. Enable the update service** so the device polls for and applies new targets automatically:

```bash
sudo systemctl enable --now fioup
```

**(Optional) Restrict which apps run.** By default, `fioup` runs every app the factory ships. To run only `ei-vision`:

```bash
sudo tee -a /var/sota/sota.toml >/dev/null <<'EOF'

[pacman]
compose_apps = "ei-vision"
EOF
sudo systemctl restart fioup
```

Once the device is registered, every tag pushed by the workflows above flows automatically: GitHub Actions → factory `containers.git` → factory CI → OTA target → `fioup` on the device → running container.

## Pipeline

### 1. Build the Edge Impulse model

The model is built from project **25483 / "Tutorial: object detection"** with the **Arduino UNO Q** deployment target, `float32` model variant.

```bash
curl -X POST -H "x-api-key: $EI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"engine":"tflite","modelType":"float32"}' \
  "https://studio.edgeimpulse.com/v1/api/25483/jobs/build-ondevice-model?type=arduino-uno-q"

# poll /jobs/{id}/status, then:
curl -L -H "x-api-key: $EI_API_KEY" \
  -o app/model/object-detection.eim \
  "https://studio.edgeimpulse.com/v1/api/25483/deployment/download?type=arduino-uno-q&modelType=float32"
```

### 1b. Auto-retrain on new data

[`.github/workflows/ei-data-watch-and-retrain.yml`](.github/workflows/ei-data-watch-and-retrain.yml) runs hourly. It:

1. Reads the current training+testing sample count from EI.
2. Compares it to `lastTrainedSampleCount` in [`.dataset-state.json`](.dataset-state.json).
3. If different (or `force=true` via manual dispatch): retrains the impulse, builds a new `arduino-uno-q` `.eim`, updates both copies of the model in this repo, bumps the patch version, and pushes a new `vX.Y.Z` tag.

The new tag fires `foundries-deploy.yml`, completing the pipeline EI → GitHub → Foundries → device.

Uses the `EI_API_KEY` secret (see [Setup: GitHub secrets](#setup-github-secrets)).

### 2. Ship to the Foundries factory

**Automated (recommended):** [`.github/workflows/foundries-deploy.yml`](.github/workflows/foundries-deploy.yml) syncs `containers/ei-vision/` into the factory's `containers.git` whenever a `v*` tag is pushed. It can also be run manually via *Actions → Push to Foundries containers.git → Run workflow*.

Uses the `FOUNDRIES_API_TOKEN` secret (see [Setup: GitHub secrets](#setup-github-secrets)).

**Manual fallback:**

```bash
git clone https://source.foundries.io/factories/jenny/containers.git
cp -r containers/ei-vision /path/to/containers.git/
cd /path/to/containers.git
git add ei-vision && git commit -m "ei-vision: add EI object detection container"
git push  # triggers container-main CI build → OTA target
```

### 3. Device pulls the new target

Any UNO Q registered to the `jenny` factory with the `main` tag will, on its next aktualizr-lite poll, pull the new arm64 image and start the `ei-vision` Compose service. Inference is exposed on `:4912`.

## Container behavior

The container runs Edge Impulse's official Linux runner against the bundled `.eim`:

```
edge-impulse-linux-runner --model-file /app/object-detection.eim --enable-camera --silent
```

The runner serves a live preview + classification UI on port **4912**. With `/dev/video0` mapped through `docker-compose.yml`, any UVC USB camera attached to the UNO Q is used.

## App Lab alternative

`app/app.yaml` describes the same model wired through the Arduino App Lab `arduino:video_object_detection` brick. App Lab expects the model at:

```
/home/arduino/.arduino-bricks/ei-models/object-detection.eim
```

This path is the canonical location for App Lab brick consumption when running outside the Compose-app pipeline.

## Model

| Property        | Value                                            |
|-----------------|--------------------------------------------------|
| Source          | Edge Impulse project 25483                       |
| Architecture    | aarch64 ELF (Linux 3.7+)                         |
| Input           | 320×320 RGB, `fit-short` resize                  |
| Type            | Object detection (FOMO)                          |
| Classes         | `coffee`, `lamp`                                 |
| Quantization    | float32                                          |
| Size            | ~25 MB                                           |

## Refresh the model

To rebuild from a newer Edge Impulse training run:

```bash
EI_API_KEY=<your key> ./scripts/refresh-model.sh   # see scripts/
```

(Or rerun step 1 above and commit the new `.eim`.)

## Links

- Edge Impulse project: https://studio.edgeimpulse.com/studio/25483
- Foundries factory: https://app.foundries.io/factories/jenny/
- UNO Q getting started: https://docs.foundries.io/96/getting-started/arduino-uno-q/index.html
- Edge Impulse on UNO Q: https://docs.edgeimpulse.com/hardware/boards/arduino-uno-q

## License

MIT
