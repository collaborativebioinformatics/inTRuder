#!/usr/bin/env bash
# Authenticate the dx CLI from .env and pin the group's project.
#
#     source scripts/dx-env.sh
#
# Must be sourced, not executed -- it only exports variables. See
# docs/DNANexus.md for what each one does and why.

_dx_env_repo="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
_dx_env_file="${_dx_env_repo}/.env"

if [[ ! -f "${_dx_env_file}" ]]; then
    echo "dx-env: no ${_dx_env_file}; copy .env.example and add your token" >&2
    return 1 2>/dev/null || exit 1
fi

_dx_token="$(awk -F= '/^DX_API_TOKEN=/{print $2}' "${_dx_env_file}" | tr -d '"'"'"' \r')"

if [[ -z "${_dx_token}" ]]; then
    echo "dx-env: DX_API_TOKEN is empty in ${_dx_env_file}" >&2
    return 1 2>/dev/null || exit 1
fi

# `dx` lives in the non-default `dx` dependency-group, and `uv sync` resyncs to
# exactly the groups you name -- so a plain `uv sync` (or one naming only extras,
# e.g. `uv sync --extra embed`) silently uninstalls it. The failure surfaces later
# as an opaque `Failed to spawn: dx`, so check for it here, where the fix is
# obvious.
if ! uv run --group dx --no-sync dx --version >/dev/null 2>&1; then
    echo "dx-env: dxpy missing from .venv (a plain 'uv sync' removes it)." >&2
    echo "dx-env: restoring with 'uv sync --group dx' ..." >&2
    uv sync -q --group dx || {
        echo "dx-env: could not install dxpy; run 'uv sync --group dx'" >&2
        return 1 2>/dev/null || exit 1
    }
fi

# The CLI wants a JSON blob, not the bare token. Exporting DX_API_TOKEN alone
# fails with a misleading "At least VIEW permission is required".
export DX_SECURITY_CONTEXT="{\"auth_token_type\":\"Bearer\",\"auth_token\":\"${_dx_token}\"}"

# Pins every job to Group2_2026, which bills to org-baylor_hackathon_2020_sales.
# Without this a job can land in a personal project and bill you.
export DX_PROJECT_CONTEXT_ID=project-JB6zg5Q0pzX96qVJjz7gKg58

# dxpy's own regexes raise SyntaxWarning on 3.13; without this every dx call
# prints ~18 lines of noise first.
export PYTHONWARNINGS=ignore::SyntaxWarning

unset _dx_env_repo _dx_env_file _dx_token
echo "dx-env: authenticated; project pinned to Group2_2026" >&2
