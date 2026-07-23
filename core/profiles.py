"""Resolve which account's files to run against, selected by the $PROFILE env var.

    PROFILE=demo   (default) → config/demo/{config,portfolio,watchlist}.yaml
    PROFILE=stocks           → private/stocks/{config,portfolio,watchlist}.yaml
    PROFILE=etf              → private/etf/{config,portfolio,watchlist}.yaml

`private/` is git-ignored by this repo and kept in its own local-only repo, so real
holdings never reach the GitHub remote. See docs/REAL_PORTFOLIO_SETUP.md.
"""
from __future__ import annotations

import os


def resolve(root: str) -> tuple[str, str, str, str, str]:
    """Return (config, portfolio, watchlist, options, out_dir) paths for the active profile.

    `options.yaml` is optional (not every profile records option positions), so it is
    returned but not checked for existence — quant.options.load_options tolerates absence.
    """
    profile = os.environ.get("PROFILE", "demo")
    if profile == "demo":
        base = os.path.join(root, "config", "demo")
    else:
        base = os.path.join(root, "private", profile)
    config = os.path.join(base, "config.yaml")
    portfolio = os.path.join(base, "portfolio.yaml")
    watchlist = os.path.join(base, "watchlist.yaml")
    options = os.path.join(base, "options.yaml")
    out_dir = os.path.join(root, "output", profile)

    for path in (config, portfolio, watchlist):
        if not os.path.exists(path):
            raise SystemExit(
                f"PROFILE={profile}: missing {path}\n"
                f"See docs/REAL_PORTFOLIO_SETUP.md to create your private profile."
            )
    return config, portfolio, watchlist, options, out_dir
