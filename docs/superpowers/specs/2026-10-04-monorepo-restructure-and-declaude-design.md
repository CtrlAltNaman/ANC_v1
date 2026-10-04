# Monorepo Restructure and DeClaude Design

## Goal

Reorganize the ANC_v1 repository into a professional firmware/ML/tools/test
monorepo while preserving every existing tracked file and removing only Claude
co-author trailers from Git history.

## Preservation rules

- No tracked source, notebook, configuration, documentation, or test file is
  deleted.
- Existing files are moved with Git-aware renames where possible.
- New compatibility documentation and updated commands explain every moved
  path.
- The previously removed untracked I²C scanner remains removed because that was
  explicitly requested earlier.
- Primary commit authors and commit content remain unchanged during the history
  rewrite; only lines matching the Claude `Co-Authored-By` trailer are removed.

## Target structure

```text
.
├── README.md
├── CONTRIBUTING.md
├── SECURITY.md
├── .env.example
├── .gitignore
├── .github/workflows/
│   ├── ci.yml
│   └── firmware-build.yml
├── docs/
│   ├── architecture.md
│   ├── hardware.md
│   ├── audio-pipeline.md
│   ├── streaming-protocol.md
│   ├── benchmarking.md
│   └── decisions/
│       ├── 001-esp32-target.md
│       └── 002-model-architecture.md
├── firmware/esp32/
│   ├── CMakeLists.txt
│   ├── partitions.csv
│   ├── sdkconfig.defaults
│   ├── main/
│   │   ├── include/
│   │   └── src/
│   └── boards/esp32-s3/README.md
├── ml/
│   ├── README.md
│   ├── requirements.txt
│   ├── requirements-inference.txt
│   ├── configs/
│   ├── data/
│   ├── models/
│   ├── notebooks/
│   ├── scripts/
│   └── reports/
├── tools/
│   └── audio/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── audio/
│   └── golden/
└── backups/                 # local-only, ignored history bundles
```

## History cleanup

Before rewriting, create a local recovery bundle. Use `git-filter-repo` to
remove only Claude co-author trailers from all reachable commit messages. Verify
the rewritten history contains no `Claude`, `anthropic.com`, or
`Co-Authored-By` matches, then force-push `main` with lease protection. Add
contributor guidance for disabling future Claude attribution.

## Verification

- Before/after tracked-file inventories have identical file-content identities,
  accounting for intentional path moves and newly added project documentation.
- Host tests and Python compilation pass.
- The ESP-IDF build passes from `firmware/esp32` when the toolchain is present.
- No merge markers or Claude trailers remain.
- The rewritten `origin/main` matches the verified local `main` commit.
