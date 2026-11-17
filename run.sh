#!/bin/sh
# pvj-logos-link launcher for macOS / Linux.
#   ./run.sh                                  Signals on the Logos testnet
#   ./run.sh --mock                           Signals with fake messages
#   ./run.sh --mode pvj --pvj 192.168.1.40    Logos -> a PVJ phone
#   (every flag of bridge/logos_bridge.py works; --help lists them)
set -e
cd "$(dirname "$0")"
case " $* " in
  *" --mock "*|*" --help "*|*" -h "*) ;;
  *)
    if ! command -v logosctl >/dev/null 2>&1 && [ ! -x "$HOME/.local/logosctl/bin/logosctl" ]; then
      echo "Installing logosctl from the official Logos script..."
      curl -fsSL https://raw.githubusercontent.com/logos-co/logos-docs/main/resources/scripts/install-logosctl.sh | sh
    fi
    ;;
esac
exec python3 bridge/logos_bridge.py --open "$@"
