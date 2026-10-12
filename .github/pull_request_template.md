## Firmware submission

- Firmware repository: <!-- https URL -->
- Pinned commit: <!-- full 40-character hash; CI builds exactly this -->

### Checklist

- [ ] This PR adds or updates exactly one file in `registry/`.
- [ ] `make` at the pinned commit builds the `.vsb` named by `artifact` with
      only `gcc-arm-none-eabi`, Python 3 and Node 22.
- [ ] The firmware contains no vendor code or assets and I have the right to
      publish it and its built image.
- [ ] I understand that passing CI does not certify the image as safe to
      flash on physical hardware.
