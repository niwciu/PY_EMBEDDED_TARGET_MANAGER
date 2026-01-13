# Embedded Target Manager

Embedded Target Manager is a CLI utility for running build targets across multiple embedded modules based on a YAML configuration file. It orchestrates CMake configuration, executes Make/Ninja targets, and generates HTML report indexes.

## Installation

```bash
pip install embedded-target-manager
```

## Usage

```bash
embedded-target-manager --config config.yaml
```

### Options

- `-c, --config`: Path to the YAML configuration file (default: `config.yaml`).
- `-r, --reconfigure`: Remove existing `out` directories before running CMake.
- `-k, --keep-going`: Continue executing targets even if one fails.
- `-v, --verbose`: Print detailed output.
- `-m, --modules`: Run targets only for the specified modules.
- `-t, --targets`: Run only the specified targets.

## Development

```bash
python -m embedded_target_manager --config config.yaml
```

## Configuration format

The YAML configuration must include a `build` section defining the `system` (`make` or `ninja`) and a `module_paths` list pointing to directories that contain module subfolders (each module folder must include a `CMakeLists.txt`).

Example with multiple module paths, common targets, exclusions, and additions:

```yaml
build:
  system: ninja
  jobs: 8

module_paths:
  - ../firmware/modules
  - ../platform/modules

common_targets:
  - all
  - unit_tests
  - ccmr

excluded_targets:
  bootloader:
    - unit_tests
  sensor_driver:
    - ccmr

additional_targets:
  bootloader:
    - flash
  app_core:
    - coverage
```
