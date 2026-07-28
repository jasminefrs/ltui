# Multi-Workspace Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user configure several Linear workspace API keys and switch between workspace-isolated boards from an in-app `w` picker.

**Architecture:** Keep the existing single-file application, but add small profile-resolution and storage-path models plus pure configuration/path helpers near the current authentication helpers. The active profile selects the API key, cache directory, and state file. Switching is a guarded transaction: synchronously mark the app as switching, cancel and await old read workers, close the credential-bearing HTTP client, clear every workspace-derived field and widget, select the new profile, and start the existing cached boot flow with the new client. Constructors accept storage roots and a client factory so tests never touch the real home directory or network.

**Tech Stack:** Python 3.11+, stdlib `tomllib`/`unittest`, Textual 8, HTTPX, uv.

---

### Task 1: Profile configuration and isolated storage

**Files:**
- Modify: `ltui/ltui.py:35-45,319-459,546-584`
- Create: `ltui/tests/__init__.py`
- Create: `ltui/tests/test_profiles.py`

- [ ] **Step 1: Write failing tests**

Cover new-format TOML parsing, legacy top-level `api_key` compatibility, default-profile selection, safe profile/cache-name validation, profile-specific cache/state paths, source-gated legacy fallback, symlink/path-containment rejection, and `0600` files created atomically inside normalized `0700` directories. Assert that profile/debug representations and configuration errors never contain an API key. Use only `TemporaryDirectory` roots, adapt/skip Unix permission assertions where mode bits are not enforceable, and create `tests/__init__.py` so both discovery and dotted test invocation work.

- [ ] **Step 2: Run tests and confirm failure**

Run: `cd ltui && uv run python -m unittest discover -s tests -v`

Expected: imports fail because `WorkspaceProfile`, `parse_workspace_profiles`, and profile path helpers do not exist.

- [ ] **Step 3: Implement profile/storage helpers**

Add frozen `WorkspaceProfile(name, label, api_key=field(repr=False))`, `ProfileResolution(profiles, active, source, allow_legacy_storage)`, and injected `StoragePaths` dataclasses. Enforce strict component validation (`[A-Za-z0-9_-]+`) at every storage helper boundary and path containment before I/O. Reject symlink targets. Resolve credentials in this exact order:

1. `LINEAR_API_KEY` creates a single `environment` profile.
2. One or more `[workspaces.<name>]` entries use the multi-profile format.
3. A top-level `api_key` creates the backwards-compatible `default` legacy profile.
4. Otherwise use the current `linear-cli` workspace key as a single fallback profile.

For multi-profile configuration, choose the active profile in this order: a valid name from global state, the valid configured `default_workspace`, then the first declared profile. Ignore an invalid saved name; raise a configuration error for an explicitly configured default that does not exist. Never infer legacy behavior from the literal profile name `default`: set `allow_legacy_storage` only when the resolver actually selected the legacy top-level-key format. Use this schema:

```toml
default_workspace = "work"

[workspaces.work]
label = "Work"
api_key = "lin_api_..."
```

Change persistence helpers to accept injected storage paths plus the profile name:

```python
load_state(storage, profile, allow_legacy=False)
save_state(storage, profile, data)
read_cache(storage, profile, name, allow_legacy=False)
write_cache(storage, profile, name, data)
clear_cache(storage, profile)
```

Use `~/.cache/ltui/<profile>/` and `~/.local/state/ltui/workspaces/<profile>.json`. Preserve legacy `state.json` and root cache reads only when `allow_legacy_storage` came from the legacy resolver source. Create and normalize containing directories as `0700`; write through a same-directory uniquely named temporary file opened with `O_CREAT | O_EXCL | O_WRONLY | getattr(os, "O_NOFOLLOW", 0)` and mode `0600`, use explicit `lstat` symlink checks as the portable fallback, flush and `fsync`, then `os.replace` the target and normalize it to `0600`. Add global active-profile state at `~/.local/state/ltui/global.json`. Keep onboarding compatible by saving the top-level `api_key` and then resolving it through the same legacy path. Warn when a manually created multi-profile `config.toml` is readable by group/others, and document `chmod 600 ~/.config/ltui/config.toml`.

- [ ] **Step 4: Run the focused tests**

Run: `cd ltui && uv run python -m unittest discover -s tests -v`

Expected: all profile and storage tests pass.

### Task 2: Runtime workspace switching

**Files:**
- Modify: `ltui/ltui.py:335-425,743-766,1081-1138,1277-1779,2200-2305`
- Modify: `ltui/tests/test_profiles.py`

- [ ] **Step 1: Write failing lifecycle and Textual integration tests**

Run the app with two injected profiles, temporary storage, a fake client factory, and mocked `gql()` responses. Press `w`, select the second option, and assert that the active profile, organization, sole team, state path, cache path, theme/group/mine preferences, and visible widgets all change without a real network call. Add race tests proving that a delayed old-workspace response performs no UI/cache writes, the old client closes, switching is rejected while a mutation is active, mutation GraphQL is rejected during a switch, only one refresh timer exists, and a failed new boot leaves no old workspace data visible. Add a startup test proving invalid multi-profile configuration displays an error and never opens onboarding or overwrites the config; only a dedicated `CredentialsNotFound` condition may launch onboarding.

- [ ] **Step 2: Run the integration test and confirm failure**

Run: `cd ltui && uv run python -m unittest tests.test_profiles.WorkspaceSwitchTests -v`

Expected: failure because the binding/action/switch lifecycle is absent.

- [ ] **Step 3: Implement the picker and switch lifecycle**

Add `switch_workspace` to `DEFAULT_KEYBINDS` and `CONFIG_TEMPLATE`, defaulting to `w`. Build picker rows from profile labels without displaying keys. A synchronous `_begin_workspace_switch()` must validate the target, reject both an already-true `_switching` guard and a running `mutate` worker, and set `_switching = True` before launching any async work. Snapshot workers returned by `cancel_group()` for `boot`, `issues`, `detail`, and `members`; await each and explicitly accept `WorkerCancelled`. Then close the old `httpx.AsyncClient`, replace it using the injected client factory, load profile preferences, persist the active profile, and call the cached boot flow with the new key. Reject mutation GraphQL while `_switching` is true. Clear `_switching` in `finally`, close the current client during app shutdown, and create the auto-refresh timer once in `on_mount()` rather than `_start()`.

Reset all current workspace-derived state before boot: `_teams`, `_issues`, `_states`, `_members`, `_team_labels`, `_team_projects`, `_team`, `_viewer_id`, `_viewer_name`, `_boot_data`, `_org`, `_filter`, `_project_filter`, `_detail_issue`, `_opt_index`, `_issue_by_id`, `_header_indices`, `_group_starts`, and `_refreshing`, plus the filter/loading/detail widgets and the teams/issues/profile/header containers. A failed boot must therefore show an empty/error state, never stale data.

- [ ] **Step 4: Surface the active workspace**

Add a clickable workspace line to the profile card, a workspace item in Settings, and a `w` entry in Help. Automatically select the first team after a cold boot, preserving the existing behavior for workspaces that happen to contain more than one team.

- [ ] **Step 5: Run all tests**

Run: `cd ltui && uv run python -m unittest discover -s tests -v`

Expected: profile, persistence, race, shutdown, permission, and Textual switching tests pass under normal `unittest discover` (with `tests/__init__.py` present).

### Task 3: Documentation and compatibility

**Files:**
- Modify: `ltui/README.md:43-65,112-135,140-205,281-327`
- Modify: `ltui/ltui.py:2700-2744`
- Modify: `ltui/tools/screenshots.py:215-290`

- [ ] **Step 1: Document the multi-workspace schema**

Show a complete two-profile TOML example, explain one API key per workspace, document `w`, profile-isolated cache/state locations, the exact environment/new-format/legacy/linear-cli precedence, active-profile restoration, and legacy top-level `api_key` compatibility.

- [ ] **Step 2: Update CLI help and privacy text**

Mention the profile schema, `w` binding, and workspace-scoped local storage without exposing credentials.

- [ ] **Step 3: Keep the fake screenshot harness compatible**

Inject a fake `ProfileResolution` and accept the profile-aware persistence helper signatures so README screenshot generation remains network-free.

- [ ] **Step 4: Run documentation consistency searches**

Run: `rg -n "one API key at a time|multiple workspaces.*not|config.toml|cache|workspace|switch_workspace" ltui/README.md ltui/ltui.py`

Expected: no stale claim that multiple workspaces are unsupported.

### Task 4: Final verification

**Files:**
- Verify: `ltui/ltui.py`
- Verify: `ltui/tests/test_profiles.py`
- Verify: `ltui/README.md`

- [ ] **Step 1: Run the full test and compile checks**

Run:

```sh
cd ltui
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q ltui.py tests
uv run ltui --version
uv run ltui --help
```

Expected: zero failures and successful CLI output.

- [ ] **Step 2: Inspect the working tree**

Run: `git diff --check && git status --short && git diff --stat && git diff`

Expected: only the planned source, tests, documentation, and plan changes; no credentials or unrelated files.

- [ ] **Step 3: Review security invariants**

Confirm the picker never renders keys, old HTTP clients are closed, read workers are canceled before client replacement, mutations block switching, cache/state paths are profile-scoped, and legacy single-key users still start normally.
