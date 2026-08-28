#!/usr/bin/env bash
# Authenticate the dx CLI from .env and pin the project everything bills to.
#
#     source scripts/dx-env.sh
#
# Must be sourced, not executed -- it only exports variables. See
# docs/scripts/DNANexus.md for what each one does and why.

# Every `return` below is followed by `|| exit 1`, the fallback for someone
# running this file instead of sourcing it; shellcheck cannot see that path and
# reads those as dead code.
# shellcheck disable=SC2317
_dx_env_repo="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
_dx_env_file="${_dx_env_repo}/.env"

_dx_env_say() { echo "dx-env: $*" >&2; }

# One key out of .env. Tolerates `export KEY=`, spaces around the `=`, quotes,
# CRLF line endings and trailing comments, because every one of those has shown
# up in a hand-edited .env and a silently empty token reads as a bad password.
_dx_env_get() {
    awk -v key="$1" '
        /^[[:space:]]*#/ { next }
        {
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            eq = index(line, "=")
            if (eq == 0) next
            k = substr(line, 1, eq - 1)
            gsub(/[[:space:]]/, "", k)
            if (k != key) next
            v = substr(line, eq + 1)
            sub(/^[[:space:]]+/, "", v)
            sub(/[[:space:]\r]+$/, "", v)
            gsub(/^["'"'"']|["'"'"']$/, "", v)
            print v
            exit
        }
    ' "${_dx_env_file}"
}

# `return`, not `exit`: this file is sourced, and exiting would close the
# caller's shell. The `|| exit` keeps it honest if someone runs it anyway.
if [[ ! -f "${_dx_env_file}" ]]; then
    _dx_env_say "no ${_dx_env_file}; copy .env.example and add your token"
    return 1 2>/dev/null || exit 1
fi

_dx_token="$(_dx_env_get DX_API_TOKEN)"
[[ -n "${_dx_token}" ]] || { _dx_env_say "DX_API_TOKEN is empty in ${_dx_env_file}"
    return 1 2>/dev/null || exit 1; }

# `dx` lives in the non-default `dx` dependency-group, and `uv sync` resyncs to
# exactly the groups you name -- so a plain `uv sync` silently uninstalls it.
# The failure surfaces later as an opaque `Failed to spawn: dx`, so check for it
# here, where the fix is obvious.
if ! uv run --group dx --no-sync dx --version >/dev/null 2>&1; then
    echo "dx-env: dxpy missing from .venv (a plain 'uv sync' removes it)." >&2
    echo "dx-env: restoring with 'uv sync --group dx' ..." >&2
    uv sync -q --group dx || { _dx_env_say "could not install dxpy; run 'uv sync --group dx'"
        return 1 2>/dev/null || exit 1; }
fi

# The CLI wants a JSON blob, not the bare token. Exporting DX_API_TOKEN alone
# fails with a misleading "At least VIEW permission is required".
export DX_SECURITY_CONTEXT="{\"auth_token_type\":\"Bearer\",\"auth_token\":\"${_dx_token}\"}"

# dxpy's own regexes raise SyntaxWarning on 3.13; without this every dx call
# prints ~18 lines of noise first.
export PYTHONWARNINGS=ignore::SyntaxWarning

# The project pin is about BILLING, not convenience: compute bills to the
# `billTo` of the project a job runs in, and a project you created bills to you.
# Prefer the id -- resolving the name costs an API call and is ambiguous if two
# projects share a name (dx sorts by descending permission, so the first hit is
# the one you can actually write to).
_dx_project="$(_dx_env_get DX_PROJECT_ID)"
if [[ -z "${_dx_project}" ]]; then
    _dx_name="$(_dx_env_get DX_PROJECT_NAME)"
    [[ -n "${_dx_name}" ]] || { _dx_env_say "set DX_PROJECT_ID or DX_PROJECT_NAME in ${_dx_env_file}"
        return 1 2>/dev/null || exit 1; }
    _dx_project="$(uv run --group dx --no-sync dx find projects --name "${_dx_name}" --brief 2>/dev/null | head -1 | tr -d '\r')"
    [[ -n "${_dx_project}" ]] || { _dx_env_say "no project named '${_dx_name}' is visible to this token"
        return 1 2>/dev/null || exit 1; }
fi
export DX_PROJECT_CONTEXT_ID="${_dx_project}"

echo "dx-env: authenticated; project pinned to ${DX_PROJECT_CONTEXT_ID}" >&2
unset _dx_env_repo _dx_env_file _dx_token _dx_project _dx_name
unset -f _dx_env_get _dx_env_say
