# Benchmarking

## Quality metrics

Evaluate enhancement on a fixed, versioned manifest and report:

- input and output SNR or SI-SNR;
- STOI for intelligibility;
- PESQ when the evaluation dependency and license permit it;
- failure cases for stationary, non-stationary, and impulsive noise.

Run evaluation with:

```text
python -m ml.scripts.evaluate \
  --checkpoint ml/checkpoints/best.pt \
  --data_root ml/data/dccrn_dataset \
  --output_dir ml/reports
```

Do not compare reports made from different manifests or sample-rate settings.
Record the commit, model checkpoint, dataset manifest, device, and command
alongside every result.

## Embedded performance

Measure on the target hardware after model export or quantization:

- end-to-end algorithmic latency;
- processing real-time factor;
- peak RAM and flash usage;
- sustained power draw and thermal behavior;
- packet loss and recovery under USB load.

The practical acceptance criterion is intelligible speech at a latency suitable
for communication, not a single offline metric in isolation.
