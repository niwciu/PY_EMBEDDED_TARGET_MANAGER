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

The CLI accepts legacy and normalized module schemas. Ensure the YAML includes a `build` section defining the `system` (`make` or `ninja`) and the `modules` list.
