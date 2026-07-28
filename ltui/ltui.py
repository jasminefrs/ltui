#!/usr/bin/env python3
"""ltui — a fast, clean TUI for Linear.

Copyright (C) 2026 Gheat / Pantheon
This program is free software licensed under the GNU GPL v3 or later;
you may redistribute and modify it only under those terms. Distributed
WITHOUT ANY WARRANTY. Commercial licenses are available from Pantheon
(dual licensing) — see the repository README. See also the LICENSE file.
"""

from __future__ import annotations

__version__ = "0.15.0"

import asyncio
import json
import os
import re
import secrets
import sys
import tomllib
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color as TColor
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Footer, Input, Markdown, OptionList, Static, TextArea
from textual.widgets.option_list import Option
from textual.worker import WorkerCancelled, WorkerState

API_URL = "https://api.linear.app/graphql"
CONFIG = Path.home() / ".config/linear-cli/config.toml"
LTUI_CONFIG = Path.home() / ".config/ltui/config.toml"
LTUI_JSON_CONFIG = Path.home() / ".config/ltui/config.json"
STATE_FILE = Path.home() / ".local/state/ltui/state.json"
CACHE_DIR = Path.home() / ".cache/ltui"
AUTO_REFRESH_SECONDS = 180
ALL_WORKSPACES = "__all__"


@dataclass(frozen=True)
class StoragePaths:
    """Filesystem roots used by ltui, injectable so tests stay isolated."""

    config: Path
    linear_config: Path
    state_root: Path
    cache_root: Path

    @property
    def legacy_state(self) -> Path:
        return self.state_root / "state.json"

    @property
    def global_state(self) -> Path:
        return self.state_root / "global.json"

    @property
    def workspace_states(self) -> Path:
        return self.state_root / "workspaces"


DEFAULT_STORAGE = StoragePaths(
    config=LTUI_CONFIG,
    linear_config=CONFIG,
    state_root=STATE_FILE.parent,
    cache_root=CACHE_DIR,
)

# ── palette (catppuccin mocha) ────────────────────────────────────────────
C_TEXT = "#cdd6f4"
C_SUB = "#a6adc8"
C_DIM = "#6c7086"
C_FAINT = "#45475a"
C_VFAINT = "#313244"
C_BLUE = "#89b4fa"
C_LAV = "#b4befe"
C_PEACH = "#fab387"
C_GREEN = "#a6e3a1"
C_RED = "#f38ba8"
C_MAUVE = "#cba6f7"

_PALETTE = dict(
    C_TEXT=C_TEXT, C_SUB=C_SUB, C_DIM=C_DIM, C_FAINT=C_FAINT, C_VFAINT=C_VFAINT,
    C_BLUE=C_BLUE, C_LAV=C_LAV, C_PEACH=C_PEACH, C_GREEN=C_GREEN, C_RED=C_RED,
    C_MAUVE=C_MAUVE,
)
_PALETTE_ANSI = dict(
    C_TEXT="default", C_SUB="white", C_DIM="bright_black", C_FAINT="bright_black",
    C_VFAINT="bright_black", C_BLUE="blue", C_LAV="bright_blue", C_PEACH="yellow",
    C_GREEN="green", C_RED="red", C_MAUVE="magenta",
)


def set_palette(ansi: bool) -> None:
    """Swap the chrome palette; `system` draws it in terminal ANSI colors."""
    globals().update(_PALETTE_ANSI if ansi else _PALETTE)

# ── themes ────────────────────────────────────────────────────────────────
_ACCENTS = dict(
    success=C_GREEN, warning="#f9e2af", error=C_RED, dark=True
)

THEMES = [
    Theme(
        name="mocha",
        primary=C_BLUE, secondary=C_MAUVE, accent="#f5c2e7",
        background="#1e1e2e", surface="#313244", panel="#181825",
        foreground=C_TEXT, **_ACCENTS,
        variables={
            "ltui-border": "#45475a",
            "ltui-border-focus": C_BLUE,
            "ltui-border-detail": C_LAV,
            "ltui-modal-bg": "#181825",
            "ltui-cursor": "#3e4869",
            "ltui-overlay": "black 40%",
            "scrollbar": "#313244",
            "scrollbar-hover": "#45475a",
            "scrollbar-active": "#585b70",
            "scrollbar-background": "#181825",
            "screen-selection-background": "#b4befe 35%",
            "input-selection-background": "#b4befe 35%",
        },
    ),
    Theme(
        name="void",
        primary=C_BLUE, secondary=C_MAUVE, accent="#f5c2e7",
        background="#000000", surface="#101018", panel="#070709",
        foreground=C_TEXT, **_ACCENTS,
        variables={
            "ltui-border": "#26262e",
            "ltui-border-focus": C_BLUE,
            "ltui-border-detail": C_LAV,
            "ltui-modal-bg": "#0a0a10",
            "ltui-cursor": "#1e2a4a",
            "ltui-overlay": "black 40%",
            "scrollbar": "#1e1e28",
            "scrollbar-hover": "#2c2c38",
            "scrollbar-active": "#3c3c4a",
            "scrollbar-background": "#0a0a10",
            "screen-selection-background": "#b4befe 30%",
            "input-selection-background": "#b4befe 30%",
        },
    ),
    Theme(
        name="onyx",
        primary="#9aa5b5", secondary="#7d8494", accent="#b8c0cc",
        background="#0e0e11", surface="#1b1b20", panel="#131317",
        foreground="#d4d6dd", **_ACCENTS,
        variables={
            "ltui-border": "#33333c",
            "ltui-border-focus": "#9aa5b5",
            "ltui-border-detail": "#b8c0cc",
            "ltui-modal-bg": "#141419",
            "ltui-cursor": "#2b303b",
            "ltui-overlay": "black 40%",
            "scrollbar": "#2a2a32",
            "scrollbar-hover": "#3a3a44",
            "scrollbar-active": "#4a4a56",
            "scrollbar-background": "#131317",
            "screen-selection-background": "#b8c0cc 30%",
            "input-selection-background": "#b8c0cc 30%",
        },
    ),
    # no background at all — the terminal's own background (and any
    # blur/transparency it has) shows through
    Theme(
        name="clear",
        primary="#8a93a5", secondary="#6f7787", accent="#a9b1c0",
        background="ansi_default", surface="ansi_default", panel="ansi_default",
        foreground=C_TEXT, **_ACCENTS,
        variables={
            "ltui-border": "#3c3f4a",
            "ltui-border-focus": "#8a93a5",
            "ltui-border-detail": "#a9b1c0",
            "ltui-modal-bg": "#16161d",
            "ltui-cursor": "#282c38",
            "ltui-overlay": "transparent",
            "scrollbar": "#3c3f4a",
            "scrollbar-hover": "#4a4e5a",
            "scrollbar-active": "#5a5f6d",
            "scrollbar-background": "transparent",
            "screen-selection-background": "#3f4655",
            "input-selection-background": "#3f4655",
        },
    ),
    # your terminal's own ANSI palette + no background: a custom kitty /
    # alacritty theme becomes the ltui theme
    Theme(
        name="system",
        primary="ansi_blue", secondary="ansi_magenta", accent="ansi_cyan",
        background="ansi_default", surface="ansi_default", panel="ansi_default",
        foreground="ansi_default",
        success="ansi_green", warning="ansi_yellow", error="ansi_red", dark=True,
        variables={
            "ltui-border": "ansi_bright_black",
            "ltui-border-focus": "ansi_blue",
            "ltui-border-detail": "ansi_bright_blue",
            "ltui-modal-bg": "ansi_black",
            "ltui-cursor": "ansi_bright_black",
            "ltui-overlay": "transparent",
            "scrollbar": "ansi_bright_black",
            "scrollbar-hover": "ansi_bright_black",
            "scrollbar-active": "ansi_blue",
            "scrollbar-background": "ansi_default",
            "screen-selection-background": "ansi_cyan",
            "screen-selection-foreground": "ansi_black",
            "input-selection-background": "ansi_cyan",
        },
    ),
]
THEME_NAMES = [t.name for t in THEMES]

TYPE_RANK = {
    "triage": 0,
    "started": 1,
    "unstarted": 2,
    "backlog": 3,
    "completed": 4,
    "canceled": 5,
    "duplicate": 6,
}

KNOWN_STATUS_TYPES = (
    "triage",
    "backlog",
    "unstarted",
    "started",
    "completed",
    "canceled",
    "duplicate",
)
STATUS_TYPE_LABELS = {
    "triage": "Triage",
    "backlog": "Backlog",
    "unstarted": "Todo",
    "started": "Started",
    "completed": "Done",
    "canceled": "Canceled",
    "duplicate": "Duplicate",
}
ACTIVE_STATUS_TYPES = frozenset(("unstarted", "started"))


@dataclass(frozen=True)
class StatusView:
    mode: str
    types: frozenset[str]


DEFAULT_STATUS_VIEW = StatusView("include", ACTIVE_STATUS_TYPES)
EVERYTHING_STATUS_VIEW = StatusView("exclude", frozenset())


def status_view_matches(view: StatusView, state_type: str) -> bool:
    """Return whether a Linear workflow type is visible in ``view``."""
    if view.mode == "exclude":
        return state_type not in view.types
    return state_type in view.types


def status_view_from_state(value: object) -> StatusView:
    """Decode persisted status-view data, falling back safely to Active."""
    if not isinstance(value, dict):
        return DEFAULT_STATUS_VIEW
    mode = value.get("mode")
    raw_types = value.get("types")
    if mode not in ("include", "exclude") or not isinstance(raw_types, list):
        return DEFAULT_STATUS_VIEW
    if not all(isinstance(item, str) and item for item in raw_types):
        return DEFAULT_STATUS_VIEW
    types = frozenset(raw_types)
    if mode == "include" and not types:
        return DEFAULT_STATUS_VIEW
    return StatusView(mode, types)


def status_view_to_state(view: StatusView) -> dict:
    return {"mode": view.mode, "types": sorted(view.types)}


def toggle_done_in_status_view(view: StatusView) -> StatusView:
    """Toggle completed issues without changing any other type's visibility."""
    if status_view_matches(view, "completed"):
        if view.mode == "exclude":
            return StatusView("exclude", view.types | {"completed"})
        remaining = view.types - {"completed"}
        return StatusView("include", remaining) if remaining else DEFAULT_STATUS_VIEW
    if view.mode == "exclude":
        return StatusView("exclude", view.types - {"completed"})
    return StatusView("include", view.types | {"completed"})


def status_view_label(view: StatusView) -> str:
    if view == DEFAULT_STATUS_VIEW:
        return "Active"
    if view == EVERYTHING_STATUS_VIEW:
        return "Everything"
    if view == StatusView("include", ACTIVE_STATUS_TYPES | {"completed"}):
        return "Active + Done"
    if view.mode == "exclude":
        hidden = ", ".join(
            STATUS_TYPE_LABELS.get(item, item) for item in sorted(view.types)
        )
        return f"Everything − {hidden}"
    labels = [
        STATUS_TYPE_LABELS.get(item, item)
        for item in KNOWN_STATUS_TYPES
        if item in view.types
    ]
    return ", ".join(labels) if labels else "Active"


@dataclass(frozen=True)
class CycleView:
    mode: str
    workspace: str | None = None
    team_id: str | None = None
    cycle_id: str | None = None


DEFAULT_CYCLE_VIEW = CycleView("all")
CYCLE_SEMANTIC_MODES = frozenset(("all", "current", "next", "previous", "none"))


def cycle_view_from_state(value: object) -> CycleView:
    """Decode a persisted cycle selector without overloading ids as modes."""
    if not isinstance(value, dict):
        return DEFAULT_CYCLE_VIEW
    mode = value.get("mode")
    if mode in CYCLE_SEMANTIC_MODES:
        return CycleView(mode)
    if mode != "named":
        return DEFAULT_CYCLE_VIEW
    identity = (value.get("workspace"), value.get("team_id"), value.get("cycle_id"))
    if not all(isinstance(item, str) and item for item in identity):
        return DEFAULT_CYCLE_VIEW
    return CycleView("named", *identity)


def cycle_view_to_state(view: CycleView) -> dict:
    data = {"mode": view.mode}
    if view.mode == "named":
        data.update(
            workspace=view.workspace,
            team_id=view.team_id,
            cycle_id=view.cycle_id,
        )
    return data


def cycle_key(workspace: str, cycle_id: str) -> str:
    return scoped_id(workspace, cycle_id)


def cycle_name(cycle: dict) -> str:
    return cycle.get("name") or f"Cycle {cycle.get('number', '?')}"


def cycle_sort_key(cycle: dict) -> tuple:
    if cycle.get("isActive"):
        rank = 0
    elif cycle.get("isNext"):
        rank = 1
    elif cycle.get("isFuture"):
        rank = 2
    elif cycle.get("isPrevious"):
        rank = 3
    elif cycle.get("isPast"):
        rank = 4
    else:
        rank = 5
    return rank, cycle.get("startsAt") or "", cycle.get("number") or 0


def cycle_view_matches(view: CycleView, issue: dict, workspace: str) -> bool:
    cycle = issue.get("cycle")
    if view.mode == "all":
        return True
    if view.mode == "none":
        return cycle is None
    if cycle is None:
        return False
    if view.mode == "current":
        return bool(cycle.get("isActive"))
    if view.mode == "next":
        return bool(cycle.get("isNext"))
    if view.mode == "previous":
        return bool(cycle.get("isPrevious"))
    return bool(
        view.mode == "named"
        and view.workspace == workspace
        and view.cycle_id == cycle.get("id")
    )

PRIORITIES = [(1, "Urgent"), (2, "High"), (3, "Medium"), (4, "Low"), (0, "No priority")]

# ── graphql ───────────────────────────────────────────────────────────────
CYCLE_FIELDS = """
        id name number startsAt endsAt
        isActive isFuture isPast isPrevious isNext
"""

ISSUE_FIELDS = """
        id identifier title description url priority branchName
        updatedAt createdAt
        state { id name color type position }
        assignee { id displayName }
        labels(first: 6) { nodes { id name color } }
        relations(first: 6) { nodes { type relatedIssue { identifier } } }
        inverseRelations(first: 6) { nodes { type issue { identifier } } }
        project { id name color }
        cycle {
""" + CYCLE_FIELDS + """
        }
        parent { identifier }
"""

QL_BOOT = """
query {
  viewer { id displayName }
  organization { name }
  teams(first: 50) { nodes { id name key color } }
}"""

QL_ISSUES = f"""
query($teamId: String!) {{
  team(id: $teamId) {{
    issues(first: 250, orderBy: updatedAt) {{
      nodes {{ {ISSUE_FIELDS} }}
    }}
    states {{ nodes {{ id name color type position }} }}
  }}
}}"""

QL_CYCLES = f"""
query($teamId: String!) {{
  team(id: $teamId) {{
    cycles(first: 250) {{
      nodes {{ {CYCLE_FIELDS} }}
      pageInfo {{ hasNextPage }}
    }}
  }}
}}"""

M_CREATE = f"""
mutation($teamId: String!, $title: String!, $desc: String) {{
  issueCreate(input: {{teamId: $teamId, title: $title, description: $desc}}) {{
    success
    issue {{ {ISSUE_FIELDS} }}
  }}
}}"""

QL_COMMENTS = """
query($id: String!) {
  issue(id: $id) {
    parent { identifier title }
    children(first: 25) {
      nodes { identifier title state { name color type } }
    }
    comments(first: 50) {
      nodes { id body createdAt user { displayName } botActor { name } }
    }
  }
}"""

QL_MEMBERS = """
query($teamId: String!) {
  team(id: $teamId) {
    members(first: 50) { nodes { id displayName } }
  }
}"""

M_STATE = """
mutation($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: {stateId: $stateId}) {
    success
    issue { id state { id name color type position } }
  }
}"""

M_ASSIGN = """
mutation($id: String!, $assigneeId: String) {
  issueUpdate(id: $id, input: {assigneeId: $assigneeId}) {
    success
    issue { id assignee { id displayName } }
  }
}"""

M_PRIORITY = """
mutation($id: String!, $p: Int!) {
  issueUpdate(id: $id, input: {priority: $p}) { success }
}"""

QL_TEAM_LABELS = """
query($teamId: String!) {
  team(id: $teamId) { labels(first: 100) { nodes { id name color } } }
}"""

QL_TEAM_PROJECTS = """
query($teamId: String!) {
  team(id: $teamId) { projects(first: 100) { nodes { id name color } } }
}"""

M_LABELS = """
mutation($id: String!, $labelIds: [String!]!) {
  issueUpdate(id: $id, input: {labelIds: $labelIds}) {
    success
    issue { id labels(first: 6) { nodes { id name color } } }
  }
}"""

M_PROJECT = """
mutation($id: String!, $projectId: String) {
  issueUpdate(id: $id, input: {projectId: $projectId}) {
    success
    issue { id project { id name color } }
  }
}"""

M_PROJECT_CREATE = """
mutation($name: String!, $teamIds: [String!]!) {
  projectCreate(input: {name: $name, teamIds: $teamIds}) {
    success
    project { id name color }
  }
}"""

M_COMMENT = """
mutation($id: String!, $body: String!) {
  commentCreate(input: {issueId: $id, body: $body}) { success }
}"""


def load_user_config() -> dict:
    """~/.config/ltui/config.json — keybinds + options. Read once at startup."""
    try:
        return json.loads(LTUI_JSON_CONFIG.read_text())
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"ltui: ignoring invalid config.json ({e})", file=sys.stderr)
        return {}


USER_CONFIG = load_user_config()
CONFIG_OPTIONS = USER_CONFIG.get("options", {}) if isinstance(USER_CONFIG, dict) else {}

# action -> (default keys, footer label or None). every action here can be
# remapped in config.json under "keybinds"; a value may be a key or a list.
DEFAULT_KEYBINDS = {
    "new_ticket": (["n"], "new"),
    "change_status": (["s"], "status"),
    "add_comment": (["c"], "comment"),
    "filter": (["slash"], "filter"),
    "filter_status": (["F"], None),
    "toggle_done": (["d"], None),
    "toggle_mine": (["m"], "mine"),
    "toggle_group": (["v"], "group"),
    "pick_project": (["V"], None),
    "pick_cycle": (["C"], None),
    "cycle_theme": (["t"], "theme"),
    "open_settings": (["comma"], None),
    "switch_workspace": (["w"], None),
    "help": (["question_mark"], "help"),
    "quit": (["q"], "quit"),
    "refresh": (["r"], None),
    "change_priority": (["p"], None),
    "edit_labels": (["l"], None),
    "move_project": (["P"], None),
    "change_assignee": (["a"], None),
    "open_browser": (["o"], None),
    "yank": (["y"], None),
    # vim layer (additive)
    "next_group": (["right_square_bracket"], None),
    "prev_group": (["left_square_bracket"], None),
    "command_palette": (["colon"], None),
    # lateral arrows walk the panes: teams ◂ issues ▸ detail
    "focus_left": (["left"], None),
    "focus_right": (["right"], None),
}


def build_bindings(user_keybinds: dict | None = None) -> list:
    """App bindings from defaults + config.json overrides. Fail-safe: a bad
    config falls back to the defaults for the affected action."""
    merged: dict[str, tuple[list, str | None]] = {}
    user_keybinds = user_keybinds if user_keybinds is not None else (
        USER_CONFIG.get("keybinds", {}) if isinstance(USER_CONFIG, dict) else {}
    )
    for action, (keys, label) in DEFAULT_KEYBINDS.items():
        custom = user_keybinds.get(action)
        if isinstance(custom, str):
            keys = [custom]
        elif isinstance(custom, list) and all(isinstance(k, str) for k in custom) and custom:
            keys = custom
        merged[action] = (keys, label)
    bindings = [Binding("escape", "back", show=False)]
    for action, (keys, label) in merged.items():
        for i, key in enumerate(keys):
            bindings.append(
                Binding(
                    key,
                    action,
                    label or "",
                    show=bool(label) and i == 0,
                )
            )
    return bindings


CONFIG_TEMPLATE = """{
  "keybinds": {
    "new_ticket": "n",
    "change_status": "s",
    "add_comment": "c",
    "filter": "slash",
    "filter_status": "F",
    "toggle_done": "d",
    "toggle_mine": "m",
    "toggle_group": "v",
    "pick_project": "V",
    "pick_cycle": "C",
    "cycle_theme": "t",
    "open_settings": "comma",
    "switch_workspace": "w",
    "help": "question_mark",
    "quit": "q",
    "refresh": "r",
    "change_priority": "p",
    "edit_labels": "l",
    "move_project": "P",
    "change_assignee": "a",
    "open_browser": "o",
    "yank": "y",
    "next_group": "right_square_bracket",
    "prev_group": "left_square_bracket",
    "command_palette": "colon",
    "focus_left": "left",
    "focus_right": "right"
  },
  "options": {
    "auto_refresh_seconds": 180,
    "animations": true
  }
}
"""


PROFILE_COMPONENT = re.compile(r"^[A-Za-z0-9_-]+$")


class CredentialsNotFound(RuntimeError):
    """No usable Linear credentials were found in any supported source."""


class ProfileConfigError(ValueError):
    """The workspace profile configuration is present but invalid."""


@dataclass(frozen=True)
class WorkspaceProfile:
    name: str
    label: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class ProfileResolution:
    profiles: tuple[WorkspaceProfile, ...]
    active: str
    source: str
    allow_legacy_storage: bool = False

    def profile(self, name: str) -> WorkspaceProfile:
        for profile in self.profiles:
            if profile.name == name:
                return profile
        raise KeyError(name)


@dataclass(frozen=True)
class WorkspaceSnapshot:
    profile: str
    label: str
    boot: dict
    team: dict
    issues: list[dict]
    states: list[dict]
    cycles: list[dict]
    cycles_complete: bool


def _validate_component(value: str, kind: str) -> str:
    if not isinstance(value, str) or not PROFILE_COMPONENT.fullmatch(value):
        raise ValueError(
            f"invalid {kind}; use only letters, numbers, underscores, and hyphens"
        )
    return value


def scoped_id(profile: str, remote_id: str) -> str:
    """Encode a profile + remote id as an unambiguous Textual option id."""
    return f"{len(profile)}:{profile}{remote_id}"


def parse_workspace_profiles(
    data: dict, saved_active: str | None = None
) -> ProfileResolution:
    """Parse the explicit ``[workspaces.*]`` configuration format."""
    raw_profiles = data.get("workspaces")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ProfileConfigError("workspaces must be a non-empty table")
    profiles: list[WorkspaceProfile] = []
    for raw_name, raw_profile in raw_profiles.items():
        try:
            name = _validate_component(raw_name, "workspace name")
        except ValueError as error:
            raise ProfileConfigError(str(error)) from None
        if name == ALL_WORKSPACES:
            raise ProfileConfigError(f"workspace name {ALL_WORKSPACES!r} is reserved")
        if not isinstance(raw_profile, dict):
            raise ProfileConfigError(f"workspace {name!r} must be a table")
        api_key = raw_profile.get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProfileConfigError(f"workspace {name!r} needs a non-empty api_key")
        label = raw_profile.get("label", name)
        if not isinstance(label, str) or not label.strip():
            raise ProfileConfigError(f"workspace {name!r} has an invalid label")
        profiles.append(WorkspaceProfile(name, label.strip(), api_key.strip()))

    names = {profile.name for profile in profiles}
    configured_default = data.get("default_workspace")
    if configured_default is not None:
        if not isinstance(configured_default, str) or configured_default not in names:
            raise ProfileConfigError("default_workspace does not name a workspace")
    saved_is_valid = isinstance(saved_active, str) and (
        saved_active in names
        or (saved_active == ALL_WORKSPACES and len(profiles) > 1)
    )
    active = saved_active if saved_is_valid else configured_default or profiles[0].name
    return ProfileResolution(tuple(profiles), active, "multi")


def _warn_if_config_is_public(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        if path.stat().st_mode & 0o077:
            print(
                f"ltui: {path} contains API keys; run: chmod 600 {path}",
                file=sys.stderr,
            )
    except OSError:
        pass


def resolve_workspace_profiles(
    storage: StoragePaths = DEFAULT_STORAGE,
    environ: dict[str, str] | os._Environ[str] | None = None,
) -> ProfileResolution:
    """Resolve workspace credentials without masking invalid configuration."""
    environment = os.environ if environ is None else environ
    if key := environment.get("LINEAR_API_KEY"):
        return ProfileResolution(
            (WorkspaceProfile("environment", "Environment", key),),
            "environment",
            "environment",
        )

    if storage.config.exists():
        try:
            config_data = tomllib.loads(storage.config.read_text())
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ProfileConfigError(f"invalid ltui config: {error}") from None
        if config_data:
            _warn_if_config_is_public(storage.config)
        if "workspaces" in config_data:
            saved = load_global_state(storage).get("active_workspace")
            return parse_workspace_profiles(config_data, saved)
        key = config_data.get("api_key")
        if key is not None:
            if not isinstance(key, str) or not key.strip():
                raise ProfileConfigError("api_key must be a non-empty string")
            profile = WorkspaceProfile("default", "Default", key.strip())
            return ProfileResolution((profile,), "default", "legacy", True)
        if config_data:
            raise ProfileConfigError(
                "config must define api_key or one or more workspaces"
            )

    try:
        linear_data = tomllib.loads(storage.linear_config.read_text())
        workspace_name = linear_data.get("current", "default")
        raw_workspace = linear_data["workspaces"][workspace_name]
        key = raw_workspace["api_key"]
        if not isinstance(key, str) or not key.strip():
            raise KeyError("api_key")
        safe_name = (
            workspace_name
            if isinstance(workspace_name, str)
            and PROFILE_COMPONENT.fullmatch(workspace_name)
            and workspace_name != ALL_WORKSPACES
            else "linear-cli"
        )
        profile = WorkspaceProfile(safe_name, str(workspace_name), key.strip())
        return ProfileResolution((profile,), safe_name, "linear-cli")
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        raise CredentialsNotFound("no Linear API key found") from None


def load_api_key(storage: StoragePaths = DEFAULT_STORAGE) -> str:
    """Backward-compatible single-key accessor."""
    resolved = resolve_workspace_profiles(storage)
    active = (
        resolved.profiles[0].name
        if resolved.active == ALL_WORKSPACES
        else resolved.active
    )
    return resolved.profile(active).api_key


def save_api_key(key: str, storage: StoragePaths = DEFAULT_STORAGE) -> None:
    if not isinstance(key, str) or not key.strip():
        raise ValueError("API key cannot be empty")
    if "\n" in key or "\r" in key:
        raise ValueError("API key cannot contain a line break")
    escaped = key.strip().replace("\\", "\\\\").replace('"', '\\"')
    _atomic_write_text(storage.config, storage.config.parent, f'api_key = "{escaped}"\n')


async def verify_key(key: str) -> str:
    """Check a key against the API; returns 'viewer @ org' or raises."""
    async with httpx.AsyncClient(
        headers={"Authorization": key, "Content-Type": "application/json"},
        timeout=15,
    ) as client:
        resp = await client.post(
            API_URL,
            json={
                "query": "query { viewer { displayName } organization { name } }"
            },
        )
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(data["errors"][0].get("message", "invalid key"))
        d = data["data"]
        return f"{d['viewer']['displayName']} @ {d['organization']['name']}"


# ── helpers ───────────────────────────────────────────────────────────────
def parse_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def rel_time(iso: str) -> str:
    s = (datetime.now(timezone.utc) - parse_dt(iso)).total_seconds()
    if s < 60:
        return "now"
    if s < 3600:
        return f"{int(s // 60)}m"
    if s < 86400:
        return f"{int(s // 3600)}h"
    if s < 604800:
        return f"{int(s // 86400)}d"
    if s < 2629800:
        return f"{int(s // 604800)}w"
    if s < 31557600:
        return f"{int(s // 2629800)}mo"
    return f"{int(s // 31557600)}y"


def state_icon(state: dict) -> str:
    t = state["type"]
    if t == "started" and "review" in state["name"].lower():
        return "◑"
    return {
        "triage": "◎",
        "backlog": "◌",
        "unstarted": "○",
        "started": "◐",
        "completed": "●",
        "canceled": "⊘",
        "duplicate": "⊘",
    }.get(t, "○")


def priority_cell(p: int) -> Text:
    t = Text()
    if p == 1:
        t.append(" ", style=f"bold {C_PEACH}")
        t.append("  ")
    elif p in (2, 3, 4):
        lit = {2: 3, 3: 2, 4: 1}[p]
        for i, ch in enumerate("▂▄▆"):
            t.append(ch, style=C_SUB if i < lit else C_VFAINT)
    else:
        t.append("···", style=C_VFAINT)
    return t


def block_info(issue: dict) -> tuple[list[str], list[str]]:
    """Identifiers this issue is blocked by, and identifiers it blocks."""
    blocked_by = [
        r["issue"]["identifier"]
        for r in (issue.get("inverseRelations") or {}).get("nodes", [])
        if r["type"] == "blocks"
    ]
    blocks = [
        r["relatedIssue"]["identifier"]
        for r in (issue.get("relations") or {}).get("nodes", [])
        if r["type"] == "blocks"
    ]
    return blocked_by, blocks


def priority_name(p: int) -> str:
    return dict((n, lbl) for n, lbl in PRIORITIES).get(p, "No priority")


def state_sort_key(s: dict):
    rank = TYPE_RANK.get(s["type"], 9)
    pos = s["position"] or 0
    return (rank, -pos if s["type"] == "started" else pos)


def issue_sort_key(i: dict):
    # most recently updated first within each status group
    return (-parse_dt(i["updatedAt"]).timestamp(),)


def _path_within(path: Path, root: Path) -> bool:
    path_abs = Path(os.path.abspath(path))
    root_abs = Path(os.path.abspath(root))
    return path_abs == root_abs or root_abs in path_abs.parents


def _check_no_symlinks(root: Path, path: Path) -> None:
    if not _path_within(path, root):
        raise ValueError("storage path escapes its configured root")
    root_abs = Path(os.path.abspath(root))
    path_abs = Path(os.path.abspath(path))
    current = root_abs
    candidates = [current]
    for component in path_abs.relative_to(root_abs).parts:
        current = current / component
        candidates.append(current)
    for candidate in candidates:
        try:
            if stat_is_symlink(candidate):
                raise OSError(f"refusing symlink in storage path: {candidate}")
        except FileNotFoundError:
            continue


def stat_is_symlink(path: Path) -> bool:
    return bool(path.lstat().st_mode & 0o170000 == 0o120000)


def _ensure_private_dir(root: Path, path: Path) -> None:
    _check_no_symlinks(root, path)
    root_abs = Path(os.path.abspath(root))
    path_abs = Path(os.path.abspath(path))
    relative_parts = path_abs.relative_to(root_abs).parts
    directories = [root_abs]
    directories.extend(
        root_abs.joinpath(*relative_parts[:index])
        for index in range(1, len(relative_parts) + 1)
    )
    for directory in directories:
        if directory.exists():
            if stat_is_symlink(directory) or not directory.is_dir():
                raise OSError(f"unsafe storage directory: {directory}")
        else:
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        if os.name != "nt":
            directory.chmod(0o700)


def _atomic_write_text(path: Path, root: Path, text: str) -> None:
    if not _path_within(path, root):
        raise ValueError("storage path escapes its configured root")
    _ensure_private_dir(root, path.parent)
    _check_no_symlinks(root, path)
    if path.exists() and stat_is_symlink(path):
        raise OSError(f"refusing symlink target: {path}")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    temp = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(temp, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and stat_is_symlink(path):
            raise OSError(f"refusing symlink target: {path}")
        os.replace(temp, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path, root: Path) -> dict | None:
    _check_no_symlinks(root, path)
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, root: Path, data: dict) -> None:
    _atomic_write_text(path, root, json.dumps(data, separators=(",", ":")))


def profile_state_path(storage: StoragePaths, profile: str) -> Path:
    _validate_component(profile, "workspace name")
    path = storage.workspace_states / f"{profile}.json"
    if not _path_within(path, storage.state_root):
        raise ValueError("workspace state path escapes its configured root")
    return path


def profile_cache_path(storage: StoragePaths, profile: str, name: str) -> Path:
    _validate_component(profile, "workspace name")
    _validate_component(name, "cache name")
    path = storage.cache_root / profile / f"{name}.json"
    if not _path_within(path, storage.cache_root):
        raise ValueError("workspace cache path escapes its configured root")
    return path


def load_global_state(storage: StoragePaths = DEFAULT_STORAGE) -> dict:
    return _read_json(storage.global_state, storage.state_root) or {}


def save_global_state(storage: StoragePaths, data: dict) -> None:
    _write_json(storage.global_state, storage.state_root, data)


def load_state(
    storage: StoragePaths = DEFAULT_STORAGE,
    profile: str = "default",
    allow_legacy: bool = False,
) -> dict:
    data = _read_json(profile_state_path(storage, profile), storage.state_root)
    if data is None and allow_legacy:
        data = _read_json(storage.legacy_state, storage.state_root)
    return data or {}


def save_state(
    storage: StoragePaths | dict,
    profile: str = "default",
    data: dict | None = None,
) -> None:
    # Keep the old ``save_state(data)`` call shape available to external users.
    if isinstance(storage, dict):
        data = storage
        storage = DEFAULT_STORAGE
    if data is None:
        raise TypeError("state data is required")
    _write_json(profile_state_path(storage, profile), storage.state_root, data)


def read_cache(
    storage: StoragePaths | str = DEFAULT_STORAGE,
    profile: str = "default",
    name: str | None = None,
    allow_legacy: bool = False,
) -> dict | None:
    # Keep the old ``read_cache(name)`` shape while the app migrates below.
    if isinstance(storage, str):
        name = storage
        storage = DEFAULT_STORAGE
    if name is None:
        raise TypeError("cache name is required")
    data = _read_json(profile_cache_path(storage, profile, name), storage.cache_root)
    if data is None and allow_legacy:
        _validate_component(name, "cache name")
        data = _read_json(storage.cache_root / f"{name}.json", storage.cache_root)
    return data


def write_cache(
    storage: StoragePaths | str,
    profile: str | dict,
    name: str | None = None,
    data: dict | None = None,
) -> None:
    # Keep the old ``write_cache(name, data)`` shape while the app migrates below.
    if isinstance(storage, str) and isinstance(profile, dict):
        name, data, storage, profile = storage, profile, DEFAULT_STORAGE, "default"
    if not isinstance(storage, StoragePaths) or not isinstance(profile, str):
        raise TypeError("invalid cache arguments")
    if name is None or data is None:
        raise TypeError("cache name and data are required")
    _write_json(profile_cache_path(storage, profile, name), storage.cache_root, data)


def clear_cache(
    storage: StoragePaths = DEFAULT_STORAGE,
    profile: str = "default",
    allow_legacy: bool = False,
) -> int:
    _validate_component(profile, "workspace name")
    directory = storage.cache_root / profile
    _check_no_symlinks(storage.cache_root, directory)
    count = 0
    if directory.exists():
        for path in directory.iterdir():
            if path.suffix != ".json":
                continue
            if stat_is_symlink(path):
                raise OSError(f"refusing symlink cache entry: {path}")
            path.unlink()
            count += 1
    if allow_legacy and storage.cache_root.exists():
        _check_no_symlinks(storage.cache_root, storage.cache_root)
        for path in storage.cache_root.iterdir():
            if path.suffix != ".json":
                continue
            if stat_is_symlink(path):
                raise OSError(f"refusing symlink cache entry: {path}")
            if not path.is_file():
                continue
            path.unlink()
            count += 1
    return count


# ── widgets ───────────────────────────────────────────────────────────────
def pop_in(widget, duration: float = 0.15) -> None:
    """Fade a freshly mounted container into place.

    (offset/slide animation isn't supported for ScalarOffset in textual 8.x,
    so this is opacity-only — still reads as motion at 150ms.)
    """
    if not CONFIG_OPTIONS.get("animations", True):
        return
    widget.styles.opacity = 0.0
    widget.styles.animate("opacity", 1.0, duration=duration, easing="out_cubic")


SPINNER_FRAMES = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"

FX_TICK = 0.12  # seconds per animation frame
FX_REST_TICKS = 26  # pause between wave sweeps (~3s)


def wave_markup(s: str, pos: int, base: str, hi: str) -> str:
    """One traveling letter, bolded + capitalized: gheatmc -> gHeatmc -> ..."""
    out = []
    for i, ch in enumerate(s):
        e = escape(ch)
        if i == pos:
            out.append(f"[bold {hi}]{e.upper()}[/]")
        else:
            out.append(f"[{base}]{e}[/]")
    return "".join(out)


class NavList(OptionList):
    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "first", show=False),
        Binding("G", "last", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("ctrl+f", "page_down", show=False),
        Binding("ctrl+b", "page_up", show=False),
    ]

    def _reveal_leading_rows(self) -> None:
        """Keep disabled headers above the first selectable row visible."""
        highlighted = self.highlighted
        if highlighted is None:
            return
        if all(
            self.get_option_at_index(index).disabled
            for index in range(highlighted)
        ):
            self.scroll_home(animate=False, force=True, immediate=True)

    def watch_highlighted(self, highlighted: int | None) -> None:
        super().watch_highlighted(highlighted)
        self._reveal_leading_rows()

    def action_first(self) -> None:
        super().action_first()
        # The reactive watcher does not run when the first item was already
        # highlighted (for example after mouse-wheel scrolling).
        self._reveal_leading_rows()

    def _snap_to_enabled(self, direction: int) -> None:
        """Page motions can land on a disabled header; nudge to a real row."""
        if not self.option_count:
            return
        i = self.highlighted
        if i is None:
            i = 0 if direction > 0 else self.option_count - 1
        elif not self.get_option_at_index(i).disabled:
            return
        order = range(i, self.option_count) if direction > 0 else range(i, -1, -1)
        fallback = range(i, -1, -1) if direction > 0 else range(i, self.option_count)
        for scan in (order, fallback):
            for j in scan:
                if not self.get_option_at_index(j).disabled:
                    self.highlighted = j
                    return

    def action_page_down(self) -> None:
        super().action_page_down()
        self._snap_to_enabled(1)

    def action_page_up(self) -> None:
        super().action_page_up()
        self._snap_to_enabled(-1)

    def on_resize(self, event) -> None:
        if self.id == "issues":
            app = self.app
            if getattr(app, "_issues", None):
                app.call_later(app.render_issues)


class DetailScroll(VerticalScroll):
    can_focus = True
    BINDINGS = [
        Binding("j", "scroll_down", show=False),
        Binding("k", "scroll_up", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("ctrl+f", "page_down", show=False),
        Binding("ctrl+b", "page_up", show=False),
        # VerticalScroll grabs ←/→ for horizontal scroll (a no-op here);
        # reroute them to pane navigation instead
        Binding("left", "app.focus_left", show=False),
        Binding("right", "app.focus_right", show=False),
    ]


class FilterInput(Input):
    BINDINGS = [Binding("escape", "dismiss_filter", show=False)]

    def action_dismiss_filter(self) -> None:
        self.value = ""
        self.remove_class("visible")
        self.app.query_one("#issues").focus()


class Splitter(Static):
    """A 1-cell drag handle between panels; drag to resize, double-click to reset."""

    can_focus = False
    ALLOW_SELECT = False  # a drag here resizes; it must not start text selection

    def __init__(
        self,
        target: str,
        invert: bool = False,
        min_width: int = 16,
        max_width: int = 100,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._target = target
        self._invert = invert
        self._min = min_width
        self._max = max_width
        self._drag_x: int | None = None
        self._start_w: int = 0

    def on_mouse_down(self, event) -> None:
        self._drag_x = event.screen_x
        self._start_w = self.app.query_one(self._target).outer_size.width
        self.capture_mouse()
        self.add_class("dragging")

    def on_mouse_move(self, event) -> None:
        if self._drag_x is None:
            return
        delta = event.screen_x - self._drag_x
        if self._invert:
            delta = -delta
        cap = min(self._max, self.app.size.width - 50)
        width = max(self._min, min(self._start_w + delta, cap))
        self.app.query_one(self._target).styles.width = width

    def on_mouse_up(self, event) -> None:
        if self._drag_x is None:
            return
        self._drag_x = None
        self.release_mouse()
        self.remove_class("dragging")
        save_layout = getattr(self.app, "_save_layout", None)
        if save_layout is not None:
            save_layout()

    def on_click(self, event) -> None:
        if getattr(event, "chain", 1) == 2:  # double-click: back to default width
            self.app.query_one(self._target).styles.width = None
            save_layout = getattr(self.app, "_save_layout", None)
            if save_layout is not None:
                save_layout(reset=self._target)


class PickerModal(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, title: str, options: list[Option]) -> None:
        super().__init__()
        self._title = title
        self._options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Static(self._title, id="picker-title")
            yield NavList(*self._options, id="picker-list")

    def on_mount(self) -> None:
        pop_in(self.query_one("#picker-box"))
        self.query_one("#picker-list").focus()

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class CommentModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("ctrl+s", "submit", show=False),
    ]

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="comment-box"):
            yield Static(self._title, id="comment-title")
            yield TextArea(id="comment-input")
            with Horizontal(id="comment-actions"):
                yield Static(
                    f"[{C_DIM}]ctrl+s to send · esc to cancel[/]", id="comment-hint"
                )
                yield Button("cancel", id="comment-cancel")
                yield Button(" comment", variant="primary", id="comment-send")

    def on_mount(self) -> None:
        pop_in(self.query_one("#comment-box"))
        self.query_one("#comment-input").focus()

    @on(Button.Pressed, "#comment-send")
    def _send(self) -> None:
        self.action_submit()

    @on(Button.Pressed, "#comment-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        text = self.query_one("#comment-input", TextArea).text.strip()
        self.dismiss(text or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class NewTicketModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("ctrl+s", "submit", show=False),
    ]

    def __init__(self, heading: str) -> None:
        super().__init__()
        self._heading = heading

    def compose(self) -> ComposeResult:
        with Vertical(id="ticket-box"):
            yield Static(self._heading, id="ticket-heading")
            yield Input(placeholder="title", id="ticket-title")
            yield TextArea(id="ticket-desc")
            with Horizontal(id="ticket-actions"):
                yield Static(
                    f"[{C_DIM}]description is optional · ctrl+s to create · esc to cancel[/]",
                    id="ticket-hint",
                )
                yield Button("cancel", id="ticket-cancel")
                yield Button(" create", variant="primary", id="ticket-create")

    def on_mount(self) -> None:
        pop_in(self.query_one("#ticket-box"))
        self.query_one("#ticket-title").focus()

    @on(Input.Submitted, "#ticket-title")
    def _title_done(self) -> None:
        self.query_one("#ticket-desc").focus()

    @on(Button.Pressed, "#ticket-create")
    def _create(self) -> None:
        self.action_submit()

    @on(Button.Pressed, "#ticket-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        title = self.query_one("#ticket-title", Input).value.strip()
        if not title:
            self.app.notify("a title is required", severity="warning")
            self.query_one("#ticket-title").focus()
            return
        desc = self.query_one("#ticket-desc", TextArea).text.strip()
        self.dismiss((title, desc or None))

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── app ───────────────────────────────────────────────────────────────────
class OnboardModal(ModalScreen):
    """First-run setup: paste a Linear API key, validate it live, save it."""

    BINDINGS = [Binding("escape", "quit_app", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="onboard-box"):
            yield Static(
                f"[bold {C_BLUE}]\uf022  welcome to ltui[/]", id="onboard-title"
            )
            yield Static(
                f"[{C_SUB}]ltui talks to Linear with a personal API key.[/]\n\n"
                f"[{C_DIM}]1.[/] [{C_SUB}]open[/] "
                f"[@click=screen.open_keys][{C_BLUE}]linear.app/settings/api[/][/] "
                f"[{C_DIM}](click it)[/]\n"
                f"[{C_DIM}]2.[/] [{C_SUB}]create a personal API key[/]\n"
                f"[{C_DIM}]3.[/] [{C_SUB}]paste it below and hit enter[/]",
                id="onboard-body",
            )
            yield Input(placeholder="lin_api_\u2026", password=True, id="onboard-key")
            yield Static("", id="onboard-status")
            with Horizontal(id="onboard-actions"):
                yield Static(
                    f"[{C_VFAINT}]saved to ~/.config/ltui/config.toml\n"
                    f"also works: LINEAR_API_KEY env, linear-cli auth[/]",
                    id="onboard-hint",
                )
                yield Button("\uf1e6 connect", variant="primary", id="onboard-connect")

    def on_mount(self) -> None:
        pop_in(self.query_one("#onboard-box"))
        self.query_one("#onboard-key").focus()

    def action_open_keys(self) -> None:
        webbrowser.open("https://linear.app/settings/api")

    def action_quit_app(self) -> None:
        self.app.exit()

    @on(Input.Submitted, "#onboard-key")
    def _submitted(self) -> None:
        self._connect()

    @on(Button.Pressed, "#onboard-connect")
    def _pressed(self) -> None:
        self._connect()

    @work(exclusive=True, group="verify")
    async def _connect(self) -> None:
        status = self.query_one("#onboard-status", Static)
        key = self.query_one("#onboard-key", Input).value.strip()
        if not key:
            status.update(f"[{C_PEACH}]paste a key first[/]")
            return
        status.update(f"[{C_DIM}]\uf017 checking\u2026[/]")
        try:
            who = await verify_key(key)
        except Exception as e:
            status.update(f"[{C_RED}]\uf057 {escape(str(e))}[/]")
            return
        status.update(f"[{C_GREEN}]\uf058 connected \u2014 {escape(who)}[/]")
        self.dismiss(key)


class ThemeModal(ModalScreen):
    """Theme picker — highlighting a theme previews it live."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-box"):
            yield Static("theme \u00b7 scroll to preview", id="theme-title")
            yield NavList(id="theme-list")

    def _row(self, name: str, active: str) -> Option:
        row = Text("  ")
        row.append("\u25cf " if name == active else "\u25cb ", style=C_BLUE if name == active else C_DIM)
        row.append(name, style=C_TEXT if name == active else C_SUB)
        return Option(row, id=name)

    def on_mount(self) -> None:
        pop_in(self.query_one("#theme-box"))
        app = self.app
        self._original = app.theme
        ol = self.query_one("#theme-list", NavList)
        opts = [Option(Text(" ltui", style=f"bold {C_SUB}"), disabled=True)]
        index_of = {}
        for name in THEME_NAMES:
            index_of[name] = len(opts)
            opts.append(self._row(name, self._original))
        extra = sorted(n for n in app.available_themes if n not in THEME_NAMES)
        if extra:
            opts.append(Option(Text(" "), disabled=True))
            opts.append(Option(Text(" textual", style=f"bold {C_SUB}"), disabled=True))
            for name in extra:
                index_of[name] = len(opts)
                opts.append(self._row(name, self._original))
        ol.add_options(opts)
        ol.highlighted = index_of.get(self._original, 1)
        ol.focus()

    @on(OptionList.OptionHighlighted, "#theme-list")
    def _preview(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self.app.theme = event.option.id

    @on(OptionList.OptionSelected, "#theme-list")
    def _select(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.app.theme = event.option.id
        self.dismiss(True)
        self.app._save_state()

    def action_cancel(self) -> None:
        self.app.theme = self._original
        self.dismiss(False)


class LabelsModal(ModalScreen):
    """Multi-select label editor: enter toggles, ctrl+s applies."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("ctrl+s", "apply", show=False),
    ]

    def __init__(self, title: str, labels: list[dict], selected: set[str]) -> None:
        super().__init__()
        self._title = title
        self._labels = labels
        self._sel = set(selected)

    def compose(self) -> ComposeResult:
        with Vertical(id="labels-box"):
            yield Static(self._title, id="labels-title")
            yield NavList(id="labels-list")
            with Horizontal(id="labels-actions"):
                yield Static(
                    f"[{C_DIM}]enter toggles \u00b7 ctrl+s applies \u00b7 esc cancels[/]",
                    id="labels-hint",
                )
                yield Button("cancel", id="labels-cancel")
                yield Button("\uf00c apply", variant="primary", id="labels-apply")

    def on_mount(self) -> None:
        pop_in(self.query_one("#labels-box"))
        self._build()
        self.query_one("#labels-list").focus()

    def _build(self) -> None:
        ol = self.query_one("#labels-list", NavList)
        prev = ol.highlighted
        ol.clear_options()
        opts = []
        for lb in self._labels:
            row = Text(no_wrap=True, overflow="ellipsis")
            on_it = lb["id"] in self._sel
            row.append("\uf00c " if on_it else "  ", style=C_GREEN)
            if not on_it:
                row.append(" ")
            row.append("\u25cf ", style=lb.get("color") or C_DIM)
            row.append(lb["name"], style=C_TEXT if on_it else C_SUB)
            opts.append(Option(row, id=lb["id"]))
        ol.add_options(opts)
        ol.highlighted = prev if prev is not None else 0

    @on(OptionList.OptionSelected, "#labels-list")
    def _toggle(self, event: OptionList.OptionSelected) -> None:
        lid = event.option.id
        if lid in self._sel:
            self._sel.discard(lid)
        else:
            self._sel.add(lid)
        self._build()

    @on(Button.Pressed, "#labels-apply")
    def _apply_btn(self) -> None:
        self.action_apply()

    @on(Button.Pressed, "#labels-cancel")
    def _cancel_btn(self) -> None:
        self.dismiss(None)

    def action_apply(self) -> None:
        self.dismiss(sorted(self._sel))

    def action_cancel(self) -> None:
        self.dismiss(None)


class StatusFilterModal(ModalScreen):
    """Multi-select workflow-type view with Active and Everything presets."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("ctrl+s", "apply", show=False),
    ]

    def __init__(self, view: StatusView) -> None:
        super().__init__()
        self._original = view
        self._sel = {
            state_type
            for state_type in KNOWN_STATUS_TYPES
            if status_view_matches(view, state_type)
        }
        self._initial_sel = set(self._sel)

    def compose(self) -> ComposeResult:
        with Vertical(id="status-box"):
            yield Static("status view", id="status-title")
            yield NavList(id="status-list")
            with Horizontal(id="status-actions"):
                yield Static(
                    f"[{C_DIM}]enter toggles · ctrl+s applies · esc cancels[/]",
                    id="status-hint",
                )
                yield Button("cancel", id="status-cancel")
                yield Button("\uf00c apply", variant="primary", id="status-apply")

    def on_mount(self) -> None:
        pop_in(self.query_one("#status-box"))
        self._build()
        self.query_one("#status-list").focus()

    def _build(self) -> None:
        ol = self.query_one("#status-list", NavList)
        previous = ol.highlighted
        ol.clear_options()
        options = []
        for option_id, label, selected in (
            ("preset:active", "Active", self._sel == set(ACTIVE_STATUS_TYPES)),
            ("preset:all", "Everything", self._sel == set(KNOWN_STATUS_TYPES)),
        ):
            row = Text("\uf0b0 ", style=C_BLUE)
            row.append(label, style=C_TEXT)
            if selected:
                row.append("  \uf00c", style=C_GREEN)
            options.append(Option(row, id=option_id))
        options.append(Option(Text(" "), disabled=True))
        for state_type in KNOWN_STATUS_TYPES:
            selected = state_type in self._sel
            row = Text("\uf00c " if selected else "   ", style=C_GREEN)
            row.append(
                STATUS_TYPE_LABELS[state_type],
                style=C_TEXT if selected else C_SUB,
            )
            options.append(Option(row, id=f"type:{state_type}"))
        ol.add_options(options)
        ol.highlighted = previous if previous is not None else 0

    @on(OptionList.OptionSelected, "#status-list")
    def _toggle(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id or ""
        if option_id == "preset:active":
            self._sel = set(ACTIVE_STATUS_TYPES)
        elif option_id == "preset:all":
            self._sel = set(KNOWN_STATUS_TYPES)
        elif option_id.startswith("type:"):
            state_type = option_id.removeprefix("type:")
            if state_type in self._sel:
                self._sel.remove(state_type)
            else:
                self._sel.add(state_type)
        self._build()

    @on(Button.Pressed, "#status-apply")
    def _apply_button(self) -> None:
        self.action_apply()

    @on(Button.Pressed, "#status-cancel")
    def _cancel_button(self) -> None:
        self.dismiss(None)

    def action_apply(self) -> None:
        if not self._sel:
            self.app.notify("select at least one status type", severity="warning")
            return
        if self._sel == self._initial_sel:
            view = self._original
        elif self._sel == set(KNOWN_STATUS_TYPES):
            view = EVERYTHING_STATUS_VIEW
        else:
            view = StatusView("include", frozenset(self._sel))
        self.dismiss(view)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ProjectNameModal(ModalScreen):
    """One-field prompt for a new project name."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="projname-box"):
            yield Static(
                f"[bold {C_SUB}]\uf07b new project[/]", id="projname-title"
            )
            yield Input(placeholder="project name", id="projname-input")
            yield Static(
                f"[{C_DIM}]enter creates \u00b7 esc cancels[/]", id="projname-hint"
            )

    def on_mount(self) -> None:
        pop_in(self.query_one("#projname-box"))
        self.query_one("#projname-input").focus()

    @on(Input.Submitted, "#projname-input")
    def _submit(self) -> None:
        name = self.query_one("#projname-input", Input).value.strip()
        if name:
            self.dismiss(name)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SettingsModal(ModalScreen):
    BINDINGS = [Binding("escape", "close_modal", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-box"):
            yield Static(id="settings-profile")
            yield NavList(id="settings-list")
            yield Static(id="settings-foot")

    def on_mount(self) -> None:
        pop_in(self.query_one("#settings-box"))
        app = self.app
        profile = Text()
        profile.append(" ", style=C_BLUE)
        profile.append(getattr(app, "_viewer_name", None) or "…", style=f"bold {C_TEXT}")
        org = getattr(app, "_org", None)
        if org:
            profile.append(f"  ·  {org}", style=C_DIM)
        self.query_one("#settings-profile", Static).update(profile)
        foot = Text()
        foot.append(f"ltui {__version__}", style=C_DIM)
        workspace = getattr(app, "_active_profile", None) or "default"
        cache_hint = (
            "all workspace caches"
            if workspace == ALL_WORKSPACES
            else f"cache ~/.cache/ltui/{workspace}"
        )
        foot.append(f"  ·  {cache_hint}", style=C_VFAINT)
        self.query_one("#settings-foot", Static).update(foot)
        self._build()
        self.query_one("#settings-list").focus()

    def _build(self) -> None:
        app = self.app
        ol = self.query_one("#settings-list", NavList)
        prev = ol.highlighted
        ol.clear_options()
        opts: list[Option] = [
            Option(Text(" preferences", style=f"bold {C_SUB}"), disabled=True)
        ]
        workspace = getattr(app, "_active_profile", None)
        resolution = getattr(app, "_profile_resolution", None)
        if workspace and resolution is not None:
            label = (
                "All workspaces"
                if workspace == ALL_WORKSPACES
                else resolution.profile(workspace).label
            )
            row = Text("   ")
            row.append("◆ ", style=C_BLUE)
            row.append(f"workspace  {label}", style=C_TEXT)
            opts.append(Option(row, id="workspace:switch"))
        status_view = getattr(app, "_status_view", DEFAULT_STATUS_VIEW)
        row = Text("   ")
        row.append("\uf0b0 ", style=C_BLUE)
        row.append(
            f"status view  {status_view_label(status_view)}", style=C_TEXT
        )
        opts.append(Option(row, id="view:status"))
        cycle_label = app._cycle_view_label()
        row = Text("   ")
        row.append("\uf021 ", style=C_MAUVE)
        row.append(f"cycle view  {cycle_label}", style=C_TEXT)
        opts.append(Option(row, id="view:cycle"))
        mine = getattr(app, "_mine", False)
        row = Text("   ")
        row.append("● " if mine else "○ ", style=C_GREEN if mine else C_DIM)
        row.append("mine only", style=C_TEXT if mine else C_SUB)
        opts.append(Option(row, id="pref:mine"))
        opts.append(Option(Text(" "), disabled=True))
        opts.append(Option(Text(" maintenance", style=f"bold {C_SUB}"), disabled=True))
        cache_label = "clear all caches" if workspace == ALL_WORKSPACES else "clear cache"
        opts.append(Option(Text(f"    {cache_label}", style=C_SUB), id="cache:clear"))
        ol.add_options(opts)
        ol.highlighted = prev if prev is not None else 1

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        app = self.app
        oid = event.option.id or ""
        if oid == "workspace:switch":
            self.dismiss(None)
            app.call_later(app.action_switch_workspace)
            return
        elif oid == "view:status":
            self.dismiss(None)
            app.call_later(app.action_filter_status)
            return
        elif oid == "view:cycle":
            self.dismiss(None)
            app.call_later(app.action_pick_cycle)
            return
        elif oid == "pref:mine":
            app.action_toggle_mine()
        elif oid == "cache:clear":
            count = app._clear_active_cache()
            app.notify(f" cleared {count} cached file(s)")
        self._build()

    def action_close_modal(self) -> None:
        self.dismiss(None)


class HelpModal(ModalScreen):
    """Keybinding cheatsheet — press ? anywhere."""

    BINDINGS = [
        Binding("escape", "close_modal", show=False),
        Binding("question_mark", "close_modal", show=False),
        # screen-level binding wins over the app's q → quit while open
        Binding("q", "close_modal", show=False),
    ]

    SECTIONS = [
        ("navigate", [
            ("ctrl+d / ctrl+u", "half page down / up"),
            ("[ / ]", "previous / next group"),
            (":", "command palette"),
            ("j/k ↑↓", "move around lists and the detail panel"),
            ("← / →", "switch panes — → on a ticket opens it"),
            ("g / G", "jump to top / bottom"),
            ("enter", "open ticket detail (click works too)"),
            ("esc", "close panel · dismiss modal · clear filter"),
        ]),
        ("ticket", [
            ("n", "new ticket (choose workspace in All)"),
            ("s", "change status"),
            ("p", "change priority"),
            ("l", "edit labels"),
            ("P", "move to a project (or create one)"),
            ("a", "change assignee (or unassign)"),
            ("c", "add a comment (ctrl+s to send)"),
            ("y", "yank — copy branch / url / identifier"),
            ("o", "open in browser"),
        ]),
        ("view", [
            ("/", "filter issues"),
            ("F", "choose visible status types"),
            ("d", "toggle Done issues"),
            ("C", "choose a cycle view"),
            ("w", "switch workspace / All view"),
            ("m", "toggle mine only"),
            ("v", "group by workspace / status / project"),
            ("V", "filter to a single project"),
            ("t", "cycle theme"),
            (",", "settings"),
            ("r", "refresh"),
        ]),
        ("app", [
            ("?", "this help"),
            ("ctrl+p", "command palette"),
            ("q", "quit"),
        ]),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static(id="help-title")
            yield Static(id="help-body")
            yield Static(id="help-foot")

    def on_mount(self) -> None:
        pop_in(self.query_one("#help-box"))
        title = Text()
        title.append("\uf11c ", style=C_BLUE)
        title.append("keys", style=f"bold {C_TEXT}")
        self.query_one("#help-title", Static).update(title)
        key_w = max(len(k) for _, rows in self.SECTIONS for k, _ in rows) + 3
        body = Text()
        for section, rows in self.SECTIONS:
            if body:
                body.append("\n")
            body.append(f" {section}\n", style=f"bold {C_DIM}")
            for key, desc in rows:
                body.append(f"   {key.ljust(key_w)}", style=C_BLUE)
                body.append(f"{desc}\n", style=C_SUB)
        body.rstrip()
        self.query_one("#help-body", Static).update(body)
        self.query_one("#help-foot", Static).update(
            Text("? · esc · q to close", style=C_VFAINT)
        )

    def action_close_modal(self) -> None:
        self.dismiss(None)


class WelcomeModal(ModalScreen):
    """One-time first-launch tour — dismissing marks the user as welcomed."""

    BINDINGS = [
        Binding("escape", "close_modal", show=False),
        Binding("enter", "close_modal", show=False),
        Binding("question_mark", "close_to_help", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="welcome-box"):
            yield Static(
                f"[bold {C_BLUE}]\uf005  welcome to ltui[/]", id="welcome-title"
            )
            yield Static(
                f"[{C_SUB}]you're in — your issues are loading right now.[/]\n\n"
                f"[{C_BLUE}]enter[/] [{C_SUB}]opens a ticket ·[/] "
                f"[{C_BLUE}]n[/] [{C_SUB}]creates one[/]\n"
                f"[{C_BLUE}]s[/] [{C_DIM}]/[/] [{C_BLUE}]a[/] [{C_DIM}]/[/] [{C_BLUE}]c[/] "
                f"[{C_SUB}]— status, assignee, comment[/]\n"
                f"[{C_BLUE}]m[/] [{C_SUB}]shows only yours ·[/] "
                f"[{C_BLUE}]/[/] [{C_SUB}]filters the list[/]\n\n"
                f"[{C_SUB}]and[/] [{C_BLUE}]?[/] [{C_SUB}]anytime for everything else.[/]",
                id="welcome-body",
            )
            with Horizontal(id="welcome-actions"):
                yield Static(f"[{C_DIM}]esc to close[/]", id="welcome-hint")
                yield Button("got it", variant="primary", id="welcome-ok")

    def on_mount(self) -> None:
        pop_in(self.query_one("#welcome-box"))
        self.query_one("#welcome-ok").focus()

    @on(Button.Pressed, "#welcome-ok")
    def _ok(self) -> None:
        self.dismiss(None)

    def action_close_modal(self) -> None:
        self.dismiss(None)

    def action_close_to_help(self) -> None:
        app = self.app
        self.dismiss(None)
        app.call_later(app.action_help)


def hint_markup() -> str:
    return (
        f"[@click=app.change_status][{C_BLUE}]s[/] [{C_DIM}]status[/][/]  "
        f"[@click=app.change_priority][{C_BLUE}]p[/] [{C_DIM}]priority[/][/]  "
        f"[@click=app.add_comment][{C_BLUE}]c[/] [{C_DIM}]comment[/][/]  "
        f"[@click=app.open_browser][{C_BLUE}]o[/] [{C_DIM}]browser[/][/]  "
        f"[@click=app.yank][{C_BLUE}]y[/] [{C_DIM}]yank[/][/]  "
        f"[@click=app.back][{C_BLUE}]esc[/] [{C_DIM}]close[/][/]"
    )


class LTUI(App):
    TITLE = "ltui"

    BINDINGS = build_bindings()

    CSS = f"""
    #appheader {{ height: 1; padding: 0 2; }}
    #main {{ height: 1fr; }}

    #main {{ padding: 0 1 0 0; }}
    #sidebar {{ width: 24; margin: 0 0 0 1; }}
    #split-left, #split-right {{ width: 1; height: 1fr; }}
    #split-left:hover, #split-right:hover,
    #split-left.dragging, #split-right.dragging {{ background: $ltui-border; }}
    #split-right {{ display: none; }}
    #split-right.open {{ display: block; }}
    #teams {{
        height: 1fr;
        border: round $ltui-border; border-title-color: {C_SUB};
    }}
    #teams:focus {{ border: round $ltui-border-focus; border-title-color: $ltui-border-focus; }}
    #profile {{
        height: auto; padding: 0 1;
        border: round $ltui-border; border-title-color: {C_SUB};
    }}

    #centre {{
        width: 1fr;
        border: round $ltui-border;
        border-title-color: {C_TEXT}; border-subtitle-color: {C_DIM};
    }}
    #centre:focus-within {{ border: round $ltui-border-focus; }}

    #detail {{
        display: none; width: 46%; min-width: 44;
        border: round $ltui-border;
        border-title-color: $ltui-border-detail; border-subtitle-color: {C_DIM};
    }}
    #detail.open {{ display: block; }}
    #detail:focus-within {{ border: round $ltui-border-detail; }}

    OptionList {{
        background: transparent; border: none; padding: 0 1;
        scrollbar-size-vertical: 1;
    }}
    OptionList:focus {{ background: transparent; border: none; }}
    OptionList > .option-list--option-highlighted {{ background: $ltui-cursor; }}
    OptionList:focus > .option-list--option-highlighted {{ background: $ltui-cursor; }}

    CommandPalette {{ background: $ltui-overlay; }}
    CommandPalette > Vertical {{ width: 70; max-width: 85%; }}
    CommandPalette #--input {{ background: $ltui-modal-bg; }}
    CommandPalette CommandList {{ background: $ltui-modal-bg; }}

    #filter {{ display: none; height: 3; border: round $ltui-border; background: transparent; }}
    #filter.visible {{ display: block; }}
    #filter:focus {{ border: round $ltui-border-focus; }}

    #d-title {{ padding: 1 1 0 1; }}
    #d-meta {{ padding: 1 1 0 1; }}
    #d-scroll {{ height: 1fr; margin: 1 0 0 0; scrollbar-size-vertical: 1; }}
    #d-parent {{ display: none; height: auto; padding: 0 1; margin: 0 0 1 0; }}
    #d-parent.visible {{ display: block; }}
    #d-children {{ display: none; height: auto; padding: 0 1; margin: 0 0 1 0; }}
    #d-children.visible {{ display: block; }}
    #d-desc {{ background: transparent; padding: 0 1; }}
    Markdown {{ background: transparent; }}
    #d-comments-head {{ padding: 1 1 0 1; }}
    #d-comments {{ height: auto; }}
    .comment {{
        height: auto; border-left: thick {C_VFAINT};
        padding: 0 1; margin: 1 1 0 1;
    }}
    .comment-meta {{ height: auto; }}
    .comment Markdown {{ padding: 0; margin: 0; }}
    #d-hint {{ height: 1; padding: 0 1; margin: 1 0 0 0; }}

    PickerModal {{ align: center middle; background: $ltui-overlay; }}
    #picker-box {{
        width: 44; height: auto; max-height: 80%;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 1;
    }}
    #picker-title {{ padding: 0 1 1 1; color: {C_SUB}; text-style: bold; }}
    #picker-list {{ height: auto; max-height: 14; }}

    CommentModal {{ align: center middle; background: $ltui-overlay; }}
    LabelsModal {{ align: center middle; background: $ltui-overlay; }}
    #labels-box {{
        width: 46; height: auto; max-height: 80%;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 1;
    }}
    #labels-title {{ padding: 0 1 1 1; color: {C_SUB}; text-style: bold; }}
    #labels-list {{ height: auto; max-height: 14; }}
    #labels-actions {{ height: 3; margin: 1 0 0 0; }}
    #labels-hint {{ width: 1fr; padding: 1 1; }}
    #labels-actions Button {{ margin: 0 0 0 1; min-width: 9; }}

    StatusFilterModal {{ align: center middle; background: $ltui-overlay; }}
    #status-box {{
        width: 48; height: auto; max-height: 90%;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 1;
    }}
    #status-title {{ padding: 0 1 1 1; color: {C_SUB}; text-style: bold; }}
    #status-list {{ height: auto; max-height: 18; }}
    #status-actions {{ height: 3; margin: 1 0 0 0; }}
    #status-hint {{ width: 1fr; padding: 1 1; }}
    #status-actions Button {{ margin: 0 0 0 1; min-width: 9; }}

    ProjectNameModal {{ align: center middle; background: $ltui-overlay; }}
    #projname-box {{
        width: 52; height: auto;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 2;
    }}
    #projname-title {{ padding: 0 0 1 0; }}
    #projname-input {{ border: round {C_VFAINT}; background: transparent; }}
    #projname-input:focus {{ border: round {C_FAINT}; }}
    #projname-hint {{ padding: 1 0 0 0; }}

    #comment-box {{
        width: 72; height: 20;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 2;
    }}
    #comment-title {{ color: {C_SUB}; text-style: bold; padding: 0 0 1 0; }}
    #comment-input {{ height: 1fr; border: round {C_VFAINT}; background: transparent; }}
    #comment-input:focus {{ border: round {C_FAINT}; }}
    #comment-actions {{ height: 3; margin: 1 0 0 0; }}
    #comment-hint {{ width: 1fr; padding: 1 0; }}
    #comment-actions Button {{ margin: 0 0 0 2; min-width: 10; }}

    NewTicketModal {{ align: center middle; background: $ltui-overlay; }}
    #ticket-box {{
        width: 72; height: 24;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 2;
    }}
    #ticket-heading {{ color: {C_SUB}; text-style: bold; padding: 0 0 1 0; }}
    #ticket-title {{ border: round {C_VFAINT}; background: transparent; }}
    #ticket-title:focus {{ border: round {C_FAINT}; }}
    #ticket-desc {{ height: 1fr; margin: 1 0 0 0; border: round {C_VFAINT}; background: transparent; }}
    #ticket-desc:focus {{ border: round {C_FAINT}; }}
    #ticket-actions {{ height: 3; margin: 1 0 0 0; }}
    #ticket-hint {{ width: 1fr; padding: 1 0; }}
    #ticket-actions Button {{ margin: 0 0 0 2; min-width: 10; }}

    OnboardModal {{ align: center middle; background: $ltui-overlay; }}
    #onboard-box {{
        width: 62; height: auto;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 2;
    }}
    #onboard-title {{ padding: 0 0 1 0; }}
    #onboard-body {{ padding: 0 0 1 0; }}
    #onboard-key {{ border: round {C_VFAINT}; background: transparent; }}
    #onboard-key:focus {{ border: round {C_FAINT}; }}
    #onboard-status {{ height: 1; padding: 0 1; margin: 1 0 0 0; }}
    #onboard-actions {{ height: 3; margin: 1 0 0 0; }}
    #onboard-hint {{ width: 1fr; }}
    #onboard-actions Button {{ margin: 0 0 0 2; min-width: 12; }}

    ThemeModal {{ align: center middle; background: $ltui-overlay; }}
    #theme-box {{
        width: 40; height: auto; max-height: 85%;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 1;
    }}
    #theme-title {{ padding: 0 1 1 1; color: {C_SUB}; text-style: bold; }}
    #theme-list {{ height: auto; max-height: 18; }}

    SettingsModal {{ align: center middle; background: $ltui-overlay; }}
    #settings-box {{
        width: 42; height: auto; max-height: 85%;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 1;
    }}
    #settings-profile {{ padding: 0 1 1 1; }}
    #settings-list {{ height: auto; max-height: 20; }}
    #settings-foot {{ padding: 1 1 0 1; }}

    HelpModal {{ align: center middle; background: $ltui-overlay; }}
    #help-box {{
        width: 64; height: auto; max-height: 90%;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 2;
    }}
    #help-title {{ padding: 0 1 1 1; }}
    #help-body {{ height: auto; }}
    #help-foot {{ padding: 1 1 0 1; }}

    WelcomeModal {{ align: center middle; background: $ltui-overlay; }}
    #welcome-box {{
        width: 56; height: auto;
        background: $ltui-modal-bg; border: round $ltui-border-focus; padding: 1 2;
    }}
    #welcome-title {{ padding: 0 0 1 0; }}
    #welcome-body {{ padding: 0 0 1 0; }}
    #welcome-actions {{ height: 3; }}
    #welcome-hint {{ width: 1fr; padding: 1 0; }}
    #welcome-actions Button {{ margin: 0 0 0 2; min-width: 10; }}
    """

    def __init__(
        self,
        profile_resolution: ProfileResolution | None = None,
        storage: StoragePaths = DEFAULT_STORAGE,
        client_factory=None,
    ) -> None:
        super().__init__()
        self._storage = storage
        self._profile_resolution = profile_resolution
        self._active_profile: str | None = (
            profile_resolution.active if profile_resolution is not None else None
        )
        self._client_factory = client_factory
        self._switching = False
        self.client: httpx.AsyncClient | None = None
        self._teams: list[dict] = []
        self._issues: list[dict] = []
        self._states: list[dict] = []
        self._cycles: list[dict] = []
        self._cycles_complete = False
        self._members: dict[str, list] = {}
        self._team_labels: dict[str, list] = {}
        self._team_projects: dict[str, list] = {}
        self._workspace_states: dict[str, list[dict]] = {}
        self._workspace_cycles: dict[str, list[dict]] = {}
        self._workspace_cycles_complete: dict[str, bool] = {}
        self._workspace_viewers: dict[str, dict] = {}
        self._workspace_teams: dict[str, dict] = {}
        self._workspace_snapshots: dict[str, WorkspaceSnapshot] = {}
        self._aggregate_generation = 0
        self._team: dict | None = None
        self._viewer_id: str | None = None
        self._viewer_name: str | None = None
        self._boot_data: dict | None = None
        self._org: str | None = None
        self._mine = False
        self._group_by = "status"
        self._status_view = DEFAULT_STATUS_VIEW
        self._cycle_view = DEFAULT_CYCLE_VIEW
        self._filter = ""
        self._project_filter: str | None = None  # project id, "" = no-project
        self._detail_issue: dict | None = None
        self._wave_pos = -1
        self._wave_rest = 0
        self._refreshing = False
        self._spin_frame = 0
        self._opt_index: dict[str, int] = {}
        self._issue_by_id: dict[str, dict] = {}
        self._header_indices: list[int] = []
        self._group_starts: list[int] = []

    @property
    def active_workspace(self) -> str:
        if self._active_profile is None:
            raise RuntimeError("no active workspace")
        return self._active_profile

    def _profile(self, name: str | None = None) -> WorkspaceProfile:
        if self._profile_resolution is None:
            raise RuntimeError("workspace profiles have not been loaded")
        return self._profile_resolution.profile(name or self.active_workspace)

    @property
    def _is_all_workspaces(self) -> bool:
        return self._active_profile == ALL_WORKSPACES

    def _issue_workspace(self, issue: dict) -> str:
        return issue.get("_workspace") or self.active_workspace

    def _team_workspace(self, team: dict) -> str:
        return team.get("_workspace") or self.active_workspace

    def _issue_key(self, issue: dict) -> str:
        workspace = issue.get("_workspace")
        return scoped_id(workspace, issue["id"]) if workspace else issue["id"]

    def _team_key(self, team: dict) -> str:
        workspace = team.get("_workspace")
        return scoped_id(workspace, team["id"]) if workspace else team["id"]

    def _team_for_issue(self, issue: dict) -> dict | None:
        workspace = self._issue_workspace(issue)
        if self._is_all_workspaces:
            return self._workspace_teams.get(workspace)
        return self._team

    def _states_for_issue(self, issue: dict) -> list[dict]:
        if self._is_all_workspaces:
            return self._workspace_states.get(self._issue_workspace(issue), [])
        return self._states

    def _available_cycles(self) -> list[tuple[str, dict, dict]]:
        available = []
        if self._is_all_workspaces:
            for profile in self._profile_resolution.profiles:
                team = self._workspace_teams.get(profile.name)
                if team is None:
                    continue
                for cycle in sorted(
                    self._workspace_cycles.get(profile.name, []),
                    key=cycle_sort_key,
                ):
                    available.append((profile.name, team, cycle))
            return available
        if self._team is None:
            return available
        return [
            (self.active_workspace, self._team, cycle)
            for cycle in sorted(self._cycles, key=cycle_sort_key)
        ]

    def _cycle_view_label(self) -> str:
        labels = {
            "all": "All cycles",
            "current": "Current",
            "next": "Next",
            "previous": "Previous",
            "none": "No cycle",
        }
        if self._cycle_view.mode != "named":
            return labels.get(self._cycle_view.mode, "All cycles")
        for workspace, _team, cycle in self._available_cycles():
            if (
                workspace == self._cycle_view.workspace
                and cycle.get("id") == self._cycle_view.cycle_id
            ):
                name = cycle_name(cycle)
                if self._is_all_workspaces:
                    return f"{self._workspace_label(workspace)} · {name}"
                return name
        return "Selected cycle"

    def _validate_named_cycle_for_team(
        self,
        workspace: str,
        team_id: str,
        cycles: list[dict],
        cycles_complete: bool,
    ) -> bool:
        view = self._cycle_view
        if view.mode != "named":
            return False
        wrong_team = view.workspace != workspace or view.team_id != team_id
        missing_from_complete = cycles_complete and not any(
            cycle.get("id") == view.cycle_id for cycle in cycles
        )
        if not wrong_team and not missing_from_complete:
            return False
        self._cycle_view = DEFAULT_CYCLE_VIEW
        self._save_state()
        return True

    def _load_profile_state(self) -> dict:
        if self._active_profile is None:
            return {}
        allow_legacy = bool(
            self._profile_resolution
            and self._profile_resolution.allow_legacy_storage
        )
        return load_state(
            self._storage, self.active_workspace, allow_legacy=allow_legacy
        )

    def _clear_active_cache(self) -> int:
        if self._is_all_workspaces:
            return sum(
                clear_cache(self._storage, profile.name)
                for profile in self._profile_resolution.profiles
            )
        allow_legacy = bool(
            self._profile_resolution
            and self._profile_resolution.allow_legacy_storage
        )
        return clear_cache(
            self._storage,
            self.active_workspace,
            allow_legacy=allow_legacy,
        )

    def _apply_profile_preferences(self) -> None:
        state = self._load_profile_state()
        self._mine = bool(state.get("mine", False))
        self._status_view = status_view_from_state(state.get("status_view"))
        self._cycle_view = cycle_view_from_state(state.get("cycle_view"))
        group_by = state.get("group_by", "status")
        allowed_groups = (
            ("workspace", "status", "project")
            if self._is_all_workspaces
            else ("status", "project")
        )
        self._group_by = group_by if group_by in allowed_groups else allowed_groups[0]
        self._filter = ""
        self._project_filter = None
        saved_theme = state.get("theme")
        self.theme = (
            saved_theme if saved_theme in self.available_themes else THEME_NAMES[0]
        )
        sidebar = self.query_one("#sidebar")
        detail = self.query_one("#detail")
        sidebar.styles.width = int(state["sidebar_w"]) if state.get("sidebar_w") else None
        detail.styles.width = int(state["detail_w"]) if state.get("detail_w") else None

    def _make_client(self, key: str):
        return httpx.AsyncClient(
            headers={"Authorization": key, "Content-Type": "application/json"},
            timeout=20,
        )

    def _new_client(self, key: str):
        return (
            self._client_factory(key)
            if self._client_factory is not None
            else self._make_client(key)
        )

    def _on_theme_changed(self, _theme) -> None:
        # ansi-background themes (clear, ansi-dark, …) need ansi_color mode
        # so default-color codes pass through and the terminal bg shows
        set_palette(self.theme == "system")
        self.ansi_color = self._theme_is_ansi()
        if self._boot_data is not None:
            self._render_boot(self._boot_data)
        self._update_profile()
        try:
            self.query_one("#d-hint", Static).update(hint_markup())
        except Exception:
            pass
        if self._issues:
            self.render_issues()
        if self._detail_issue is not None:
            self.query_one("#d-title", Static).update(
                Text(self._detail_issue["title"], style=f"bold {C_TEXT}")
            )
            self._update_detail_meta(self._detail_issue)
        # persist every path (t, palette, picker) but not mid-preview;
        # ThemeModal commits or reverts on close
        if not isinstance(self.screen, ThemeModal):
            self._save_state()

    def _theme_is_ansi(self) -> bool:
        theme = self.available_themes.get(self.theme)
        if theme is None or theme.background is None:
            return False
        try:
            return TColor.parse(theme.background).ansi is not None
        except Exception:
            return False

    def get_css_variables(self) -> dict[str, str]:
        # ltui-* variables must exist even before our themes are registered
        # (the stylesheet is parsed while the default textual theme is active)
        variables = super().get_css_variables()
        theme = next((t for t in THEMES if t.name == self.theme), THEMES[0])
        for name, value in theme.variables.items():
            variables.setdefault(name, value)
        return variables

    # ── layout ────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Static(id="appheader")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield NavList(id="teams")
                yield Static(id="profile")
            yield Splitter("#sidebar", min_width=16, max_width=44, id="split-left")
            with Vertical(id="centre"):
                yield FilterInput(placeholder=" filter issues…", id="filter")
                yield NavList(id="issues")
            yield Splitter("#detail", invert=True, min_width=34, id="split-right")
            with Vertical(id="detail"):
                yield Static(id="d-title")
                yield Static(id="d-meta")
                with DetailScroll(id="d-scroll"):
                    yield Static(id="d-parent")
                    yield Vertical(id="d-children")
                    yield Markdown(id="d-desc")
                    yield Static(id="d-comments-head")
                    yield Vertical(id="d-comments")
                yield Static(hint_markup(), id="d-hint")
        yield Footer()

    def on_mount(self) -> None:
        for t in THEMES:
            self.register_theme(t)
        self.theme_changed_signal.subscribe(self, self._on_theme_changed)
        self.query_one("#teams").border_title = " teams "
        self.query_one("#profile").border_title = " you "
        self.query_one("#centre").border_title = " issues "
        self.set_interval(FX_TICK, self._tick_fx)
        refresh_s = CONFIG_OPTIONS.get("auto_refresh_seconds", AUTO_REFRESH_SECONDS)
        if isinstance(refresh_s, (int, float)) and refresh_s > 0:
            self.set_interval(refresh_s, self._auto_refresh_board)
        self.query_one("#issues").focus()
        try:
            if self._profile_resolution is None:
                self._profile_resolution = resolve_workspace_profiles(self._storage)
                self._active_profile = self._profile_resolution.active
        except CredentialsNotFound:
            def connected(new_key: str | None) -> None:
                if not new_key:
                    return
                try:
                    save_api_key(new_key, self._storage)
                    self._profile_resolution = resolve_workspace_profiles(
                        self._storage
                    )
                    self._active_profile = self._profile_resolution.active
                    self._apply_profile_preferences()
                except Exception as e:
                    self.notify(f"couldn't save key: {e}", severity="error")
                    return
                self._update_profile()
                self._start(self._profile().api_key)

            self.push_screen(OnboardModal(), connected)
            return
        except ProfileConfigError as error:
            self.theme = THEME_NAMES[0]
            self.ansi_color = self._theme_is_ansi()
            self._update_profile()
            self.notify(f"configuration error: {error}", severity="error", timeout=12)
            return
        self._apply_profile_preferences()
        self.ansi_color = self._theme_is_ansi()
        self._update_profile()
        if self._is_all_workspaces:
            self._start_all_workspaces()
        else:
            self._start(self._profile().api_key)

    def _start(self, key: str) -> None:
        self.client = self._new_client(key)
        # render instantly from cache, then refresh live data concurrently
        team = None
        allow_legacy = bool(
            self._profile_resolution
            and self._profile_resolution.allow_legacy_storage
        )
        if boot_cache := read_cache(
            self._storage,
            self.active_workspace,
            "boot",
            allow_legacy=allow_legacy,
        ):
            self._render_boot(boot_cache)
            last_id = self._load_profile_state().get("team_id")
            team = next((t for t in self._teams if t["id"] == last_id), None)
        if team is not None:
            self.query_one("#teams", NavList).highlighted = self._teams.index(team)
            self.load_team(team)
        self.boot(pick_team=team is None)
        # one-time tour; _start may run inside OnboardModal's dismiss callback
        # (screen still popping), so defer the push a tick
        if not self._load_profile_state().get("welcomed"):
            self.call_later(self._show_welcome)

    def _start_all_workspaces(self) -> None:
        self.client = None
        self._aggregate_generation += 1
        generation = self._aggregate_generation
        cached = {
            profile.name: snapshot
            for profile in self._profile_resolution.profiles
            if (snapshot := self._cached_workspace_snapshot(profile)) is not None
        }
        if cached:
            self._render_all_workspaces(cached)
        else:
            self.query_one("#issues", NavList).loading = True
        self.load_all_workspaces(generation, cached)
        if not self._load_profile_state().get("welcomed"):
            self.call_later(self._show_welcome)

    def _show_welcome(self) -> None:
        def done(_: object | None) -> None:
            data = self._load_profile_state()
            data["welcomed"] = True
            save_state(self._storage, self.active_workspace, data)

        self.push_screen(WelcomeModal(), done)

    async def on_unmount(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    # ── api ───────────────────────────────────────────────────────────
    async def gql(self, query: str, variables: dict | None = None) -> dict:
        if self._switching and query.lstrip().startswith("mutation"):
            raise RuntimeError("workspace switch in progress")
        if self.client is None:
            raise RuntimeError("Linear client is not connected")
        return await self._gql_client(self.client, query, variables)

    async def _gql_client(
        self, client, query: str, variables: dict | None = None
    ) -> dict:
        resp = await client.post(
            API_URL, json={"query": query, "variables": variables or {}}
        )
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(data["errors"][0].get("message", "GraphQL error"))
        return data["data"]

    async def _cancel_aggregate_refresh_for_mutation(self) -> None:
        self._aggregate_generation += 1
        cancelled = self.workers.cancel_group(self, "boot")
        for worker in cancelled:
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    async def _gql_for_workspace(
        self, profile_name: str, query: str, variables: dict | None = None
    ) -> dict:
        is_mutation = query.lstrip().startswith("mutation")
        if self._switching and is_mutation:
            raise RuntimeError("workspace switch in progress")
        if self._is_all_workspaces and is_mutation:
            await self._cancel_aggregate_refresh_for_mutation()
        if not self._is_all_workspaces and profile_name == self.active_workspace:
            return await self.gql(query, variables)
        profile = self._profile(profile_name)
        client = self._new_client(profile.api_key)
        try:
            return await self._gql_client(client, query, variables)
        finally:
            await client.aclose()

    async def _gql_for_issue(
        self, issue: dict, query: str, variables: dict | None = None
    ) -> dict:
        return await self._gql_for_workspace(
            self._issue_workspace(issue), query, variables
        )

    async def _gql_for_team(
        self, team: dict, query: str, variables: dict | None = None
    ) -> dict:
        return await self._gql_for_workspace(
            self._team_workspace(team), query, variables
        )

    def _workspace_team(self, profile: str, boot: dict) -> dict | None:
        teams = boot.get("teams", {}).get("nodes", [])
        saved_team = load_state(self._storage, profile).get("team_id")
        return next((team for team in teams if team["id"] == saved_team), None) or (
            teams[0] if teams else None
        )

    def _cached_workspace_snapshot(
        self, profile: WorkspaceProfile
    ) -> WorkspaceSnapshot | None:
        boot = read_cache(self._storage, profile.name, "boot")
        if not boot:
            return None
        team = self._workspace_team(profile.name, boot)
        if team is None:
            return None
        team_cache = read_cache(
            self._storage, profile.name, f"team-{team['id']}"
        )
        if not team_cache:
            return None
        return WorkspaceSnapshot(
            profile.name,
            profile.label,
            boot,
            team,
            team_cache.get("issues", []),
            team_cache.get("states", []),
            team_cache.get("cycles", []),
            bool(team_cache.get("cycles_complete", False)),
        )

    async def _fetch_workspace_snapshot(
        self, profile: WorkspaceProfile, semaphore: asyncio.Semaphore
    ) -> WorkspaceSnapshot:
        async with semaphore:
            client = self._new_client(profile.api_key)
            try:
                boot = await self._gql_client(client, QL_BOOT)
                team = self._workspace_team(profile.name, boot)
                if team is None:
                    raise RuntimeError("no teams found")
                data, cycle_data = await asyncio.gather(
                    self._gql_client(
                        client, QL_ISSUES, {"teamId": team["id"]}
                    ),
                    self._gql_client(
                        client, QL_CYCLES, {"teamId": team["id"]}
                    ),
                )
                cycles = cycle_data["team"]["cycles"]
                return WorkspaceSnapshot(
                    profile.name,
                    profile.label,
                    boot,
                    team,
                    data["team"]["issues"]["nodes"],
                    data["team"]["states"]["nodes"],
                    cycles["nodes"],
                    not cycles["pageInfo"]["hasNextPage"],
                )
            finally:
                await client.aclose()

    def _aggregate_is_current(self, generation: int) -> bool:
        return self._is_all_workspaces and generation == self._aggregate_generation

    @work(exclusive=True, group="boot")
    async def load_all_workspaces(
        self, generation: int, cached: dict[str, WorkspaceSnapshot]
    ) -> None:
        semaphore = asyncio.Semaphore(4)
        profiles = list(self._profile_resolution.profiles)
        results = await asyncio.gather(
            *(
                self._fetch_workspace_snapshot(profile, semaphore)
                for profile in profiles
            ),
            return_exceptions=True,
        )
        if not self._aggregate_is_current(generation):
            return
        merged = dict(cached)
        refreshed: set[str] = set()
        for profile, result in zip(profiles, results):
            if isinstance(result, BaseException):
                self.notify(
                    f"{profile.label}: {result}", severity="error", timeout=10
                )
                continue
            if not self._aggregate_is_current(generation):
                return
            write_cache(self._storage, profile.name, "boot", result.boot)
            if not self._aggregate_is_current(generation):
                return
            write_cache(
                self._storage,
                profile.name,
                f"team-{result.team['id']}",
                {
                    "issues": result.issues,
                    "states": result.states,
                    "cycles": result.cycles,
                    "cycles_complete": result.cycles_complete,
                },
            )
            merged[profile.name] = result
            refreshed.add(profile.name)
        if not self._aggregate_is_current(generation):
            return
        view = self._cycle_view
        if view.mode == "named" and view.workspace in refreshed:
            snapshot = merged.get(view.workspace)
            if snapshot is not None:
                self._validate_named_cycle_for_team(
                    view.workspace,
                    snapshot.team["id"],
                    snapshot.cycles,
                    snapshot.cycles_complete,
                )
        self._render_all_workspaces(merged)
        self.query_one("#issues", NavList).loading = False

    def _render_all_workspaces(
        self, snapshots: dict[str, WorkspaceSnapshot]
    ) -> None:
        detail_key = (
            self._issue_key(self._detail_issue)
            if self._detail_issue is not None
            else None
        )
        self._workspace_snapshots = snapshots
        self._workspace_states = {
            name: snapshot.states for name, snapshot in snapshots.items()
        }
        self._workspace_cycles = {
            name: snapshot.cycles for name, snapshot in snapshots.items()
        }
        self._workspace_cycles_complete = {
            name: snapshot.cycles_complete for name, snapshot in snapshots.items()
        }
        self._workspace_viewers = {
            name: snapshot.boot["viewer"] for name, snapshot in snapshots.items()
        }
        self._workspace_teams = {}
        self._teams = []
        self._issues = []
        self._states = []
        self._cycles = []
        self._cycles_complete = False
        for name, snapshot in snapshots.items():
            team = dict(snapshot.team)
            team["_workspace"] = name
            self._workspace_teams[name] = team
            self._teams.append(team)
            self._states.extend(snapshot.states)
            for raw_issue in snapshot.issues:
                issue = dict(raw_issue)
                issue["_workspace"] = name
                self._issues.append(issue)
        self._team = None
        self._viewer_id = None
        self._viewer_name = "All workspaces"
        self._org = f"{len(snapshots)} connected"
        self._issue_by_id = {self._issue_key(issue): issue for issue in self._issues}
        if detail_key is not None:
            fresh_detail = self._issue_by_id.get(detail_key)
            if fresh_detail is None:
                self.close_detail()
            else:
                self._detail_issue = fresh_detail
                self.query_one("#d-title", Static).update(
                    Text(fresh_detail["title"], style=f"bold {C_TEXT}")
                )
                self._update_detail_meta(fresh_detail)
                description = fresh_detail.get("description") or "*no description*"
                self.query_one("#d-desc", Markdown).update(description)
        teams_list = self.query_one("#teams", NavList)
        teams_list.clear_options()
        for profile in self._profile_resolution.profiles:
            snapshot = snapshots.get(profile.name)
            count = len(snapshot.issues) if snapshot else 0
            row = Text("◆ ", style=C_BLUE)
            row.append(profile.label, style=C_TEXT)
            row.append(f"  {count}", style=C_DIM)
            teams_list.add_option(Option(row, id=f"workspace:{profile.name}"))
        self.query_one("#teams").border_title = " workspaces "
        self.query_one("#centre").border_title = " all workspaces "
        self._update_profile()
        self._update_header()
        self.render_issues()

    # ── workers ───────────────────────────────────────────────────────
    def _render_boot(self, data: dict) -> None:
        self._boot_data = data
        self._teams = data["teams"]["nodes"]
        self._viewer_id = data["viewer"]["id"]
        self._viewer_name = data["viewer"]["displayName"]
        self._org = data["organization"]["name"]
        self._update_profile()
        self._update_header()

        teams_list = self.query_one("#teams", NavList)
        teams_list.clear_options()
        for t in self._teams:
            row = Text()
            row.append("● ", style=t.get("color") or C_BLUE)
            row.append(t["name"], style=C_TEXT)
            row.append(f"  {t['key']}", style=C_DIM)
            teams_list.add_option(Option(row, id=t["id"]))
        if self._team is not None:
            idx = next(
                (n for n, t in enumerate(self._teams) if t["id"] == self._team["id"]),
                None,
            )
            if idx is not None:
                teams_list.highlighted = idx

    @work(exclusive=True, group="boot")
    async def boot(self, pick_team: bool = True) -> None:
        issues_list = self.query_one("#issues", NavList)
        if pick_team:
            issues_list.loading = True
        try:
            data = await self.gql(QL_BOOT)
        except Exception as e:
            if pick_team:
                issues_list.loading = False
            self.notify(f"linear: {e}", severity="error", timeout=10)
            return
        if self._switching:
            return
        self._render_boot(data)
        write_cache(self._storage, self.active_workspace, "boot", data)
        if not pick_team:
            return
        last = self._load_profile_state().get("team_id")
        team = next((t for t in self._teams if t["id"] == last), None) or (
            self._teams[0] if self._teams else None
        )
        if team is None:
            issues_list.loading = False
            self.notify("no teams found", severity="warning")
            return
        self.query_one("#teams", NavList).highlighted = self._teams.index(team)
        self.load_team(team)

    def _save_layout(self, reset: str | None = None) -> None:
        if self._active_profile is None:
            return
        data = self._load_profile_state()
        if reset == "#sidebar":
            data.pop("sidebar_w", None)
        else:
            data["sidebar_w"] = self.query_one("#sidebar").outer_size.width
        detail = self.query_one("#detail")
        if reset == "#detail":
            data.pop("detail_w", None)
        elif detail.has_class("open"):
            data["detail_w"] = detail.outer_size.width
        save_state(self._storage, self.active_workspace, data)

    def _save_state(self) -> None:
        if self._active_profile is None:
            return
        data = self._load_profile_state()
        if self._team is not None:
            data["team_id"] = self._team["id"]
        data["mine"] = self._mine
        data["theme"] = self.theme
        data["group_by"] = self._group_by
        data["status_view"] = status_view_to_state(self._status_view)
        data["cycle_view"] = cycle_view_to_state(self._cycle_view)
        save_state(self._storage, self.active_workspace, data)

    @staticmethod
    def _without_internal_fields(data: dict) -> dict:
        return {key: value for key, value in data.items() if not key.startswith("_")}

    def _write_team_cache(self, issue: dict | None = None) -> None:
        if self._is_all_workspaces and issue is not None:
            workspace = self._issue_workspace(issue)
            team = self._workspace_teams.get(workspace)
            if team is None:
                return
            issues = [
                self._without_internal_fields(candidate)
                for candidate in self._issues
                if self._issue_workspace(candidate) == workspace
            ]
            states = self._workspace_states.get(workspace, [])
            cycles = self._workspace_cycles.get(workspace, [])
            cycles_complete = self._workspace_cycles_complete.get(workspace, False)
            write_cache(
                self._storage,
                workspace,
                f"team-{team['id']}",
                {
                    "issues": issues,
                    "states": states,
                    "cycles": cycles,
                    "cycles_complete": cycles_complete,
                },
            )
            snapshot = self._workspace_snapshots.get(workspace)
            if snapshot is not None:
                self._workspace_snapshots[workspace] = WorkspaceSnapshot(
                    snapshot.profile,
                    snapshot.label,
                    snapshot.boot,
                    snapshot.team,
                    issues,
                    states,
                    cycles,
                    cycles_complete,
                )
        elif self._team is not None:
            write_cache(
                self._storage,
                self.active_workspace,
                f"team-{self._team['id']}",
                {
                    "issues": self._issues,
                    "states": self._states,
                    "cycles": self._cycles,
                    "cycles_complete": self._cycles_complete,
                },
            )

    def _set_issues(
        self,
        issues: list[dict],
        states: list[dict],
        cycles: list[dict] | None = None,
        cycles_complete: bool = False,
    ) -> None:
        self._issues = issues
        self._states = states
        self._cycles = cycles or []
        self._cycles_complete = cycles_complete
        self._issue_by_id = {self._issue_key(issue): issue for issue in issues}

    @work(exclusive=True, group="issues")
    async def load_team(self, team: dict) -> None:
        self._team = team
        self._validate_named_cycle_for_team(
            self.active_workspace, team["id"], [], False
        )
        centre = self.query_one("#centre")
        centre.border_title = f" {team['key']} · {team['name']} "
        centre.border_subtitle = ""
        issues_list = self.query_one("#issues", NavList)
        allow_legacy = bool(
            self._profile_resolution
            and self._profile_resolution.allow_legacy_storage
        )
        cached = read_cache(
            self._storage,
            self.active_workspace,
            f"team-{team['id']}",
            allow_legacy=allow_legacy,
        )
        if cached:
            self._set_issues(
                cached["issues"],
                cached["states"],
                cached.get("cycles", []),
                bool(cached.get("cycles_complete", False)),
            )
            self.render_issues()
            centre.border_subtitle = f" {len(self._issues)} · ↻ refreshing "
            self._refreshing = True
        else:
            issues_list.loading = True
        self._save_state()
        try:
            data, cycle_data = await asyncio.gather(
                self.gql(QL_ISSUES, {"teamId": team["id"]}),
                self.gql(QL_CYCLES, {"teamId": team["id"]}),
            )
        except Exception as e:
            issues_list.loading = False
            self._refreshing = False
            self.notify(f"linear: {e}", severity="error", timeout=10)
            return
        if self._switching:
            self._refreshing = False
            return
        if self._team is None or self._team["id"] != team["id"]:
            self._refreshing = False
            return  # user switched teams while refreshing
        cycles = cycle_data["team"]["cycles"]
        cycles_complete = not cycles["pageInfo"]["hasNextPage"]
        self._set_issues(
            data["team"]["issues"]["nodes"],
            data["team"]["states"]["nodes"],
            cycles["nodes"],
            cycles_complete,
        )
        self._validate_named_cycle_for_team(
            self.active_workspace,
            team["id"],
            self._cycles,
            cycles_complete,
        )
        issues_list.loading = False
        self._refreshing = False
        write_cache(
            self._storage,
            self.active_workspace,
            f"team-{team['id']}",
            {
                "issues": self._issues,
                "states": self._states,
                "cycles": self._cycles,
                "cycles_complete": self._cycles_complete,
            },
        )
        self.render_issues()
        # a cold load covers the list with a loading overlay, which kicks
        # focus over to the sidebar — pull it back once rows exist
        if not cached and self._detail_issue is None:
            focused = self.focused
            if focused is None or focused.id == "teams":
                issues_list.focus()
        if self._detail_issue is not None:
            fresh = self._issue_by_id.get(self._issue_key(self._detail_issue))
            if fresh is not None:
                self._detail_issue = fresh
                self._update_detail_meta(fresh)

    # NOT named _auto_refresh: textual's DOMNode owns that instance attribute
    # (backing field of the auto_refresh property) and would shadow the method
    def _auto_refresh_board(self) -> None:
        # silent background re-sync — load_team's cache-render + exclusive
        # "issues" worker group makes this a quiet swap that preserves the
        # highlight and the open detail panel. Skip whenever it could
        # interrupt the user (modal open) or race a pending mutation.
        if self._switching:
            return
        if isinstance(self.screen, ModalScreen):
            return
        if any(
            w.group == "mutate"
            and w.state in (WorkerState.PENDING, WorkerState.RUNNING)
            for w in self.workers
        ):
            return
        if self._is_all_workspaces:
            self._start_all_workspaces()
        elif self.client is not None and self._team is not None:
            self.load_team(self._team)

    @work(exclusive=True, group="detail")
    async def load_comments(self, issue: dict) -> None:
        box = self.query_one("#d-comments", Vertical)
        head = self.query_one("#d-comments-head", Static)
        parent_w = self.query_one("#d-parent", Static)
        cbox = self.query_one("#d-children", Vertical)
        parent_w.update("")
        parent_w.remove_class("visible")
        cbox.remove_class("visible")
        await cbox.remove_children()
        await box.remove_children()
        head.update(Text(" comments · loading…", style=C_DIM))
        try:
            data = await self._gql_for_issue(
                issue, QL_COMMENTS, {"id": issue["id"]}
            )
        except Exception as e:
            head.update(Text(f" comments · failed: {e}", style=C_RED))
            return
        if self._switching:
            return
        if (
            self._detail_issue is None
            or self._issue_key(self._detail_issue) != self._issue_key(issue)
        ):
            return
        # parent + sub-issues context (old caches / demo stubs lack the keys)
        parent = data["issue"].get("parent")
        if parent:
            line = Text(no_wrap=True, overflow="ellipsis")
            line.append("\uf148 parent ", style=C_DIM)
            line.append(parent["identifier"], style=C_SUB)
            p_title = (parent.get("title") or "").strip()
            if len(p_title) > 60:
                p_title = p_title[:59] + "…"
            if p_title:
                line.append(f" — {p_title}", style=C_DIM)
            parent_w.update(line)
            parent_w.add_class("visible")
        children = (data["issue"].get("children") or {}).get("nodes") or []
        if children:
            done = sum(
                1 for ch in children
                if ch["state"]["type"] in ("completed", "canceled")
            )
            chead = Text("\uf0e8 ", style=C_MAUVE)
            chead.append(f"sub-issues · {done}/{len(children)}", style=f"bold {C_SUB}")
            await cbox.mount(Static(chead))
            for ch in children:
                st = ch["state"]
                row = Text(no_wrap=True, overflow="ellipsis")
                row.append(f"{state_icon(st)} ", style=st["color"] or C_SUB)
                row.append(ch["identifier"], style=C_DIM)
                c_title = ch["title"]
                if len(c_title) > 60:
                    c_title = c_title[:59] + "…"
                row.append(f" {c_title}", style=C_TEXT)
                await cbox.mount(Static(row))
            cbox.add_class("visible")
        comments = sorted(
            data["issue"]["comments"]["nodes"], key=lambda c: c["createdAt"]
        )
        head_text = Text(" ", style=C_MAUVE)
        head_text.append(f" comments · {len(comments)}", style=f"bold {C_SUB}")
        head.update(head_text)
        if not comments:
            await box.mount(Static(Text("   nothing here yet", style=C_DIM)))
            return
        for c in comments:
            author = (c.get("user") or {}).get("displayName") or (
                c.get("botActor") or {}
            ).get("name") or "unknown"
            meta = Text()
            meta.append("● ", style=C_MAUVE)
            meta.append(author, style=f"bold {C_TEXT}")
            meta.append(f"  {rel_time(c['createdAt'])} ago", style=C_DIM)
            wrap = Vertical(classes="comment")
            await box.mount(wrap)
            await wrap.mount(Static(meta, classes="comment-meta"))
            await wrap.mount(Markdown(c["body"] or ""))

    @work(group="mutate")
    async def apply_status(self, issue: dict, state_id: str) -> None:
        try:
            data = await self._gql_for_issue(
                issue, M_STATE, {"id": issue["id"], "stateId": state_id}
            )
            new_state = data["issueUpdate"]["issue"]["state"]
        except Exception as e:
            self.notify(f"update failed: {e}", severity="error")
            return
        issue["state"] = new_state
        self._write_team_cache(issue)
        self.render_issues(keep=self._issue_key(issue))
        if self._detail_issue and self._issue_key(self._detail_issue) == self._issue_key(issue):
            self._update_detail_meta(issue)
        self.notify(f" {issue['identifier']} → {new_state['name']}")

    @work(group="mutate")
    async def apply_priority(self, issue: dict, p: int) -> None:
        try:
            await self._gql_for_issue(
                issue, M_PRIORITY, {"id": issue["id"], "p": p}
            )
        except Exception as e:
            self.notify(f"update failed: {e}", severity="error")
            return
        issue["priority"] = p
        self._write_team_cache(issue)
        self.render_issues(keep=self._issue_key(issue))
        if self._detail_issue and self._issue_key(self._detail_issue) == self._issue_key(issue):
            self._update_detail_meta(issue)
        self.notify(f" {issue['identifier']} → {priority_name(p)}")

    @work(group="mutate")
    async def apply_assignee(self, issue: dict, assignee_id: str | None) -> None:
        try:
            data = await self._gql_for_issue(
                issue, M_ASSIGN, {"id": issue["id"], "assigneeId": assignee_id}
            )
            new_assignee = data["issueUpdate"]["issue"]["assignee"]
        except Exception as e:
            self.notify(f"update failed: {e}", severity="error")
            return
        issue["assignee"] = new_assignee
        self._write_team_cache(issue)
        self.render_issues(keep=self._issue_key(issue))
        if self._detail_issue and self._issue_key(self._detail_issue) == self._issue_key(issue):
            self._update_detail_meta(issue)
        name = (new_assignee or {}).get("displayName") or "unassigned"
        self.notify(f"\uf007 {issue['identifier']} → {name}")

    @work(group="mutate")
    async def create_issue(self, team: dict, title: str, desc: str | None) -> None:
        try:
            data = await self._gql_for_team(
                team,
                M_CREATE,
                {"teamId": team["id"], "title": title, "desc": desc},
            )
            issue = data["issueCreate"]["issue"]
        except Exception as e:
            self.notify(f"create failed: {e}", severity="error")
            return
        if not self._is_all_workspaces and (
            self._team is None or self._team["id"] != team["id"]
        ):
            self.notify(f" created {issue['identifier']}")
            return
        if self._is_all_workspaces:
            issue = dict(issue)
            issue["_workspace"] = self._team_workspace(team)
        self._issues.insert(0, issue)
        self._issue_by_id[self._issue_key(issue)] = issue
        self._write_team_cache(issue)
        self.render_issues(keep=self._issue_key(issue))
        self.notify(f" created {issue['identifier']}")

    @work(group="mutate")
    async def submit_comment(self, issue: dict, body: str) -> None:
        try:
            await self._gql_for_issue(
                issue, M_COMMENT, {"id": issue["id"], "body": body}
            )
        except Exception as e:
            self.notify(f"comment failed: {e}", severity="error")
            return
        self.notify(f" comment added to {issue['identifier']}")
        if self._detail_issue and self._issue_key(self._detail_issue) == self._issue_key(issue):
            self.load_comments(issue)

    # ── rendering ─────────────────────────────────────────────────────
    def render_issues(self, keep: str | None = None) -> None:
        ol = self.query_one("#issues", NavList)
        if keep is None:
            prev = ol.highlighted
            if prev is not None:
                opt = ol.get_option_at_index(prev)
                keep = opt.id if opt else None

        width = max(ol.content_size.width - 2, 40)
        flt = self._filter.lower()
        issues = [
            issue
            for issue in self._issues
            if status_view_matches(
                self._status_view, issue.get("state", {}).get("type", "")
            )
            and cycle_view_matches(
                self._cycle_view, issue, self._issue_workspace(issue)
            )
        ]
        def viewer_id(issue: dict) -> str | None:
            if self._is_all_workspaces:
                viewer = self._workspace_viewers.get(self._issue_workspace(issue), {})
                return viewer.get("id")
            return self._viewer_id

        if self._mine:
            issues = [
                i
                for i in issues
                if viewer_id(i)
                and (i.get("assignee") or {}).get("id") == viewer_id(i)
            ]
        if self._project_filter is not None:
            issues = [
                i
                for i in issues
                if self._project_key(i) == self._project_filter
            ]
        if flt:
            issues = [
                i
                for i in issues
                if flt
                in (
                    i["title"]
                    + " "
                    + i["identifier"]
                    + " "
                    + ((i.get("assignee") or {}).get("displayName") or "")
                    + " "
                    + self._workspace_label(self._issue_workspace(i))
                    + " "
                    + (cycle_name(i["cycle"]) if i.get("cycle") else "")
                ).lower()
            ]

        def mine_first(i: dict):
            is_mine = (i.get("assignee") or {}).get("id") == viewer_id(i)
            return (0 if is_mine else 1, *issue_sort_key(i))

        if self._is_all_workspaces and self._group_by == "workspace":
            by_workspace: dict[str, list[dict]] = {}
            for issue in issues:
                by_workspace.setdefault(self._issue_workspace(issue), []).append(issue)
            groups = [
                (
                    self._workspace_header_row(
                        profile.label,
                        len(by_workspace.get(profile.name, [])),
                        width,
                    ),
                    sorted(by_workspace.get(profile.name, []), key=mine_first),
                )
                for profile in self._profile_resolution.profiles
                if by_workspace.get(profile.name)
            ]
        elif self._group_by == "project":
            # group by project; inside a project keep the status order,
            # then mine-first + recency
            by_proj: dict[str, list[dict]] = {}
            proj_of: dict[str, dict] = {}
            for i in issues:
                p = i.get("project") or {"id": "", "name": "no project", "color": None}
                pid = self._project_key(i)
                by_proj.setdefault(pid, []).append(i)
                tagged_project = dict(p)
                tagged_project["_group_key"] = pid
                proj_of[pid] = tagged_project
            # biggest projects first, the no-project bucket last
            ordered_groups = sorted(
                proj_of.values(),
                key=lambda p: (
                    p["id"] == "",
                    -len(by_proj[p["_group_key"]]),
                ),
            )
            def in_group_key(i: dict):
                return (state_sort_key(i["state"]), *mine_first(i))
            groups = [
                (self._project_header_row(p, len(by_proj[p["_group_key"]]), width),
                 sorted(by_proj[p["_group_key"]], key=in_group_key))
                for p in ordered_groups
            ]
        else:
            by_state: dict[str, list[dict]] = {}
            state_of: dict[str, dict] = {}
            for i in issues:
                sid = (
                    scoped_id(self._issue_workspace(i), i["state"]["id"])
                    if self._is_all_workspaces
                    else i["state"]["id"]
                )
                by_state.setdefault(sid, []).append(i)
                state = dict(i["state"])
                state["_group_key"] = sid
                state_of[sid] = state
            ordered_states = sorted(state_of.values(), key=state_sort_key)
            groups = [
                (self._header_row(st, len(by_state[st["_group_key"]]), width),
                 sorted(by_state[st["_group_key"]], key=mine_first))
                for st in ordered_states
            ]

        id_w = max((len(i["identifier"]) for i in issues), default=6)
        ol.clear_options()
        self._opt_index = {}
        self._header_indices = []
        opts: list[Option] = []
        first = True
        for header, group in groups:
            if not first:
                opts.append(Option(Text(" "), disabled=True))
            first = False
            self._header_indices.append(len(opts))
            opts.append(Option(header, disabled=True))
            for i in group:
                key = self._issue_key(i)
                self._opt_index[key] = len(opts)
                opts.append(Option(self._issue_row(i, width, id_w), id=key))
        if not opts:
            msg = "no matches" if flt else "no issues"
            opts.append(Option(Text(f"  {msg}", style=C_DIM), disabled=True))
        ol.add_options(opts)

        # a group's first issue sits right after its header row
        self._group_starts = [h + 1 for h in self._header_indices]
        status_tag = f" \uf0b0 {status_view_label(self._status_view)} \u00b7"
        cycle_tag = (
            f" \uf021 {self._cycle_view_label()} \u00b7"
            if self._cycle_view.mode != "all"
            else ""
        )
        mine_tag = " \uf007 mine \u00b7" if self._mine else ""
        proj_tag = ""
        if self._project_filter is not None:
            pname = next(
                ((i.get("project") or {}).get("name") for i in self._issues
                 if self._project_key(i) == self._project_filter),
                "no project",
            ) or "no project"
            proj_tag = f" \uf07b {pname} \u00b7"
        self.query_one("#centre").border_subtitle = (
            f"{status_tag}{cycle_tag}{mine_tag}{proj_tag} {len(issues)} issues "
        )
        if keep and keep in self._opt_index:
            ol.highlighted = self._opt_index[keep]
        elif self._opt_index:
            ol.highlighted = min(self._opt_index.values())

    def _workspace_label(self, profile: str) -> str:
        try:
            return self._profile(profile).label
        except KeyError:
            return profile

    def _project_key(self, issue: dict) -> str:
        project_id = (issue.get("project") or {}).get("id", "")
        if self._is_all_workspaces:
            return scoped_id(self._issue_workspace(issue), project_id)
        return project_id

    def _workspace_header_row(self, label: str, count: int, width: int) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("◆ ", style=C_BLUE)
        t.append(label, style=f"bold {C_BLUE}")
        t.append(f" · {count} ", style=C_DIM)
        fill = width - t.cell_len - 1
        if fill > 0:
            t.append("─" * fill, style=C_FAINT)
        return t

    def _header_row(self, state: dict, count: int, width: int) -> Text:
        color = state["color"] or C_SUB
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(f"{state_icon(state)} ", style=color)
        t.append(state["name"], style=f"bold {color}")
        t.append(f" · {count} ", style=C_DIM)
        fill = width - t.cell_len - 1
        if fill > 0:
            t.append("─" * fill, style=C_FAINT)
        return t

    def _project_header_row(self, project: dict, count: int, width: int) -> Text:
        color = project.get("color") or C_DIM
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("\uf07b ", style=color)
        t.append(project["name"], style=f"bold {color}")
        t.append(f" \u00b7 {count} ", style=C_DIM)
        fill = width - t.cell_len - 1
        if fill > 0:
            t.append("\u2500" * fill, style=C_FAINT)
        return t

    def _issue_row(self, issue: dict, width: int, id_w: int) -> Text:
        st = issue["state"]
        t = Text(no_wrap=True, overflow="ellipsis")
        workspace_w = 0
        if self._is_all_workspaces:
            label = self._workspace_label(self._issue_workspace(issue))[:10]
            workspace_w = len(label) + 3
            t.append(f"{label} ", style=C_BLUE)
            t.append("· ", style=C_VFAINT)
        t.append(f"{state_icon(st)} ", style=st["color"] or C_SUB)
        t.append(issue["identifier"].ljust(id_w), style=C_DIM)
        t.append(" ")

        assignee = (issue.get("assignee") or {}).get("displayName") or ""
        assignee = assignee.split()[0][:10] if assignee else "—"
        time_s = rel_time(issue["updatedAt"])
        labels = issue["labels"]["nodes"][:3]
        blocked_by, blocks = block_info(issue)
        badges = []
        if blocked_by:
            badges.append((" \uf056", C_RED))  # blocked by something
        if blocks:
            badges.append((" \uf06a", C_PEACH))  # blocking something

        right_w = 3 + 2 + 10 + 2 + 4  # prio, gap, assignee, gap, time
        title_w = width - workspace_w - 2 - id_w - 1 - right_w - 1
        dots_w = len(labels) * 2 + len(badges) * 2
        title = issue["title"]
        avail = max(title_w - dots_w, 8)
        if len(title) > avail:
            title = title[: avail - 1] + "…"
        t.append(title, style=C_TEXT)
        for badge, color in badges:
            t.append(badge, style=color)
        for lb in labels:
            t.append(" ●", style=lb["color"] or C_DIM)
        pad = title_w - len(title) - dots_w
        if pad > 0:
            t.append(" " * pad)

        t.append(" ")
        t.append_text(priority_cell(issue["priority"]))
        t.append("  ")
        style = C_SUB if assignee != "—" else C_VFAINT
        t.append(assignee.ljust(10), style=style)
        t.append("  ")
        t.append(time_s.rjust(4), style=C_DIM)
        return t

    # ── detail panel ──────────────────────────────────────────────────
    def show_detail(self, issue: dict) -> None:
        self._detail_issue = issue
        parent_w = self.query_one("#d-parent", Static)
        parent_w.update("")
        parent_w.remove_class("visible")
        children_w = self.query_one("#d-children", Vertical)
        children_w.remove_class("visible")
        children_w.remove_children()
        panel = self.query_one("#detail")
        was_closed = not panel.has_class("open")
        panel.add_class("open")
        self.query_one("#split-right").add_class("open")
        if was_closed:
            pop_in(panel, duration=0.18)
        panel.border_title = f"  {issue['identifier']} "
        panel.border_subtitle = f" {rel_time(issue['updatedAt'])} ago "
        self.query_one("#d-title", Static).update(
            Text(issue["title"], style=f"bold {C_TEXT}")
        )
        self._update_detail_meta(issue)
        desc = issue.get("description") or "*no description*"
        self.query_one("#d-desc", Markdown).update(desc)
        self.query_one("#d-scroll", DetailScroll).scroll_home(animate=False)
        self.load_comments(issue)

    def _update_detail_meta(self, issue: dict) -> None:
        st = issue["state"]
        m = Text()
        m.append(f"{state_icon(st)} ", style=st["color"] or C_SUB)
        m.append(st["name"], style=f"bold {st['color'] or C_SUB}")
        m.append("   ")
        m.append_text(priority_cell(issue["priority"]))
        m.append(f" {priority_name(issue['priority'])}", style=C_SUB)
        m.append("   ")
        m.append(" ", style=C_DIM)
        assignee = (issue.get("assignee") or {}).get("displayName") or "unassigned"
        m.append(assignee, style=C_SUB)
        project = issue.get("project")
        if project:
            m.append("   ")
            m.append("\uf07b ", style=project.get("color") or C_DIM)
            m.append(project["name"], style=C_SUB)
        cycle = issue.get("cycle")
        if cycle:
            m.append("   ")
            m.append("\uf021 ", style=C_BLUE)
            m.append(cycle_name(cycle), style=C_SUB)
        labels = issue["labels"]["nodes"]
        if labels:
            m.append("\n")
            for lb in labels:
                m.append(" ", style=lb["color"] or C_DIM)
                m.append(f"{lb['name']}  ", style=C_SUB)
        blocked_by, blocks = block_info(issue)
        if blocked_by or blocks:
            m.append("\n")
            if blocked_by:
                m.append("\uf056 ", style=C_RED)
                m.append("blocked by " + " \u00b7 ".join(blocked_by), style=C_RED)
            if blocked_by and blocks:
                m.append("   ")
            if blocks:
                m.append("\uf06a ", style=C_PEACH)
                m.append("blocks " + " \u00b7 ".join(blocks), style=C_PEACH)
        m.append("\n")
        m.append(" ", style=C_DIM)
        m.append(
            f"created {parse_dt(issue['createdAt']).strftime('%b %d')}"
            f" · updated {rel_time(issue['updatedAt'])} ago",
            style=C_DIM,
        )
        self.query_one("#d-meta", Static).update(m)

    def close_detail(self) -> None:
        self._detail_issue = None
        self.query_one("#detail").remove_class("open")
        self.query_one("#split-right").remove_class("open")
        self.query_one("#issues").focus()

    def _current_issue(self) -> dict | None:
        if self._detail_issue is not None:
            return self._detail_issue
        ol = self.query_one("#issues", NavList)
        if ol.highlighted is None:
            return None
        opt = ol.get_option_at_index(ol.highlighted)
        if opt is None or opt.id is None:
            return None
        return self._issue_by_id.get(opt.id)

    # ── events ────────────────────────────────────────────────────────
    @on(OptionList.OptionSelected, "#teams")
    def _team_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id or ""
        if self._is_all_workspaces and option_id.startswith("workspace:"):
            self._begin_workspace_switch(option_id.removeprefix("workspace:"))
            return
        team = next((t for t in self._teams if t["id"] == event.option.id), None)
        if team and (self._team is None or team["id"] != self._team["id"]):
            if self._detail_issue:
                self.close_detail()
            self.load_team(team)

    @on(OptionList.OptionSelected, "#issues")
    def _issue_selected(self, event: OptionList.OptionSelected) -> None:
        issue = self._issue_by_id.get(event.option.id or "")
        if issue:
            self.show_detail(issue)
            self.query_one("#d-scroll").focus()

    @on(Input.Changed, "#filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self._filter = event.value
        self.render_issues()

    @on(Input.Submitted, "#filter")
    def _filter_submitted(self) -> None:
        self.query_one("#issues").focus()

    # ── actions ───────────────────────────────────────────────────────
    def action_switch_workspace(self) -> None:
        resolution = self._profile_resolution
        if resolution is None or len(resolution.profiles) < 2:
            self.notify("configure two or more workspaces to switch", severity="warning")
            return
        if self._switching:
            self.notify("workspace switch already in progress", severity="warning")
            return
        options: list[Option] = []
        for profile in resolution.profiles:
            row = Text("◆ ", style=C_BLUE if profile.name == self.active_workspace else C_DIM)
            row.append(profile.label, style=C_TEXT)
            if profile.name == self.active_workspace:
                row.append("  ", style=C_GREEN)
            options.append(Option(row, id=profile.name))
        all_row = Text(
            "◆ ", style=C_BLUE if self._is_all_workspaces else C_DIM
        )
        all_row.append("All workspaces", style=C_TEXT)
        if self._is_all_workspaces:
            all_row.append("  ", style=C_GREEN)
        options.append(Option(all_row, id=ALL_WORKSPACES))

        def selected(name: str | None) -> None:
            if name:
                self._begin_workspace_switch(name)

        self.push_screen(PickerModal("switch workspace", options), selected)

    def _begin_workspace_switch(self, name: str) -> bool:
        if self._switching:
            self.notify("workspace switch already in progress", severity="warning")
            return False
        if name == ALL_WORKSPACES:
            if len(self._profile_resolution.profiles) < 2:
                return False
        else:
            try:
                self._profile(name)
            except KeyError:
                self.notify("unknown workspace", severity="error")
                return False
        if name == self.active_workspace:
            return False
        if any(
            worker.group == "mutate"
            and worker.state in (WorkerState.PENDING, WorkerState.RUNNING)
            for worker in self.workers
        ):
            self.notify("finish the pending update before switching", severity="warning")
            return False
        # Set this synchronously, before the worker can yield, so a rapid second
        # keypress cannot start an overlapping credential/client transaction.
        self._switching = True
        self._aggregate_generation += 1
        self._switch_workspace_worker(name)
        return True

    @work(exclusive=True, group="workspace")
    async def _switch_workspace_worker(self, name: str) -> None:
        try:
            cancelled = []
            for group in ("boot", "issues", "detail", "members"):
                cancelled.extend(self.workers.cancel_group(self, group))
            for worker in dict.fromkeys(cancelled):
                try:
                    await worker.wait()
                except WorkerCancelled:
                    pass

            if self.client is not None:
                await self.client.aclose()
                self.client = None

            self._active_profile = name
            await self._clear_workspace_data()
            global_state = load_global_state(self._storage)
            global_state["active_workspace"] = name
            save_global_state(self._storage, global_state)
            self._apply_profile_preferences()
            self._update_profile()
            if self._is_all_workspaces:
                self._start_all_workspaces()
            else:
                self.query_one("#teams").border_title = " teams "
                self._start(self._profile().api_key)
        except Exception as error:
            self.notify(f"workspace switch failed: {error}", severity="error", timeout=10)
        finally:
            self._switching = False

    async def _clear_workspace_data(self) -> None:
        self._teams = []
        self._issues = []
        self._states = []
        self._cycles = []
        self._cycles_complete = False
        self._members = {}
        self._team_labels = {}
        self._team_projects = {}
        self._workspace_states = {}
        self._workspace_cycles = {}
        self._workspace_cycles_complete = {}
        self._workspace_viewers = {}
        self._workspace_teams = {}
        self._workspace_snapshots = {}
        self._team = None
        self._viewer_id = None
        self._viewer_name = None
        self._boot_data = None
        self._org = None
        self._status_view = DEFAULT_STATUS_VIEW
        self._cycle_view = DEFAULT_CYCLE_VIEW
        self._filter = ""
        self._project_filter = None
        self._detail_issue = None
        self._opt_index = {}
        self._issue_by_id = {}
        self._header_indices = []
        self._group_starts = []
        self._refreshing = False

        teams = self.query_one("#teams", NavList)
        issues = self.query_one("#issues", NavList)
        teams.clear_options()
        issues.clear_options()
        issues.loading = False
        filter_input = self.query_one("#filter", FilterInput)
        filter_input.value = ""
        filter_input.remove_class("visible")
        centre = self.query_one("#centre")
        centre.border_title = " issues "
        centre.border_subtitle = ""
        self.query_one("#appheader", Static).update("")
        self.query_one("#d-title", Static).update("")
        self.query_one("#d-meta", Static).update("")
        self.query_one("#d-parent", Static).update("")
        self.query_one("#d-parent").remove_class("visible")
        self.query_one("#d-children").remove_class("visible")
        await self.query_one("#d-children", Vertical).remove_children()
        self.query_one("#d-desc", Markdown).update("")
        self.query_one("#d-comments-head", Static).update("")
        await self.query_one("#d-comments", Vertical).remove_children()
        self.query_one("#detail").remove_class("open")
        self.query_one("#split-right").remove_class("open")
        self._update_profile()

    def action_refresh(self) -> None:
        if self._is_all_workspaces and not self._switching:
            if any(
                worker.group == "mutate"
                and worker.state in (WorkerState.PENDING, WorkerState.RUNNING)
                for worker in self.workers
            ):
                self.notify("finish the pending update before refreshing")
                return
            self._start_all_workspaces()
        elif self._team and not self._switching:
            self.load_team(self._team)

    def _tick_fx(self) -> None:
        if not CONFIG_OPTIONS.get("animations", True):
            return
        try:
            self.query_one("#profile")
        except Exception:
            return  # DOM not ready or tearing down — timers can outlive it
        # name wave: sweep, rest, repeat — renders only while sweeping
        if self._viewer_name:
            if self._wave_rest > 0:
                self._wave_rest -= 1
            else:
                self._wave_pos += 1
                if self._wave_pos >= len(self._viewer_name):
                    self._wave_pos = -1
                    self._wave_rest = FX_REST_TICKS
                self._update_profile()
                self._update_header()
        # braille spinner while a background refresh is in flight
        if self._refreshing:
            self._spin_frame = (self._spin_frame + 1) % len(SPINNER_FRAMES)
            frame = SPINNER_FRAMES[self._spin_frame]
            try:
                self.query_one("#centre").border_subtitle = (
                    f" {len(self._issues)} \u00b7 {frame} refreshing "
                )
            except Exception:
                pass

    def _update_header(self) -> None:
        if self._org is None or self._viewer_name is None:
            self.query_one("#appheader", Static).update("")
            return
        markup = (
            f"[bold {C_BLUE}] \uf03a [/]"
            + wave_markup("ltui", self._wave_pos, f"bold {C_BLUE}", C_LAV)
            + f"[{C_VFAINT}]  \u00b7  [/][{C_SUB}]{escape(self._org)}[/]"
            + f"[{C_VFAINT}] / [/][{C_DIM}]{escape(self._viewer_name)}[/]"
        )
        self.query_one("#appheader", Static).update(markup)

    def _update_profile(self) -> None:
        if self._viewer_name:
            name = wave_markup(
                self._viewer_name, self._wave_pos, f"bold {C_TEXT}", C_BLUE
            )
        else:
            name = f"[bold {C_TEXT}]\u2026[/]"
        org = escape(self._org or "connecting")
        workspace = "workspace"
        if self._is_all_workspaces:
            workspace = "All workspaces"
        elif self._active_profile is not None and self._profile_resolution is not None:
            workspace = escape(self._profile().label)
        mine = "on" if self._mine else "off"
        mine_color = C_GREEN if self._mine else C_DIM
        self.query_one("#profile", Static).update(
            " " + name + "\n"
            f"[{C_DIM}] {org}[/]\n"
            f"[@click=app.switch_workspace][{C_BLUE}] ◆ {workspace}[/][/]\n"
            f"[@click=app.change_theme][{C_SUB}] [/][{C_SUB}]{self.theme}[/][/]\n"
            f"[@click=app.toggle_mine][{C_SUB}] mine [/][{mine_color}]{mine}[/][/]\n"
            f"[@click=app.open_settings][{C_BLUE}] settings[/][/]"
        )

    def action_open_settings(self) -> None:
        if self._active_profile is None:
            self.notify("configure a workspace before opening settings", severity="warning")
            return
        if isinstance(self.screen, SettingsModal):
            return
        self.push_screen(SettingsModal())

    def action_help(self) -> None:
        if isinstance(self.screen, HelpModal):
            return
        self.push_screen(HelpModal())

    def action_change_theme(self) -> None:
        if isinstance(self.screen, ThemeModal):
            return
        self.push_screen(ThemeModal())

    def action_cycle_theme(self) -> None:
        idx = THEME_NAMES.index(self.theme) if self.theme in THEME_NAMES else -1
        self.theme = THEME_NAMES[(idx + 1) % len(THEME_NAMES)]
        self.notify(f" theme → {self.theme}")

    def action_new_ticket(self) -> None:
        if self._is_all_workspaces:
            options = []
            for profile in self._profile_resolution.profiles:
                team = self._workspace_teams.get(profile.name)
                if team is None:
                    continue
                row = Text("◆ ", style=C_BLUE)
                row.append(profile.label, style=C_TEXT)
                row.append(f"  {team['key']}", style=C_DIM)
                options.append(Option(row, id=profile.name))

            def picked(profile_name: str | None) -> None:
                if profile_name and profile_name in self._workspace_teams:
                    self._open_new_ticket(self._workspace_teams[profile_name])

            self.push_screen(PickerModal("new ticket · workspace", options), picked)
            return
        team = self._team
        if team is None:
            return
        self._open_new_ticket(team)

    def _open_new_ticket(self, team: dict) -> None:

        def done(result: tuple | None) -> None:
            if result:
                self.create_issue(team, result[0], result[1])

        self.push_screen(NewTicketModal(f" new ticket · {team['key']}"), done)

    def action_pick_project(self) -> None:
        projects: dict[str, dict] = {}
        counts: dict[str, int] = {}
        for i in self._issues:
            p = i.get("project") or {"id": "", "name": "no project", "color": None}
            pid = self._project_key(i)
            projects[pid] = p
            counts[pid] = counts.get(pid, 0) + 1
        opts = []
        row = Text()
        row.append("\uf03a ", style=C_BLUE)
        row.append("all projects", style=C_TEXT)
        if self._project_filter is None:
            row.append("  \uf00c", style=C_GREEN)
        opts.append(Option(row, id="all:"))
        for pid, p in sorted(projects.items(), key=lambda x: (x[0] == "", -counts[x[0]])):
            row = Text()
            row.append("\uf07b ", style=p.get("color") or C_DIM)
            row.append(p["name"], style=C_TEXT)
            row.append(f"  {counts[pid]}", style=C_DIM)
            if self._project_filter == pid:
                row.append("  \uf00c", style=C_GREEN)
            opts.append(Option(row, id=f"proj:{pid}"))

        def done(choice: str | None) -> None:
            if choice is None:
                return
            if choice == "all:":
                self._project_filter = None
            else:
                self._project_filter = choice.removeprefix("proj:")
            self.render_issues()

        self.push_screen(PickerModal("filter by project", opts), done)

    def _set_cycle_view(self, view: CycleView) -> None:
        self._cycle_view = view
        self._save_state()
        self.render_issues()

    def action_pick_cycle(self) -> None:
        options = []
        named_views: dict[str, CycleView] = {}

        for mode, label in (
            ("all", "All cycles"),
            ("current", "Current"),
            ("next", "Next"),
            ("previous", "Previous"),
            ("none", "No cycle"),
        ):
            view = CycleView(mode)
            count = sum(
                cycle_view_matches(view, issue, self._issue_workspace(issue))
                for issue in self._issues
            )
            row = Text("\uf021 ", style=C_BLUE)
            row.append(label, style=C_TEXT)
            row.append(f"  {count}", style=C_DIM)
            if self._cycle_view == view:
                row.append("  \uf00c", style=C_GREEN)
            options.append(Option(row, id=f"mode:{mode}"))

        for workspace, team, cycle in self._available_cycles():
            key = cycle_key(workspace, cycle["id"])
            view = CycleView("named", workspace, team["id"], cycle["id"])
            named_views[key] = view
            count = sum(
                cycle_view_matches(view, issue, self._issue_workspace(issue))
                for issue in self._issues
            )
            row = Text("\uf021 ", style=C_MAUVE)
            if self._is_all_workspaces:
                row.append(f"{self._workspace_label(workspace)} · ", style=C_BLUE)
            row.append(cycle_name(cycle), style=C_TEXT)
            row.append(f"  {count}", style=C_DIM)
            if self._cycle_view == view:
                row.append("  \uf00c", style=C_GREEN)
            options.append(Option(row, id=f"named:{key}"))

        def selected(choice: str | None) -> None:
            if choice is None:
                return
            if choice.startswith("mode:"):
                view = CycleView(choice.removeprefix("mode:"))
            else:
                view = named_views.get(choice.removeprefix("named:"))
                if view is None:
                    return
            self._set_cycle_view(view)
            self.notify(f"\uf021 cycle view → {self._cycle_view_label()}")

        self.push_screen(PickerModal("cycle view", options), selected)

    def action_next_group(self) -> None:
        self._jump_group(forward=True)

    def action_prev_group(self) -> None:
        self._jump_group(forward=False)

    def _jump_group(self, forward: bool) -> None:
        ol = self.query_one("#issues", NavList)
        starts = getattr(self, "_group_starts", [])
        if not starts:
            return
        cur = ol.highlighted if ol.highlighted is not None else -1
        if forward:
            target = next((s for s in starts if s > cur), starts[0])
        else:
            prev = [s for s in starts if s < cur]
            target = prev[-1] if prev else starts[-1]
        ol.highlighted = target
        ol.focus()

    def action_focus_left(self) -> None:
        """← walks panes: detail → issues → teams. No-op inside modals."""
        fid = self.focused.id if self.focused else None
        if fid == "d-scroll":
            self.query_one("#issues", NavList).focus()
        elif fid == "issues":
            self.query_one("#teams", NavList).focus()

    def action_focus_right(self) -> None:
        """→ walks panes: teams → issues → detail, opening it if needed."""
        fid = self.focused.id if self.focused else None
        if fid == "teams":
            self.query_one("#issues", NavList).focus()
        elif fid == "issues":
            issue = self._current_issue()
            if issue is None:
                return
            if self._detail_issue is None:
                self.show_detail(issue)
            self.query_one("#d-scroll").focus()

    def action_toggle_group(self) -> None:
        groups = (
            ("workspace", "status", "project")
            if self._is_all_workspaces
            else ("status", "project")
        )
        try:
            current = groups.index(self._group_by)
        except ValueError:
            current = -1
        self._group_by = groups[(current + 1) % len(groups)]
        self._save_state()
        self.render_issues()
        self.notify(f"\uf0ca grouping by {self._group_by}")

    def action_toggle_mine(self) -> None:
        self._mine = not self._mine
        self._save_state()
        self._update_profile()
        self.render_issues()

    def _set_status_view(self, view: StatusView) -> None:
        self._status_view = view
        self._save_state()
        self.render_issues()

    def action_filter_status(self) -> None:
        def selected(view: StatusView | None) -> None:
            if view is not None:
                self._set_status_view(view)
                self.notify(f"\uf0b0 status view → {status_view_label(view)}")

        self.push_screen(StatusFilterModal(self._status_view), selected)

    def action_toggle_done(self) -> None:
        self._set_status_view(toggle_done_in_status_view(self._status_view))
        visible = status_view_matches(self._status_view, "completed")
        self.notify(f"\uf058 Done {'shown' if visible else 'hidden'}")

    def action_filter(self) -> None:
        f = self.query_one("#filter", FilterInput)
        f.add_class("visible")
        f.focus()

    def action_back(self) -> None:
        f = self.query_one("#filter", FilterInput)
        if self._detail_issue is not None:
            self.close_detail()
        elif f.has_class("visible"):
            f.action_dismiss_filter()

    def action_change_status(self) -> None:
        issue = self._current_issue()
        if not issue:
            return
        states = self._states_for_issue(issue)
        if not states:
            return
        opts = []
        for s in sorted(states, key=state_sort_key):
            row = Text()
            row.append(f"{state_icon(s)} ", style=s["color"] or C_SUB)
            row.append(s["name"], style=C_TEXT)
            if s["id"] == issue["state"]["id"]:
                row.append("  ", style=C_GREEN)
            opts.append(Option(row, id=s["id"]))

        def done(state_id: str | None) -> None:
            if state_id and state_id != issue["state"]["id"]:
                self.apply_status(issue, state_id)

        self.push_screen(PickerModal(f"move {issue['identifier']}", opts), done)

    def action_edit_labels(self) -> None:
        issue = self._current_issue()
        if not issue:
            return
        self.open_labels(issue)

    @work(exclusive=True, group="members")
    async def open_labels(self, issue: dict) -> None:
        team = self._team_for_issue(issue)
        if team is None:
            return
        team_key = self._team_key(team)
        labels = self._team_labels.get(team_key)
        if labels is None:
            try:
                data = await self._gql_for_team(
                    team, QL_TEAM_LABELS, {"teamId": team["id"]}
                )
                labels = data["team"]["labels"]["nodes"]
            except Exception as e:
                self.notify(f"linear: {e}", severity="error")
                return
            if self._switching:
                return
            self._team_labels[team_key] = labels
        current_team = self._team_for_issue(issue)
        if current_team is None or self._team_key(current_team) != team_key:
            return
        if not labels:
            self.notify("this team has no labels yet", severity="warning")
            return
        current = {
            lb["id"] for lb in issue["labels"]["nodes"] if lb.get("id")
        }

        def done(ids: list | None) -> None:
            if ids is not None and set(ids) != current:
                self.apply_labels(issue, ids)

        self.push_screen(
            LabelsModal(f"\uf02b labels \u00b7 {issue['identifier']}", labels, current),
            done,
        )

    @work(group="mutate")
    async def apply_labels(self, issue: dict, label_ids: list) -> None:
        try:
            data = await self._gql_for_issue(
                issue, M_LABELS, {"id": issue["id"], "labelIds": label_ids}
            )
            issue["labels"] = data["issueUpdate"]["issue"]["labels"]
        except Exception as e:
            self.notify(f"update failed: {e}", severity="error")
            return
        self._write_team_cache(issue)
        self.render_issues(keep=self._issue_key(issue))
        if self._detail_issue and self._issue_key(self._detail_issue) == self._issue_key(issue):
            self._update_detail_meta(issue)
        self.notify(f"\uf02b {issue['identifier']} \u00b7 labels updated")

    def action_move_project(self) -> None:
        issue = self._current_issue()
        if not issue:
            return
        self.open_project_picker(issue)

    @work(exclusive=True, group="members")
    async def open_project_picker(self, issue: dict) -> None:
        team = self._team_for_issue(issue)
        if team is None:
            return
        team_key = self._team_key(team)
        projects = self._team_projects.get(team_key)
        if projects is None:
            try:
                data = await self._gql_for_team(
                    team, QL_TEAM_PROJECTS, {"teamId": team["id"]}
                )
                projects = data["team"]["projects"]["nodes"]
            except Exception as e:
                self.notify(f"linear: {e}", severity="error")
                return
            if self._switching:
                return
            self._team_projects[team_key] = projects
        current_team = self._team_for_issue(issue)
        if current_team is None or self._team_key(current_team) != team_key:
            return
        current = (issue.get("project") or {}).get("id")
        opts = []
        row = Text()
        row.append("\uf067 ", style=C_GREEN)
        row.append("new project\u2026", style=C_TEXT)
        opts.append(Option(row, id="new:"))
        row = Text()
        row.append("\u25cb ", style=C_DIM)
        row.append("no project", style=C_SUB)
        if current is None:
            row.append("  \uf00c", style=C_GREEN)
        opts.append(Option(row, id="none:"))
        for p in projects:
            row = Text(no_wrap=True, overflow="ellipsis")
            row.append("\uf07b ", style=p.get("color") or C_DIM)
            row.append(p["name"], style=C_TEXT)
            if p["id"] == current:
                row.append("  \uf00c", style=C_GREEN)
            opts.append(Option(row, id=f"proj:{p['id']}"))

        def done(choice: str | None) -> None:
            if choice is None:
                return
            if choice == "new:":
                def named(name: str | None) -> None:
                    if name:
                        self.create_project_and_assign(issue, name)
                self.push_screen(ProjectNameModal(), named)
            elif choice == "none:":
                if current is not None:
                    self.apply_project(issue, None)
            else:
                pid = choice.removeprefix("proj:")
                if pid != current:
                    self.apply_project(issue, pid)

        self.push_screen(
            PickerModal(f"move {issue['identifier']} to\u2026", opts), done
        )

    @work(group="mutate")
    async def create_project_and_assign(self, issue: dict, name: str) -> None:
        team = self._team_for_issue(issue)
        if team is None:
            return
        team_key = self._team_key(team)
        try:
            data = await self._gql_for_issue(
                issue,
                M_PROJECT_CREATE,
                {"name": name, "teamIds": [team["id"]]},
            )
            project = data["projectCreate"]["project"]
        except Exception as e:
            self.notify(f"create project failed: {e}", severity="error")
            return
        self._team_projects.setdefault(team_key, []).append(project)
        self.notify(f"\uf07b created project {project['name']}")
        self.apply_project(issue, project["id"])

    @work(group="mutate")
    async def apply_project(self, issue: dict, project_id: str | None) -> None:
        try:
            data = await self._gql_for_issue(
                issue, M_PROJECT, {"id": issue["id"], "projectId": project_id}
            )
            issue["project"] = data["issueUpdate"]["issue"]["project"]
        except Exception as e:
            self.notify(f"update failed: {e}", severity="error")
            return
        self._write_team_cache(issue)
        self.render_issues(keep=self._issue_key(issue))
        if self._detail_issue and self._issue_key(self._detail_issue) == self._issue_key(issue):
            self._update_detail_meta(issue)
        pname = (issue.get("project") or {}).get("name") or "no project"
        self.notify(f"\uf07b {issue['identifier']} \u2192 {pname}")

    def action_change_priority(self) -> None:
        issue = self._current_issue()
        if not issue:
            return
        opts = []
        for p, label in PRIORITIES:
            row = Text()
            row.append_text(priority_cell(p))
            row.append(f" {label}", style=C_TEXT)
            if p == issue["priority"]:
                row.append("  ", style=C_GREEN)
            opts.append(Option(row, id=str(p)))

        def done(pid: str | None) -> None:
            if pid is not None and int(pid) != issue["priority"]:
                self.apply_priority(issue, int(pid))

        self.push_screen(PickerModal(f"priority · {issue['identifier']}", opts), done)

    def action_change_assignee(self) -> None:
        issue = self._current_issue()
        if not issue or self._team_for_issue(issue) is None:
            return
        self.pick_assignee(issue)

    @work(exclusive=True, group="members")
    async def pick_assignee(self, issue: dict) -> None:
        team = self._team_for_issue(issue)
        if team is None:
            return
        team_key = self._team_key(team)
        members = self._members.get(team_key)
        if members is None:
            try:
                data = await self._gql_for_team(
                    team, QL_MEMBERS, {"teamId": team["id"]}
                )
                members = data["team"]["members"]["nodes"]
            except Exception as e:
                self.notify(f"linear: {e}", severity="error")
                return
            if self._switching:
                return
            self._members[team_key] = members
        current_team = self._team_for_issue(issue)
        if current_team is None or self._team_key(current_team) != team_key:
            return  # user switched teams while fetching
        current = (issue.get("assignee") or {}).get("id")
        opts = []
        viewer = (
            self._workspace_viewers.get(self._issue_workspace(issue), {})
            if self._is_all_workspaces
            else {"id": self._viewer_id, "displayName": self._viewer_name}
        )
        viewer_id = viewer.get("id")
        viewer_name = viewer.get("displayName")
        if viewer_id:
            row = Text(no_wrap=True, overflow="ellipsis")
            row.append("\uf007 ", style=C_BLUE)
            row.append(f"me ({viewer_name})", style=C_TEXT)
            if viewer_id == current:
                row.append("  \uf00c", style=C_GREEN)
            opts.append(Option(row, id=viewer_id))
        for m in members:
            if m["id"] == viewer_id:
                continue
            row = Text(no_wrap=True, overflow="ellipsis")
            row.append("\uf007 ", style=C_MAUVE)
            row.append(m["displayName"], style=C_TEXT)
            if m["id"] == current:
                row.append("  \uf00c", style=C_GREEN)
            opts.append(Option(row, id=m["id"]))
        row = Text()
        row.append("\uf05e ", style=C_DIM)
        row.append("unassign", style=C_SUB)
        if current is None:
            row.append("  \uf00c", style=C_GREEN)
        opts.append(Option(row, id="none:"))

        def done(assignee_id: str | None) -> None:
            if assignee_id is None:
                return
            new_id = None if assignee_id == "none:" else assignee_id
            if new_id != current:
                self.apply_assignee(issue, new_id)

        self.push_screen(PickerModal(f"assign {issue['identifier']}", opts), done)

    def action_add_comment(self) -> None:
        issue = self._current_issue()
        if not issue:
            return

        def done(body: str | None) -> None:
            if body:
                self.submit_comment(issue, body)

        self.push_screen(CommentModal(f" comment on {issue['identifier']}"), done)

    def action_open_browser(self) -> None:
        issue = self._current_issue()
        if issue and issue.get("url"):
            webbrowser.open(issue["url"])
            self.notify(f" opened {issue['identifier']}")

    def action_yank(self) -> None:
        issue = self._current_issue()
        if not issue:
            return
        # old disk caches predate branchName — fall back to a sane guess
        branch = issue.get("branchName") or issue["identifier"].lower()
        opts = []
        for icon, label, value in (
            ("\ue725", "branch", branch),
            ("\uf0c1", "url", issue.get("url") or ""),
            ("\uf02b", "identifier", issue["identifier"]),
        ):
            if not value:
                continue
            row = Text(no_wrap=True, overflow="ellipsis")
            row.append(f"{icon} ", style=C_MAUVE)
            row.append(label, style=C_TEXT)
            row.append(f"  {value}", style=C_DIM)
            opts.append(Option(row, id=value))

        def done(value: str | None) -> None:
            if not value:
                return
            self.copy_to_clipboard(value)
            disp = value if len(value) <= 50 else value[:49] + "…"
            self.notify(f" copied {escape(disp)}")

        self.push_screen(PickerModal(f"yank · {issue['identifier']}", opts), done)


HELP = """ltui - a fast, clean TUI for Linear   https://github.com/Gheat1/ltui

usage: ltui [--version] [--help] [--init-config]

config: ~/.config/ltui/config.json remaps any keybind and sets options
        (auto_refresh_seconds, animations). ltui --init-config writes a
        starter file. changes apply on restart.

auth: LINEAR_API_KEY env var, [workspaces.*] profiles (or legacy api_key)
      in ~/.config/ltui/config.toml, then linear-cli's config.
      use one API key per Linear workspace; chmod the TOML file to 600.

keys: enter open ticket   n new   s status   p priority   c comment
      a assign   l labels   P project   o browser   y yank   / filter
      w workspace / All view   m mine only   v group
      F status view   d show / hide Done   C cycle view
      V one project   t theme
      , settings   j/k navigate   g/G top/bottom   r refresh   ? help
      q quit

views: Active = Todo + Started (not Backlog or Triage). F can include any
       status type; C offers current, next, previous, no cycle, or named cycles.

arrows: up/down move · left/right walk the panes teams - issues - detail
        (right on a ticket opens it; every list takes arrows everywhere)

vim:  j/k move   g/G ends   ctrl+d/u half page   ctrl+f/b page
      [ / ] previous / next group   : command palette

mouse: everything clicks; drag the panel dividers to resize,
       double-click a divider to reset"""


def main() -> None:
    if "--version" in sys.argv or "-v" in sys.argv:
        print(f"ltui {__version__}")
        return
    if "--help" in sys.argv or "-h" in sys.argv:
        print(f"ltui {__version__}\n{HELP}")
        return
    if "--init-config" in sys.argv:
        if LTUI_JSON_CONFIG.exists():
            print(f"config already exists: {LTUI_JSON_CONFIG}")
            return
        LTUI_JSON_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        LTUI_JSON_CONFIG.write_text(CONFIG_TEMPLATE)
        print(f"wrote {LTUI_JSON_CONFIG} — remap keys, tweak options, restart ltui")
        return
    LTUI().run()


if __name__ == "__main__":
    main()
