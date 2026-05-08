# SHOW. TRAIN. SHIP. REPEAT.

**Powered by Arduino UNO Q + Edge Impulse + Foundries.io**


## What just happened on the table

You picked something up at another booth — a squishy, a sticker, a branded mug, whatever. You set it in front of this $40 Arduino UNO Q. The model didn't know what it was at 9 a.m. By the time you finish your coffee, the model knows. So do all the other boards in this booth.

That's a full active-learning loop running, in public, on a tech-conference floor.

## The loop in four moves

**① SHOW** — A USB camera + OpenCV motion detector spots that something new just landed in the frame. The image is uploaded to an Edge Impulse project's training (or testing) dataset.

**② TRAIN** — A GitHub Actions workflow polls the project hourly. New samples → kick off `POST /jobs/retrain` → poll the job → build a fresh `.eim` for `arduino-uno-q` → commit + tag a new release. *Roughly 10 minutes from upload to release tag.*

**③ SHIP** — A second workflow reacts to the new tag, syncs the updated container into the Foundries.io factory's `containers.git`, and the factory's CI builds an arm64 OTA target.

**④ REPEAT** — Every UNO Q registered to the factory polls aktualizr-lite, pulls the new target, restarts the inference container, and now recognizes the thing you just showed it. **Devices are never touched. No re-flashing, no SSH, no scripts.**

## Why it lands

- **A $40 board, not a $1,000 dev kit.** The UNO Q runs Debian on aarch64 — full Linux, full Docker, room for surprises.
- **One workflow scales to any fleet.** Updating one board and updating ten thousand is the same operation.
- **Active learning isn't theory.** The booth's model gets *measurably* better between coffee and lunch. We're keeping a printout — come back at 4 p.m. and look at the version timeline.


## The stack

| Layer | What's running |
|---|---|
| Device | Arduino UNO Q · `edge-impulse-linux-runner` · `motion-watcher.py` (OpenCV) |
| ML | Edge Impulse — training, hosted inference build, ingestion API |
| Fleet | Foundries.io — `containers.git`, container CI, OTA targets, aktualizr-lite |
| Glue | GitHub Actions — hourly EI watcher, tag-driven Foundries deploy |

Every box above is open-source or off-the-shelf. The only thing custom is `~150 lines` of Bash + Python.

## Take it home

```
github.com/yennster/ei-vision-uno-q-foundries
```

Fork it, set two GitHub variables (`EI_PROJECT_ID`, `FOUNDRIES_FACTORY`), set two secrets (API keys), register a UNO Q with `fioup`, and you've got the same loop running in your factory by lunch.

> Want to learn more or talk shop? Find us at the booth. Or, you know — show it something.

