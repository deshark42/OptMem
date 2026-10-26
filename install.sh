#!/bin/sh
# OptMem installer. Run it again to update the tool without replacing memories.
#
#   sh ./install.sh [options for memo init]
#   curl -fsSL https://raw.githubusercontent.com/deshark42/OptMem/main/install.sh | sh

set -e
DIR="$HOME/.optmem"

command -v python3 >/dev/null || {
  echo "OptMem is one Python file, and this machine has no python3." >&2
  echo "Install python3, then run this line again." >&2
  exit 1
}

SOURCE=
if [ -f "$0" ]; then
  SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
  if [ -f "$SCRIPT_DIR/memo" ]; then
    SOURCE="$SCRIPT_DIR/memo"
  fi
fi

mkdir -p "$DIR"
if [ -n "$SOURCE" ]; then
  cp "$SOURCE" "$DIR/memo.new"
else
  curl -fsSL https://raw.githubusercontent.com/deshark42/OptMem/main/memo -o "$DIR/memo.new"
fi
mv "$DIR/memo.new" "$DIR/memo"
chmod +x "$DIR/memo"

exec "$DIR/memo" init "$@"
