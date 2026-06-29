from __future__ import annotations

from .runtime_config import render_active_configs_from_db


def main() -> None:
    render_active_configs_from_db()
    print("OmniProxyGate active nginx configs rendered from /data")


if __name__ == "__main__":
    main()
