#!/usr/bin/env bash
# Shared core of the four dx-{instance,batch}-{cpu,gpu}.sh front-ends. Sourced
# by them, never run on its own.
#
# The front-ends exist so that the two decisions you actually make -- CPU or
# GPU, terminal or program -- are in the command's name instead of in flags you
# have to remember. They deliberately hold no logic of their own: each sets two
# variables and sources this, which hands everything to scripts/dx-instance.sh.
#
# In particular NONE of them tries to work out whether you passed a command.
# Doing that here would mean copying dx-instance.sh's option table -- which
# option takes a value, where `--` ends the flags -- into five places that would
# then drift. Instead the mode is passed down as --batch or --interactive and
# dx-instance.sh, the one parser that already knows, enforces it.
#
# The caller sets:
#   DX_WRAP_MODE   batch | interactive
#   DX_WRAP_ARCH   cpu | gpu
# and passes its own "$@".

_dx_wrap_src="${BASH_SOURCE[1]:-$0}"
_dx_wrap_self="$(basename "$_dx_wrap_src")"
_dx_wrap_repo="$(cd "$(dirname "$_dx_wrap_src")/.." && pwd)"

# --help prints the caller's own header, not dx-instance.sh's. Only the leading
# options are scanned: a `-h` after `--` belongs to your program, not to us.
for _dx_wrap_arg in "$@"; do
    case "$_dx_wrap_arg" in
        --) break ;;
        -h|--help)
            awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' \
                "$_dx_wrap_src"
            cat <<EOF

Every scripts/dx-instance.sh option is accepted here and passed straight
through; \`scripts/dx-instance.sh --help\` documents all of them. The ones you
will reach for:

  -t, --time DURATION   how long the box may live at most        [2h]
  -f, --input ID|PATH   stage a platform file onto the worker; repeatable
  -o, --output-dir DIR  where results land locally               [data/dx/<run>]
  -b, --branch BRANCH   branch the worker clones          [your current branch]
      --sync-args ARGS  extra flags for the worker's uv sync, e.g. "--group dx"
  -i, --instance TYPE   override the instance type this script picks
  -n, --dry-run         print the platform calls instead of running them

  scripts/dx-instance.sh --list-instances     what this project may launch
EOF
            exit 0 ;;
        -*) ;;
        *)  break ;;
    esac
done

# GPU asks for --gpu rather than naming a type, so the one place the L4's name
# is written stays dx-instance.sh; CPU is already its default. Our flags go
# first, so anything you pass -- including -i -- still overrides them.
_dx_wrap_flags=("--$DX_WRAP_MODE")
[ "$DX_WRAP_ARCH" = gpu ] && _dx_wrap_flags+=("--gpu")

# So dx-instance.sh's errors name the command you actually typed.
export DX_WRAPPER_NAME="scripts/$_dx_wrap_self"
exec "$_dx_wrap_repo/scripts/dx-instance.sh" "${_dx_wrap_flags[@]}" "$@"
