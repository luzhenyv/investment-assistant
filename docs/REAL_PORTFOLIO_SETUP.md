# Going Live: Real Portfolio Setup

This guide moves you from the **demo** config to running the weekly engine on your
**real** accounts — a stocks+options+cash account and a separate ETF account — while
keeping that real data version-controlled locally but **never** pushed to GitHub.

## What lives where

| Location | Tracked by main repo? | Pushed to GitHub? | Contents |
|---|---|---|---|
| `config/`, `quant/`, `*.py`, `docs/`, `config/templates/` | yes | yes | code, strategy defaults, templates, this guide — **no secrets** |
| `config/demo/` | yes | yes | the **demo** profile (safe sample numbers, same shape as a real profile) |
| `private/` | **no** (git-ignored) | **never** | your **real** money — its own local-only git repo |

Two independent barriers keep real data off GitHub:
1. `/private/` is in the main repo's `.gitignore`, so the main repo can't stage, commit,
   or push it — not even `git push --all`.
2. `private/` is its **own** git repo with **no remote configured**, so a `git push` from
   inside it has nowhere to go.

It is *not* a git submodule — there is no link from the main repo to it.

## Profiles

The active profile is chosen by the `PROFILE` environment variable:

| `PROFILE` | Config | Portfolio / Watchlist | Reports |
|---|---|---|---|
| `demo` (default) | `config/demo/config.yaml` | `config/demo/*.yaml` | `output/demo/` |
| `stocks` | `private/stocks/config.yaml` | `private/stocks/*.yaml` | `output/stocks/` |
| `etf` | `private/etf/config.yaml` | `private/etf/*.yaml` | `output/etf/` |

```sh
PROFILE=stocks uv run weekly_review.py
PROFILE=etf    uv run weekly_review.py
uv run weekly_review.py            # defaults to demo
```

## One-time setup

If `private/` was scaffolded for you, skip to step 4 to fill in real numbers. Otherwise:

1. **Create the private repo** (own git history, **no remote**):
   ```sh
   mkdir -p private/stocks private/etf
   git -C private init
   # Do NOT run `git -C private remote add ...` unless you read "Off-machine backup" below.
   ```
2. **Seed each profile from the templates:**
   ```sh
   cp config/demo/config.yaml                  private/stocks/config.yaml
   cp config/templates/portfolio.example.yaml  private/stocks/portfolio.yaml
   cp config/templates/watchlist.example.yaml  private/stocks/watchlist.yaml
   cp config/templates/options.example.yaml    private/stocks/options.yaml
   # repeat for private/etf/ (ETF account usually needs no options.yaml)
   cp config/demo/config.yaml                  private/etf/config.yaml
   cp config/templates/portfolio.example.yaml  private/etf/portfolio.yaml
   cp config/templates/watchlist.example.yaml  private/etf/watchlist.yaml
   ```
3. **Tune each `config.yaml`** for that account — most importantly `target_weights`
   (per-symbol allocation) and `lifecycle.max_positions`. The ETF account is typically a
   short watchlist (e.g. `VOO`, `QQQM`, `SCHD`) with simple targets.
4. **Fill real numbers** into `portfolio.yaml` (cash + share counts) and `watchlist.yaml`.
5. **Commit the snapshot:**
   ```sh
   git -C private add -A
   git -C private commit -m "Initial real portfolio"
   ```

## Weekly workflow

1. Update `private/stocks/portfolio.yaml` — current cash and share counts.
2. Log option legs in `private/stocks/options.yaml` (reference only; see below).
3. Run the review:
   ```sh
   PROFILE=stocks uv run weekly_review.py
   ```
4. Read `output/stocks/weekly_report.md`, then place trades manually (you pick strikes/sizing).
5. Snapshot the week so you can diff decisions over time:
   ```sh
   git -C private add -A && git -C private commit -m "Week of $(date +%F)"
   ```
6. Repeat for the ETF account with `PROFILE=etf`.

## Options convention

`options.yaml` is **not read by the engine** — options remain intent *hints* in v0.1. It
exists so each weekly private-repo commit captures your full position (legs, strikes,
expiries, premium) for your own records and review. Schema is in
`config/templates/options.example.yaml`.

## Off-machine backup (optional, opt-in)

The private repo has no remote by design. If you want a backup, push it **only** to a repo
**you own and have set private**:
```sh
git -C private remote add origin git@github.com:<you>/my-portfolio-private.git
git -C private push -u origin main
```
⚠️ Once you add a remote, the "no remote" barrier is gone — double-check the destination
repo is private. The demo/code repo's `.gitignore` barrier still stands regardless.

## Safety checklist

```sh
git check-ignore private          # → prints "private" (ignored by main repo)
git status                        # → does NOT list private/
git -C private remote -v          # → empty, unless you opted into backup above
git -C private log --oneline      # → your snapshots (real version control works)
```
