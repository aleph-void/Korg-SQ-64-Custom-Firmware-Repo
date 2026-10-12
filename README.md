# SQ-64 custom firmware registry

A public registry of community firmware for the Korg SQ-64 hardware
sequencer. Every merged entry is **built from source, validated and
published automatically**:

1. A contributor opens a pull request adding one JSON file under
   [`registry/`](registry/) that points at their public firmware repository,
   pinned to an exact commit.
2. CI clones that commit, builds it with `make`, runs the
   [SQ-64 conformance spec](https://github.com/aleph-void/Korg-SQ-64-Custom-Firmware-Spec)'s
   `image` profile, executes the image headlessly in the
   [SQ-64 emulator](https://github.com/aleph-void/Korg-SQ-64-Emulator) with
   its critical damage detectors armed, and validates any shipped emulator
   UI scripts.
3. When the pull request is merged, the same pipeline publishes the built
   `.vsb`, its validation reports and its UI scripts to GitHub Pages, and the
   [browser emulator](https://sq64.alephvoid.com) lists it under **Firmware
   repository** for one-click loading.

**Published manifest:**
`https://aleph-void.github.io/Korg-SQ-64-Custom-Firmware-Repo/index.json`

> **Hardware warning.** Passing these checks means the image builds, has a
> well-formed package, and runs in the emulator without tripping hazard
> detectors. It is **not** a certification that the firmware is safe on a
> physical SQ-64. Flashing real hardware is at your own risk.

## Submitting your firmware

Open a pull request that adds a single file `registry/<id>.json`, where
`<id>` is a short lowercase slug for your firmware (`[a-z0-9-]`, at most 40
characters):

```json
{
  "name": "Euclidean",
  "repo": "https://github.com/you/your-sq64-firmware",
  "ref": "<full 40-character commit hash>",
  "artifact": "build/your-firmware.vsb",
  "description": "One or two sentences about what your firmware does.",
  "homepage": "https://optional-project-page.example"
}
```

| Field | Meaning |
| --- | --- |
| `name` | Display name shown in the emulator (≤ 80 characters). |
| `repo` | Public `https` git URL of your firmware source. |
| `ref` | The exact commit to build — a full 40-character hash, so the published image can never change after review. |
| `artifact` | Repository-relative path of the `.vsb` your `make` produces (≤ 4 MiB). |
| `description` | Shown in the emulator's firmware list (≤ 400 characters). |
| `homepage` | Optional project page (`https`). |
| `order` | Optional integer list position (lower sorts first; default 1000). |

Your repository must build the artifact with a plain `make` using the GNU
Arm toolchain (`gcc-arm-none-eabi`), Python 3 and Node 22 — the same
contract as the
[Euclidean reference firmware](https://github.com/aleph-void/Korg-SQ-64-Euclidean-Firmware).
To update a published firmware, open a pull request that bumps your entry's
`ref`.

### What CI checks

- The entry document is well formed (fields above).
- `make` at the pinned commit produces the named `.vsb` (≤ 4 MiB).
- The spec's `image` profile passes: package geometry, header fields,
  checksums, reset vectors.
- A 2,000,000-instruction headless run in the emulator completes without a
  fault and without tripping any critical damage detector (internal flash
  writes, system configuration writes, forbidden SPI commands, dangerous DMA
  destinations).
- Every shipped UI script (see below) validates.

Run it yourself before submitting: see
[Local pipeline](#local-pipeline).

### Shipping emulator UI scripts

If your repository has a `scripts/` directory, every `scripts/*.json` file
is validated as an [SQ-64 emulator UI script](https://github.com/aleph-void/Korg-SQ-64-Emulator/blob/main/web/README.md#ui-scripts)
(`format: sq64-ui-script`, version 1, ≤ 1 MiB, at most 16 scripts) and
published with your firmware. The emulator imports them into its UI scripts
library when a user loads your firmware from the list — use them to demo
your firmware's features or drive its update flow.

## Published site layout

```
index.json                      — the registry manifest (format: sq64-firmware-registry)
firmware/<id>/<name>.vsb        — the built firmware image
firmware/<id>/scripts/<x>.json  — validated UI scripts, if any
reports/<id>/validation.json    — conformance image-profile report
reports/<id>/smoke.json         — headless emulator execution report
```

Each manifest entry records the source `repo` and `ref`, the artifact path,
its SHA-256 and size, the spec version it was validated against, report
paths, and its UI scripts (name, path, SHA-256). Consumers should verify the
SHA-256 of a downloaded image against the manifest.

## Local pipeline

```sh
git clone https://github.com/aleph-void/Korg-SQ-64-Custom-Firmware-Spec spec
git clone https://github.com/aleph-void/Korg-SQ-64-Emulator emulator
python -m venv .venv && .venv/bin/pip install ./spec ./emulator
.venv/bin/python tools/build_registry.py --out site --spec spec --emulator emulator
```

The exact spec and emulator commits CI uses are pinned in
[`.github/workflows/build.yml`](.github/workflows/build.yml).

## License

The registry tooling is MIT licensed (see [LICENSE](LICENSE)). Each listed
firmware keeps its own license; the built images are redistributed here
under the submitting repository's terms, which the submitter is responsible
for permitting.
