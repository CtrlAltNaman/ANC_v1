# Monorepo Restructure and DeClaude Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (inline execution is authorized by the user). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every existing project file while reorganizing firmware, ML, tools, tests, documentation, CI, and Git history into a professional monorepo.

**Architecture:** The ESP-IDF project becomes `firmware/esp32`; ML code becomes a Python package under `ml`; host capture/analysis tools move under `tools/audio`; tests become top-level suites. Existing implementation files are relocated, not rewritten except where imports and path defaults must follow the new package layout.

**Tech Stack:** ESP-IDF 5.5.2, C/CMake, Python 3, PyTorch, standard-library `unittest`, Git filter-repo, GitHub Actions.

---

### Task 1: Capture a preservation inventory and add repository governance

**Files:** Create `CONTRIBUTING.md`, `SECURITY.md`, `.env.example`; modify `.gitignore`.

- [ ] **Step 1:** Create `backups/` and record `git ls-files | Sort-Object` into `backups/tracked-before.txt`.
- [ ] **Step 2:** Document branch naming, Conventional Commits, required verification, and the Claude setting `includeCoAuthoredBy: false` in `CONTRIBUTING.md`.
- [ ] **Step 3:** Document secret, dataset, checkpoint, recording, and vulnerability handling in `SECURITY.md`.
- [ ] **Step 4:** Add only safe, blank environment variable names to `.env.example`.
- [ ] **Step 5:** Ignore `backups/`, firmware build output, ML datasets/checkpoints/logs/reports, Python caches, recordings, and local environment files.

### Task 2: Move the ESP32 project under `firmware/esp32`

**Files:** Move `CMakeLists.txt`, `partitions.csv`, `sdkconfig.defaults`, and `main/` into `firmware/esp32/`; create board documentation and firmware helper scripts under `tools/`.

- [ ] **Step 1:** Use Git-aware renames so all firmware files remain byte-identical.
- [ ] **Step 2:** Document the ESP32-S3 N16R8 target and exact board pinout in `firmware/esp32/boards/esp32-s3/README.md`.
- [ ] **Step 3:** Make build/flash/monitor scripts resolve `$PSScriptRoot/../firmware/esp32`, validate `idf.py`, and run the requested command there.
- [ ] **Step 4:** Run `idf.py build` from `firmware/esp32` with ESP-IDF 5.5.2 exported.

### Task 3: Package the ML pipeline under `ml`

**Files:** Move root ML scripts into `ml/scripts/`, model modules into `ml/models/`, `src/dataset.py` into `ml/data/`, the notebook into `ml/notebooks/`, and requirements into `ml/`.

- [ ] **Step 1:** Add `ml/__init__.py`, `ml/models/__init__.py`, `ml/data/__init__.py`, and `ml/scripts/__init__.py`.
- [ ] **Step 2:** Update imports to `ml.models` and `ml.data`, while adding the repository root to `sys.path` for direct script execution.
- [ ] **Step 3:** Change defaults to `ml/data/dccrn_dataset`, `ml/checkpoints`, `ml/logs`, and `ml/reports`; anchor dataset preparation paths at the repository root.
- [ ] **Step 4:** Document both `python -m ml.scripts.train` and `python ml/scripts/train.py` forms.
- [ ] **Step 5:** Run `python -m compileall -q ml`.

### Task 4: Move host utilities and tests into top-level tools/tests

**Files:** Move `host/` into `tools/audio/`; move `host/tests/test_dashboard.py` into `tests/unit/`; add package markers and `.gitkeep` files for integration/audio/golden suites.

- [ ] **Step 1:** Preserve receiver, dashboard, README, and requirements content during Git-aware renames.
- [ ] **Step 2:** Update imports to `tools.audio.dashboard` and run `python -m unittest discover -s tests/unit -v`.
- [ ] **Step 3:** Update all README and documentation command paths.

### Task 5: Build documentation and CI

**Files:** Move `docs/protocol.md` to `docs/streaming-protocol.md`; create pipeline, benchmark, and decision documents; create `.github/workflows/ci.yml` and `firmware-build.yml`; update README and existing docs.

- [ ] **Step 1:** Replace old firmware, host, and ML paths in documentation.
- [ ] **Step 2:** Document capture → WAV → NLMS → DCCRN flow, benchmarks, ESP32 target rationale, and model rationale.
- [ ] **Step 3:** Configure CI for host tests/Python compilation and firmware CI for ESP-IDF 5.5 from `firmware/esp32`.
- [ ] **Step 4:** Update README with the complete repository tree and commands.

### Task 6: Remove Claude co-author trailers and publish safely

**Files:** Git history only; no tracked file content is intentionally changed.

- [ ] **Step 1:** Create `backups/anc-v1-before-declaude.bundle` with `git bundle create backups/anc-v1-before-declaude.bundle --all`.
- [ ] **Step 2:** Run `python -m git_filter_repo --force --message-callback` with a regex removing complete `Co-Authored-By:` lines containing `Claude` or `anthropic.com`.
- [ ] **Step 3:** Verify `git log --all --format=%B` contains no `Claude`, `anthropic.com`, or `Co-Authored-By` matches.
- [ ] **Step 4:** Compare the before/after inventories after normalizing moved paths, then rerun tests, Python compilation, and firmware build.
- [ ] **Step 5:** Push with `git push --force-with-lease origin main` only after verification.
- [ ] **Step 6:** Query GitHub contributors and commits to confirm Claude is absent and primary authors remain.
