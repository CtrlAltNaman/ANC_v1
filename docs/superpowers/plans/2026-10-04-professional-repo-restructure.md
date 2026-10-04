# Professional Repository Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the DhvaniKavach/ANC_v1 repository into a professional ESP-IDF plus host-tools layout without changing the repository name or runtime behavior.

**Architecture:** Keep the ESP-IDF project rooted at the repository root, move firmware implementation files into `main/src/`, expose shared firmware headers through `main/include/`, and retain the existing host script entry points. Add documentation, host regression coverage, and Windows command wrappers around the existing tools.

**Tech Stack:** ESP-IDF 5.5.2, ESP32-S3, C, CMake, Python 3, standard-library `unittest`, PowerShell.

---

### Task 1: Remove the temporary diagnostic firmware and restore the capture target

**Files:**
- Delete: `main/i2c_scan.c`
- Modify: `main/CMakeLists.txt`

- [ ] **Step 1: Delete the unneeded I²C scanner**

Remove only `main/i2c_scan.c`. Do not remove or reset other working-tree changes.

- [ ] **Step 2: Restore the ESP-IDF source registration**

Set `main/CMakeLists.txt` to:

```cmake
idf_component_register(
    SRCS
        "src/main.c"
        "src/clip.c"
        "src/web.c"
    PRIV_REQUIRES
        driver
        esp_wifi
        esp_http_server
        esp_netif
        esp_event
        nvs_flash
        esp_timer
    INCLUDE_DIRS
        "include"
)
```

- [ ] **Step 3: Verify the scanner is no longer referenced**

Run:

```powershell
rg -n "i2c_scan|I2C_SCAN|i2c_master" main CMakeLists.txt
```

Expected: no output and exit code 1 from `rg`.

### Task 2: Separate firmware source and public headers

**Files:**
- Create: `main/src/main.c`
- Create: `main/src/clip.c`
- Create: `main/src/web.c`
- Create: `main/include/clip.h`
- Create: `main/include/web.h`
- Delete: `main/main.c`
- Delete: `main/clip.c`
- Delete: `main/clip.h`
- Delete: `main/web.c`
- Delete: `main/web.h`

- [ ] **Step 1: Move the implementation files into `main/src/`**

Move the three existing C implementation files byte-for-byte into `main/src/`.

- [ ] **Step 2: Move the public headers into `main/include/`**

Move `clip.h` and `web.h` byte-for-byte into `main/include/`.

- [ ] **Step 3: Confirm include resolution is explicit**

Keep source includes as `#include "clip.h"` and `#include "web.h"`; the updated
`INCLUDE_DIRS "include"` entry supplies those headers to every source file.

- [ ] **Step 4: Verify the source inventory**

Run:

```powershell
rg --files main | Sort-Object
```

Expected: `main/CMakeLists.txt`, the two headers under `main/include/`, and the
three C files under `main/src/`, with no scanner or old root-level source files.

### Task 3: Add host-tool metadata and regression coverage

**Files:**
- Create: `host/requirements.txt`
- Create: `host/README.md`
- Create: `host/tests/test_dashboard.py`

- [ ] **Step 1: Declare the host runtime dependency**

Create `host/requirements.txt` containing:

```text
pyserial>=3.5
```

- [ ] **Step 2: Add host-tool usage documentation**

Document installation, receiver usage, dashboard usage, ANC0 channel meaning,
and the fact that the dashboard itself uses only the Python standard library.

- [ ] **Step 3: Write regression tests before changing host behavior**

Create `host/tests/test_dashboard.py` with `unittest` tests covering:

```python
from array import array
import unittest

from host.dashboard import metrics, nlms


class DashboardTests(unittest.TestCase):
    def test_metrics_reports_peak_and_sample_rate_features(self):
        signal = array("h", [0, 1000, -1000, 2000, -2000, 0] * 100)
        result = metrics(signal, 16000)
        self.assertEqual(result["peak"], 2000)
        self.assertGreater(result["rms"], 0)
        self.assertEqual(result["zcr"], 8000.0)

    def test_nlms_returns_same_length_signal(self):
        desired = array("h", [1000, 1000, 1000, 1000] * 20)
        reference = array("h", [500, 500, 500, 500] * 20)
        cleaned = nlms(desired, reference, taps=8, mu=0.2)
        self.assertEqual(len(cleaned), len(desired))
        self.assertTrue(all(-32768 <= sample <= 32767 for sample in cleaned))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the host tests**

Run:

```powershell
python -m unittest discover -s host/tests -v
```

Expected: both tests pass.

### Task 4: Add project documentation and command wrappers

**Files:**
- Modify: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/hardware.md`
- Create: `docs/protocol.md`
- Create: `docs/development.md`
- Create: `scripts/build.ps1`
- Create: `scripts/flash.ps1`
- Create: `scripts/monitor.ps1`

- [ ] **Step 1: Rewrite the README navigation and project overview**

Keep the existing hardware, web-player, wired-host, dashboard, and ANC0 details,
but add a project map, quick-start links, explicit repository identity note, and
links to the four detailed documents.

- [ ] **Step 2: Document the architecture**

Describe the ESP32 capture path, clip/web path, host receiver, and dashboard
data flow. State that this branch contains the phase-1 capture and NLMS tools.

- [ ] **Step 3: Document the hardware**

Move the current pin table and microphone L/R strap requirements into a focused
hardware document, retaining the exact GPIO numbers and electrical notes.

- [ ] **Step 4: Document the ANC0 protocol**

Document the 12-byte little-endian header, packet fields, stereo sample order,
16 kHz/16-bit format, pre-roll flag, and sequence-gap behavior.

- [ ] **Step 5: Document local development**

Document ESP-IDF setup, build/flash/monitor commands, host dependency setup,
host tests, and generated-file handling.

- [ ] **Step 6: Add PowerShell wrappers**

Each wrapper must fail clearly if `idf.py` is unavailable and then invoke the
existing ESP-IDF command. The build wrapper uses:

```powershell
$ErrorActionPreference = "Stop"
if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
    throw "idf.py was not found. Run the ESP-IDF export script first."
}
idf.py build
```

The flash wrapper accepts an optional `-Port` parameter and invokes
`idf.py -p $Port flash`; the monitor wrapper invokes `idf.py -p $Port monitor`.

### Task 5: Clean tracked editor configuration and verify the full restructure

**Files:**
- Modify: `.vscode/settings.json`
- Modify: `.gitignore`

- [ ] **Step 1: Remove machine-specific serial-port configuration**

Keep the relative clangd compile-commands path, but remove the tracked
`"idf.port": "COM19"` setting so another developer's machine is not forced to
use the current user's port.

- [ ] **Step 2: Add standard host/test ignores**

Add `.pytest_cache/`, `.mypy_cache/`, and `.coverage` without removing the
existing build, SDK, virtual-environment, recording, WAV, or generated-dashboard
rules.

- [ ] **Step 3: Compile all Python files**

Run:

```powershell
python -m py_compile host/dashboard.py host/receive.py host/tests/test_dashboard.py
```

Expected: exit code 0 and no output.

- [ ] **Step 4: Attempt the ESP-IDF build**

Run:

```powershell
idf.py build
```

Expected: successful build when the ESP-IDF environment is exported. If the
toolchain is unavailable, report that exact limitation instead of claiming a
firmware build passed.

- [ ] **Step 5: Review the final diff and repository identity**

Run:

```powershell
git diff --stat
git diff -- CMakeLists.txt .git/config
git status --short
```

Confirm there is no remote rename, no repository-name operation, no scanner,
and no unrelated source behavior change.
