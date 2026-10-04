# ML data

This directory contains local dataset material and manifests. Large or
sensitive audio is intentionally ignored by Git.

Expected flow:

```text
data/speech/       clean speech source files
data/noise/        defence-noise source files
data/mixed/        generated noisy clips and metadata.csv
data/dccrn_dataset train/validation/test pairs consumed by DCCRN
```

Use `python -m ml.scripts.dataset_mixer` to create mixed clips and
`python -m ml.scripts.prepare_dccrn_dataset` to create reproducible splits.
