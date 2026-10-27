# Installation

Hydra needs Python 3.11 or later. Install `hydra-ctl` from the `hydra-git` folder with [uv](https://docs.astral.sh/uv/) or pip:

=== "uv"

    ```sh
    uv tool install ./hydra-git
    ```

=== "pip"

    ```sh
    pip install ./hydra-git
    ```

Then run `hydra-ctl` on its own to see the command list.

## Updating

After pulling changes, install again:

=== "uv"

    ```sh
    uv tool install --reinstall ./hydra-git
    ```

=== "pip"

    ```sh
    pip install --force-reinstall --no-deps ./hydra-git
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
