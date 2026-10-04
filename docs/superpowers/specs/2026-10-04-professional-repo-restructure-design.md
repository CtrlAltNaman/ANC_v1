# Professional Repository Restructure Design

## Goal

Restructure the DhvaniKavach/ANC_v1 working tree into a clearer, maintainable
ESP-IDF project without renaming the Git repository, changing the capture
protocol, or altering runtime behavior.

## Scope

In scope:

- Remove the temporary `main/i2c_scan.c` diagnostic application.
- Restore the capture application as the firmware component entry point.
- Separate firmware implementation files from public headers.
- Add focused documentation for architecture, hardware, protocol, and local
  development.
- Add lightweight host-tool dependency and regression-test structure.
- Add Windows helper scripts for common ESP-IDF commands.
- Remove machine-specific editor configuration from tracked settings.
- Keep the existing Git repository name, remote, project identity, ANC0 wire
  protocol, microphone pinout, and host command behavior unchanged.

Out of scope:

- Rewriting the ANC/NLMS implementation.
- Adding the missing ML training pipeline to this local branch.
- Changing hardware pins, sample format, Wi-Fi behavior, or HTTP endpoints.
- Renaming the repository or changing its Git remote.

## Target Structure

```text
.
├── CMakeLists.txt
├── partitions.csv
├── sdkconfig.defaults
├── README.md
├── docs/
│   ├── architecture.md
│   ├── development.md
│   ├── hardware.md
│   └── protocol.md
├── main/
│   ├── CMakeLists.txt
│   ├── include/
│   │   ├── clip.h
│   │   └── web.h
│   └── src/
│       ├── clip.c
│       ├── main.c
│       └── web.c
├── host/
│   ├── README.md
│   ├── requirements.txt
│   ├── dashboard.py
│   ├── receive.py
│   └── tests/
│       └── test_dashboard.py
└── scripts/
    ├── build.ps1
    ├── flash.ps1
    └── monitor.ps1
```

The ESP-IDF project remains rooted at the repository root because that is the
least disruptive layout for `idf.py`, VS Code ESP-IDF integration, and the
existing build directory. The host scripts remain at their current paths so
existing commands continue to work.

## Build and Runtime Boundaries

- `main/src/main.c` owns GPIO, I2S, PTT, USB packet emission, and the capture
  loop.
- `main/src/clip.c` owns PSRAM clip buffering and WAV assembly.
- `main/src/web.c` owns Wi-Fi, HTTP, WebSocket notification, and the embedded
  player page.
- `main/include/` exposes only the interfaces shared by those firmware units.
- `host/receive.py` remains the ANC0-to-WAV receiver.
- `host/dashboard.py` remains the standard-library NLMS analysis dashboard.
- `host/tests/` verifies stable host-side analysis behavior without requiring
  hardware.

## Compatibility Rules

- The root CMake project name remains `DhvaniKavach` as currently configured.
- No Git remote or repository name is changed.
- Firmware include paths are updated to use the new public-header directory,
  but function signatures and protocol constants remain unchanged.
- Host invocation remains:

  ```text
  python host/receive.py --port <port> --out recordings/
  python host/dashboard.py recordings/<capture>.wav
  ```

- `recordings/`, generated WAV files, generated dashboards, build output, and
  local SDK configuration remain ignored.

## Verification

The restructure is accepted only when all of the following are true:

1. `main/i2c_scan.c` is absent and no CMake file references it.
2. `main/CMakeLists.txt` registers `src/main.c`, `src/clip.c`, and `src/web.c`.
3. The host regression tests pass with the standard library.
4. Python compilation succeeds for both host scripts and the test module.
5. ESP-IDF configuration/build is attempted when the local toolchain is
   available; otherwise the exact missing-tool limitation is reported.
6. Git diff confirms no remote/repository rename and no unrelated source
   behavior changes.
