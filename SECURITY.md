# Security policy

## Scope

This project handles defence-noise recordings and embedded-device networking.
Please treat raw recordings, datasets, model checkpoints, Wi-Fi credentials,
serial captures, and evaluation reports as potentially sensitive.

## Do not commit

- Real Wi-Fi passwords or device secrets
- Raw operational recordings or identifying speech
- Proprietary defence-noise datasets
- Model checkpoints or generated reports containing sensitive samples
- Private keys, access tokens, or cloud credentials

Use `.env.example` as the safe configuration template and keep actual values in
local `.env` files or an approved secret store.

## Reporting

For a suspected security issue, do not open a public issue with sensitive
details. Contact the repository maintainers through the private channel used by
the project team and include reproduction steps, affected commit, and impact.
