<div align="center">

# ◐ ltui

**A stupidly fast, actually beautiful TUI for [Linear](https://linear.app).**

Your whole workspace, grouped the way triage actually works —
`In Review` on top, `Done` at the bottom, your tickets first.

[![python](https://img.shields.io/badge/python-3.11+-89b4fa?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![built with textual](https://img.shields.io/badge/built%20with-textual-b4befe?style=flat-square)](https://github.com/Textualize/textual)
[![license](https://img.shields.io/badge/license-GPLv3%20%2B%20commercial-a6e3a1?style=flat-square)](LICENSE)
[![linear api](https://img.shields.io/badge/linear-graphql%20api-5e6ad2?style=flat-square&logo=linear&logoColor=white)](https://developers.linear.app)

<img src="assets/hero.png" alt="ltui — issue list with detail panel" width="100%">

<sub>every screenshot in this README is generated from <b>fake demo data</b> by
<a href="tools/screenshots.py"><code>tools/screenshots.py</code></a> — no real tickets were harmed</sub>

</div>

---

> [!NOTE]
> **not on Linear?** this repo also ships [**jtui**](../jtui/) for Jira and
> [**sctui**](../sctui/) for Shortcut — same app, same speed, same themes.

## why another Linear TUI?

Because every Linear TUI I tried had the same two problems: **slow** and **ugly**.

The slowness isn't even their fault — Linear's GraphQL API takes 2–5 seconds to
return a decently sized team. Most TUIs just make you eat that wait on every
launch. ltui doesn't:

- 📦 **instant startup** — your last-seen issues render from a local cache in
  ~50ms while fresh data loads in the background. You're scrolling before the
  API has even said hello.
- 🎨 **actually pretty** — rounded borders, five themes,
  Linear's own state colors, nerd font icons, priority bars like the real app,
  and subtle fade animations on panels and modals.
- ⌨️ **keyboard first, mouse welcome** — vim keys everywhere, but everything is
  also clickable: tickets, teams, even the hint bar. The panel dividers
  **drag to resize** (double-click to reset), and your layout sticks.

## features

|     |                                                                                     |
| --- | ----------------------------------------------------------------------------------- |
| 🗂️  | **smart grouping** — `In Review` → `In Progress` → `Todo` → `Backlog` → `Done` — sorted by how close work is to shipping, freshest tickets first inside every group |
| 👤  | **mine first** — your tickets float to the top of every group; press `m` to hide everyone else entirely |
| 📁  | **project view** — `v` regroups the whole board by project (color-coded, status-ordered inside); the detail panel names each ticket's project |
| 🌿  | **`y` yanks the git branch** — Linear's generated branch name straight to your clipboard (or the URL / identifier); ticket → `git checkout -b` in seconds |
| 👥  | **assign without leaving** — `a` reassigns to anyone on the team, or you, or nobody |
| 🌳  | **hierarchy aware** — the detail panel shows the parent ticket and all sub-issues with a done-count, next to blocked/blocking relations |
| 🔄  | **never stale** — the board silently re-syncs every 3 minutes |
| 🔀  | **multiple workspaces + combined inbox** — configure one key per Linear workspace, then press `w` to switch or see every workspace together |
| 🎯  | **focused views** — Active shows only Todo + Started; `F` selects any status combination, `d` shows or hides Done, and `C` filters by current, next, previous, no cycle, or a named cycle |
| 📖  | **rich detail panel** — full markdown descriptions (code blocks, checklists, quotes), labels, comments — scrolls with arrows, vim keys, or mouse wheel |
| ✏️  | **write, don't just read** — create tickets, change status & priority, add comments without leaving the terminal |
| 🚧  | **blocked & blocking at a glance** — a red badge on tickets that are blocked, an orange one on tickets holding others up; the detail panel names the exact tickets |
| 🔍  | **instant filter** — `/` fuzzy-narrows by title, identifier, or assignee as you type |
| 🌚  | **five themes** — `mocha`, pure-black `void`, monochrome `onyx`, `clear` (no background — your terminal's transparency/blur shows through), and `system` (drawn in your terminal's own ANSI palette: your kitty theme *is* the ltui theme) — cycle with `t` |
| ⚙️  | **profile & settings** — who you are bottom-left, `,` opens a settings panel with live theme preview, preferences, and cache controls |
| 🧠  | **remembers everything** — last team, theme, filters persist across sessions |
| 🎛️  | **fully remappable** — every key rebindable via `~/.config/ltui/config.json` (`ltui --init-config`), with a vim motion layer (`ctrl+d/u`, `[`/`]` group jumps, `:` palette) out of the box |
| 🔌  | **zero config** — reuses your [linear-cli](https://github.com/Finesssee/linear-cli) API key, or set `LINEAR_API_KEY` |

## install

works on any linux · macOS · windows, straight from this repo.
grab [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io) and:

```sh
uv tool install "git+https://github.com/runpantheon/ltui#subdirectory=ltui"
# or
pipx install "git+https://github.com/runpantheon/ltui#subdirectory=ltui"
```

or build it yourself from source:

```sh
git clone https://github.com/runpantheon/ltui && cd ltui/ltui
pip install .
```

To run an edited checkout directly from the repository root without
reinstalling it, point `uv` at the inner Python project:

```sh
uv run --directory ltui ltui
```

Plain `uv run ltui` only discovers the project when your current directory is
that inner `ltui/` directory; otherwise it may run an older globally installed
copy from `~/.local/bin`.

either way you now have the command:

```sh
ltui
```

upgrading later: `uv tool upgrade ltui-linear` / `pipx reinstall ltui-linear`
(the *package* is named `ltui-linear`; the command is `ltui`).

<details>
<summary><b>platform notes</b></summary>

- **linux** — any terminal that isn't from 1985 works: kitty, alacritty,
  ghostty, wezterm, foot…
- **macOS** — `brew install pipx` first if you don't have it. iTerm2, ghostty,
  kitty, or WezTerm recommended over stock Terminal.app.
- **windows** — Python 3.11+ (`winget install Python.Python.3.12`), then pipx.
  Run it in **Windows Terminal** — legacy conhost will not do it justice.
- everywhere: needs **python ≥ 3.11**.

</details>

> [!TIP]
> Use a terminal with a [nerd font](https://www.nerdfonts.com/) for the icons.
> Everything else degrades gracefully without one.

## auth

**there is nothing to set up.** launch `ltui` and if no key is found, it
walks you through it: click the link to Linear's API-keys page, paste the
key, done — ltui validates it live and stores it in
`~/.config/ltui/config.toml` (permissions `600`).

<div align="center">
<img src="assets/onboard.png" alt="first-run onboarding" width="70%">
</div>

already set up somewhere? ltui checks, in order:

1. the `LINEAR_API_KEY` environment variable
2. `[workspaces.*]` profiles in its own `~/.config/ltui/config.toml`
3. the legacy top-level `api_key` in that same file
4. your [linear-cli](https://github.com/Finesssee/linear-cli) config — if you
   already use linear-cli, ltui logs in with zero setup

### multiple workspaces

Linear API keys are workspace-specific, so create one key in each workspace
and put them in `~/.config/ltui/config.toml`:

```toml
default_workspace = "work"

[workspaces.work]
label = "Acme"
api_key = "lin_api_your_work_key"

[workspaces.personal]
label = "Personal"
api_key = "lin_api_your_personal_key"
```

Protect the file, then restart ltui:

```sh
chmod 600 ~/.config/ltui/config.toml
```

Press `w` (or click the workspace name in the profile card) to switch. The
picker also includes **All workspaces**, which merges the remembered team from
every configured workspace into one interactive board. Issue rows carry a
workspace badge, and `v` cycles through workspace, status, and project
grouping. Duplicate Linear ids from different workspaces remain separate.

The combined board is not read-only: opening details, adding comments, and
changing an issue always use the API key for that issue's source workspace.
`m` applies “mine only” using your identity in each workspace, and `n` asks
which workspace should receive the new ticket. Cached data appears immediately
while all workspaces refresh concurrently; if one refresh fails, the others
remain usable and that workspace's valid cache is retained. In Settings,
**clear all caches** clears the real workspace caches without deleting your
profiles or combined-view preferences.

ltui remembers the active workspace or combined view and restores it on every
device independently. Each real workspace keeps its own selected team, theme,
grouping, mine-only preference, status view, cycle view, layout, and cached
issues; the combined view keeps separate display preferences.

On multiple Macs, copy the same protected `config.toml` to each one. You can
reuse each workspace's API key across your own devices; if you revoke a key,
replace that profile's value on every Mac.

`default_workspace` is optional; without it, the first profile is used. A
saved active workspace takes precedence when it still exists. The
`LINEAR_API_KEY` environment variable intentionally overrides the entire file
and creates a single temporary `Environment` profile, so unset it when you want
the in-app workspace picker.

Existing single-workspace files remain valid:

```toml
api_key = "lin_api_your_key"
```

Your key never leaves your machine — ltui talks directly to
`api.linear.app` and nothing else.

First launch also greets you with a 20-second tour card (once, never again),
and `?` opens the full keybinding cheatsheet whenever you need it.

<div align="center">
<img src="assets/welcome.png" alt="first-run welcome" width="60%">
</div>

## keys

| key      | action                                        |
| -------- | --------------------------------------------- |
| `↑↓` `jk` | move around (lists *and* the detail panel)   |
| `←` `→`  | walk the panes: teams ◂ issues ▸ detail — `→` on a ticket opens it |
| `1` `2` `3` | toggle the **Teams / Issues / Detail** panels |
| `enter` / click | open ticket detail panel                |
| `esc`    | close panel / dismiss modal / clear filter    |
| `n`      | **new ticket** (prompts for a workspace in All) |
| `s`      | change **status**                             |
| `p`      | change **priority**                           |
| `a`      | change **assignee** (or unassign)             |
| `l`      | edit **labels** (multi-select)                |
| `P`      | move to a **project** — or create one inline  |
| `c`      | add a **comment** (`ctrl+s` to send)          |
| `o`      | open ticket in **browser**                    |
| `y`      | **yank** — copy branch name / url / id        |
| `/`      | filter issues                                 |
| `w`      | switch **workspace / All workspaces view**      |
| `m`      | toggle **mine only**                          |
| `F`      | choose visible **status types**               |
| `d`      | show / hide **Done** in the current view      |
| `C`      | choose a **cycle view**                       |
| `v`      | group by **workspace / status / project**     |
| `V`      | filter to a **single project**                |
| `t`      | cycle **theme**                               |
| `,`      | open **settings**                             |
| `r`      | refresh                                       |
| `g` `G`  | jump to top / bottom                          |
| `ctrl+d/u` `ctrl+f/b` | half page / full page             |
| `[` `]`  | previous / next **group**                     |
| `:`      | command palette                               |
| `?`      | **help** — keybinding cheatsheet              |
| `q`      | quit                                          |

## project view

In a single workspace, `v` flips the board between status and **projects**. In
**All workspaces**, it cycles through workspace, status, and project sections.
Each project gets a color-coded section (freshest work first, status order
inside), with tickets that belong to no project collected at the bottom. Press
`V` to zoom into a **single project** in any grouping.

<div align="center">
<img src="assets/projects.png" alt="group by project" width="80%">
</div>

## status & cycle views

The default **Active** view contains only Linear's `unstarted` and `started`
workflow types (shown as Todo and Started). It intentionally excludes Backlog,
Triage, Done, Canceled, and Duplicate issues.

Press `F` to choose exactly which status types are visible, including Backlog,
Triage, Canceled, or any combination. The picker also has **Active** and
**Everything** presets. Press `d` to add or remove Done without revealing any
other excluded status; from Active this toggles between Active and
Active + Done.

Press `C` to choose **All cycles**, **Current**, **Next**, **Previous**,
**No cycle**, or a specific named cycle. In All workspaces, named cycles are
scoped and labeled by workspace, so cycles with the same Linear id or name do
not collide. Status and cycle views combine with mine-only, project, and text
filters, and are remembered separately for each workspace and the combined
view.

## make it yours

every keybind is remappable, vim-style motions included:

```sh
ltui --init-config    # writes ~/.config/ltui/config.json
```

```jsonc
{
  "keybinds": {
    "new_ticket": "n",            // any action -> any key
    "switch_workspace": "w",
    "filter_status": "F",
    "toggle_done": "d",
    "pick_cycle": "C",
    "toggle_teams_panel": "1",
    "toggle_issues_panel": "2",
    "toggle_detail_panel": "3",
    "yank": ["y", "ctrl+y"]       // or several keys
  },
  "options": {
    "auto_refresh_seconds": 180,  // 0 disables background sync
    "animations": true,           // false = no fades, no name wave
    "hide_issues_on_detail": true // false keeps Issues beside Detail
  }
}
```

key names are [Textual key names](https://textual.textualize.io/guide/input/#key)
(`slash`, `comma`, `question_mark`, `ctrl+x`, …). unknown or invalid entries
fall back to the defaults; changes apply on restart.

## the detail panel

`enter` (or a click) opens any ticket in a side panel — markdown description
rendered properly, comments threaded underneath, and every action one key away.
The footer hints are clickable too. Press `1`, `2`, or `3` to toggle the Teams,
Issues, or Detail panel. Opening Detail hides Issues by default so the ticket
gets the available space; press `2` to reveal Issues again. Closing Detail
restores your saved panel layout. Detail expands to the full available width
when it is the only visible panel, making the layout practical in narrow
terminals. Set `hide_issues_on_detail` to `false` to keep the split view when a
ticket opens. Teams and Issues visibility is remembered separately for each
workspace.

<div align="center">
<img src="assets/picker.png" alt="status picker" width="80%">
</div>

## creating tickets

`n` opens a minimal composer: title, optional markdown description, `ctrl+s`.
The ticket lands in your list already highlighted, ready for `s` / `p` to
slot it into the right column.

<div align="center">
<img src="assets/new-ticket.png" alt="new ticket modal" width="80%">
</div>

## settings

Your profile lives bottom-left — workspace, name, org, and one-click toggles
for theme and mine-only. Press `,` (or click ` settings`) for the panel: switch
workspace, choose status and cycle views, flip preferences, or clear the active
workspace's cache. From the combined view, the same action is labeled
**clear all caches**.

<div align="center">
<img src="assets/settings.png" alt="settings panel" width="80%">
</div>

## themes

Cycle with `t`. Your choice sticks.

|  `mocha` — catppuccin warmth | `void` — pure black, OLED bait | `onyx` — monochrome steel |
| --- | --- | --- |
| ![mocha](assets/list.png) | ![void](assets/theme-void.png) | ![onyx](assets/theme-onyx.png) |

Two of them can't be screenshotted honestly:

- **`clear`** paints **no background at all** and uses the terminal's default
  foreground for task text, so both light and dark terminal themes remain
  readable. If your terminal is transparent or blurred, ltui is too.
- **`system`** goes further: the whole UI chrome is drawn in your terminal's
  **ANSI palette** (plus the transparent background) — whatever theme your
  kitty/alacritty/ghostty is running, ltui matches it automatically. Ticket
  data (state colors, labels) stays true to Linear. Selected rows use terminal
  reverse-video colors for reliable contrast on both light and dark palettes.

Made for rice.

Not enough? `ctrl+p` → *Change theme* opens the theme picker with **every
built-in Textual theme** — nord, gruvbox, dracula, tokyo-night, rose-pine, the
whole catppuccin family and more. The whole app **restyles live as you scroll**
the list; `enter` keeps it, `esc` puts everything back. `t` keeps cycling the
four ltui themes.

<div align="center">
<img src="assets/themes.png" alt="theme picker with live preview" width="80%">
</div>

## how it's fast

Linear's API is the bottleneck — a 250-issue team takes **2.5–4.5s** to fetch,
and no client can fix that. So ltui stops pretending the network is fast:

```
launch ──▶ render cached issues (~50ms) ──▶ you're already working
                    │
                    └──▶ background refresh ──▶ rows swap in silently
```

- issue lists cache to `~/.cache/ltui/<workspace>/` per team
- mutations (status, priority, new tickets) update the cache immediately —
  what you see is always what you did
- the `↻ refreshing` badge in the border tells you when fresh data is inbound
- the board silently re-syncs every 3 minutes, so it never goes stale

## data & privacy

- **reads**: teams, issues, workflow states, comments — for the teams you view
- **writes**: only the mutations you explicitly trigger (create / status /
  priority / comment)
- **talks to**: `api.linear.app` — nothing else, no telemetry, no analytics
- **stores locally**: cache in `~/.cache/ltui/<workspace>/`, workspace UI state
  in `~/.local/state/ltui/workspaces/<workspace>.json`, and the active profile
  name (never its key) in `~/.local/state/ltui/global.json`

## faq

<details>
<summary><b>Only ~250 issues show per team?</b></summary>

ltui fetches the 250 most-recently-updated issues per team. For triage that's
effectively everything alive; ancient `Done` tickets fall off the bottom,
which is where they belong.

</details>

<details>
<summary><b>Why do the screenshots look fake?</b></summary>

Because they are! They're generated by <code>tools/screenshots.py</code> with a
mocked API — fake org, fake tickets, fake people. Run it yourself; it never
touches the network.

</details>

<details>
<summary><b>Some icons render as boxes</b></summary>

Install a <a href="https://www.nerdfonts.com/">nerd font</a> and set it as your
terminal font. Everything else degrades gracefully.

</details>

<details>
<summary><b>Does it work with multiple workspaces?</b></summary>

Yes. Add one API key per workspace under <code>[workspaces.*]</code> in
<code>~/.config/ltui/config.toml</code>, then press <code>w</code>. The picker
shows labels only—never API keys—and every workspace has isolated cache and UI
state. See <a href="#multiple-workspaces">multiple workspaces</a> above.

</details>

## contributing

It's one Python file. Read it in ten minutes, break it in five:

```sh
git clone https://github.com/runpantheon/ltui && cd ltui/ltui
python -m venv .venv && .venv/bin/pip install -e . && .venv/bin/ltui
```

PRs welcome — keep it fast, keep it pretty.

## credits

made by [**@Gheat1**](https://github.com/Gheat1) — issues, ideas, and PRs
welcome over at [Gheat1/ltui](https://github.com/runpantheon/ltui/tree/main/ltui).

building your own TUI? the themes, widgets, and design system behind ltui
live in [**ricekit**](https://github.com/Gheat1/ricekit) — and ltui has
siblings: [**jtui**](https://github.com/runpantheon/ltui/tree/main/jtui) for Jira and
[**sctui**](https://github.com/runpantheon/ltui/tree/main/sctui) for Shortcut.

standing on the shoulders of [textual](https://github.com/Textualize/textual)
and the [Linear API](https://developers.linear.app).

## license

**Dual-licensed.** [GPL-3.0](../LICENSE) for everyone — free to use anywhere,
work included; forks and redistributions must stay open source with credit,
so closed-source rebranding/resale is not permitted. Need it outside GPL
terms? Pantheon offers commercial licenses — open an issue or reach out.

<div align="center">
<sub>not affiliated with Linear — just a fan of good issue trackers and good terminals</sub>
</div>
