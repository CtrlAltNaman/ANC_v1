# Speech-enhancement ML pipeline

The ML package trains and evaluates the DCCRN speech enhancer used after the
ESP32 capture and NLMS stages.

## Install

```powershell
python -m pip install -r ml/requirements.txt
```

For deployment-only inference:

```powershell
python -m pip install -r ml/requirements-inference.txt
```

## Commands

```text
python -m ml.scripts.train --data_root ml/data/dccrn_dataset --epochs 30
python -m ml.scripts.evaluate --checkpoint ml/checkpoints/best.pt --data_root ml/data/dccrn_dataset
python -m ml.scripts.infer --checkpoint best.pt --input noisy.wav --output enhanced.wav
```

The scripts also work when invoked by path, for example
`python ml/scripts/infer.py ...`. Model implementations live in `ml/models/`;
dataset loading lives in `ml/data/`; generated checkpoints, logs, and reports
are ignored.
