# Installation

Hydra needs Python 3.11 or later. Install `hydra-ctl` from GitHub with [uv](https://docs.astral.sh/uv/) or pip:

=== "uv"

    ```sh
    uv tool install git+https://github.com/meridiangray/openhydra
    ```

=== "pip"

    ```sh
    pip install git+https://github.com/meridiangray/openhydra
    ```

Then run `hydra-ctl` on its own to see the command list.

## Updating

To get the latest version:

=== "uv"

    ```sh
    uv tool install --reinstall git+https://github.com/meridiangray/openhydra
    ```

=== "pip"

    ```sh
    pip install --upgrade --force-reinstall --no-deps git+https://github.com/meridiangray/openhydra
    ```

## Removing

=== "uv"

    ```sh
    uv tool uninstall open-hydra
    ```

=== "pip"

    ```sh
    pip uninstall open-hydra
    ```

To use Hydra from an AI assistant, install [hydra-mcp](guides/mcp.md#setup) as well.
