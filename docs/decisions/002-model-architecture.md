# Decision 002: DCCRN plus adaptive filtering

## Decision

Use the two-microphone NLMS filter as a lightweight baseline and DCCRN as the
learned enhancement path.

## Rationale

NLMS is explainable and inexpensive when the reference microphone is correlated
with noise. DCCRN adds complex-domain spectral-temporal modeling for conditions
where a linear adaptive filter cannot represent the noise or speech mixture.

## Consequences

The pipeline must preserve both microphone channels through capture and host
recording. Model metrics must be reported separately from the adaptive-filter
baseline so improvements are measurable and reproducible.
