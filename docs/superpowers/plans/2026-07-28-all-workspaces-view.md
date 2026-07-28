# All Workspaces View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a virtual, interactive “All workspaces” view that merges the single team from every configured Linear workspace while preserving per-workspace authentication, cache isolation, preferences, and mutation routing.

**Architecture:** Represent the aggregate view with a reserved internal profile id (`__all__`) that is selectable and restorable but never owns an API key. A cancellable boot worker loads each real profile concurrently with short-lived clients, renders isolated caches immediately, merges tagged copies of teams/issues in memory, and closes every client. Every issue and team carries its source profile internally; detail queries and mutations open a scoped client for that profile and close it after the request.

**Tech Stack:** Python 3.11+, asyncio, Textual 8, HTTPX, stdlib unittest, uv.

---

### Task 1: Aggregate identity and profile-state semantics

**Files:**
- Modify: `ltui/ltui.py:459-605,815-905,1830-1905`
- Modify: `ltui/tests/test_profiles.py`

- [ ] **Step 1: Write failing unit tests**

Cover: `__all__` is rejected as a user profile name; a Linear CLI `current = "__all__"` name is remapped to the safe single-profile id `linear-cli`; a saved `__all__` selection is restored only when at least two real profiles exist; aggregate preferences use `workspaces/__all__.json`; runtime identities use the collision-free string encoding `f"{len(profile)}:{profile}{remote_id}"` so Textual `Option.id` remains a string and ambiguous concatenations cannot collide.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `cd ltui && uv run --offline python -m unittest tests.test_profiles.ProfileConfigTests tests.test_profiles.ProfileStorageTests -v`

Expected: failures because the aggregate id, resolver behavior, and composite helpers do not exist.

- [ ] **Step 3: Implement the identity helpers**

Add `ALL_WORKSPACES = "__all__"`, reserve it in explicit profile parsing, and remap the Linear CLI fallback if its current workspace uses that name. Add `is_all_workspaces`, `_scoped_id(profile, remote_id)`, `_issue_key(issue)`, `_issue_workspace(issue)`, and `_team_workspace(team)`. Keep API response dictionaries unmodified on disk by tagging shallow copies only when loading them into the model. Use scoped string ids for issue options and every runtime cache keyed by a remote id, including member/label/project lookups. Allow the aggregate grouping preference only in aggregate mode; normal profiles continue to accept only status/project.

- [ ] **Step 4: Run the focused tests**

Expected: profile, storage, and composite-identity tests pass.

### Task 2: Concurrent aggregate boot and cache rendering

**Files:**
- Modify: `ltui/ltui.py:1970-2245,2702-2825`
- Modify: `ltui/tests/test_profiles.py`

- [ ] **Step 1: Write failing aggregate integration tests**

Use two fake profiles with one team each, different viewers, and issues that intentionally share remote issue, team, and project ids. Assert that selecting “All workspaces” renders both cached/live datasets, builds two issue rows, records per-profile viewer/state/team maps, restores `__all__`, and closes every temporary client. Add partial-failure coverage proving a failed workspace cannot erase another workspace’s results or reintroduce stale data.

- [ ] **Step 2: Run the aggregate integration tests and confirm failure**

Run: `cd ltui && uv run --offline python -m unittest tests.test_profiles.AllWorkspacesTests -v`

Expected: failure because the picker and aggregate boot worker are absent.

- [ ] **Step 3: Implement cached and live snapshot loading**

Add a `WorkspaceSnapshot` dataclass and helpers to select the remembered/first team, read that profile’s boot/team cache, and fetch boot+issues with one scoped client. In `_start_all_workspaces`, render available caches synchronously, then run live fetches under an `asyncio.Semaphore(4)` with `gather(return_exceptions=True)`. Close clients in `finally`, write only to the originating profile’s cache, merge successful results, retain valid cached results for failed profiles, and show one concise notification per failed workspace.

Maintain a monotonically increasing `_aggregate_generation`. Increment it synchronously before every accepted aggregate refresh, workspace switch, and aggregate mutation request. Every aggregate worker captures its generation and checks both `generation == self._aggregate_generation` and `active_workspace == __all__` immediately before each cache write and UI merge. A mutation request increments the generation, cancels and awaits the aggregate `boot` workers, then performs its scoped request; this serializes mutation with refresh and ensures even a cancellation-suppressing transport cannot apply stale data. Both manual and automatic aggregate refresh must refuse to start while any `mutate` worker is pending/running, preventing the reverse race where a newer refresh begins during an awaited mutation.

- [ ] **Step 4: Wire the aggregate lifecycle**

Add “All workspaces” to the `w` picker when at least two profiles exist. Branch startup, refresh, switching, state persistence, and profile-card/settings labels for the virtual profile. In aggregate mode, “clear cache” clears every real profile’s cache but does not remove any profile or aggregate preference state; label the action accordingly and test that behavior. Ensure the existing switch transaction increments the aggregate generation synchronously, then cancels and awaits aggregate boot requests before changing credentials.

- [ ] **Step 5: Run aggregate and existing switching tests**

Expected: aggregate tests and all prior switching/race tests pass, including a delayed aggregate response that suppresses cancellation and proves no stale cache/UI write after a switch or mutation, plus a delayed mutation during which manual and automatic refresh attempts launch no aggregate worker.

### Task 3: Merged rendering, filtering, and navigation

**Files:**
- Modify: `ltui/ltui.py:2082-2240,2410-2605,2825-3015`
- Modify: `ltui/tests/test_profiles.py`

- [ ] **Step 1: Write failing rendering tests**

Assert: every aggregate issue row shows its workspace label; `mine` compares each issue with the viewer id for its own profile; grouping cycles through workspace/status/project only in aggregate mode; workspace grouping produces one group per profile; selecting a workspace in the sidebar switches to that real profile.

- [ ] **Step 2: Implement merged rendering**

Maintain `_workspace_states`, `_workspace_viewers`, and `_workspace_teams`. Render a workspace summary in the sidebar, use `_scoped_id` strings for option ids, add compact workspace badges to rows, add a workspace header renderer, and make selection preservation, detail refresh comparisons, and mutation rerendering use `_issue_key` rather than bare remote ids. Scope status/project grouping and project-filter identities by profile so duplicate remote project ids never collapse. Keep normal single-workspace rendering unchanged.

- [ ] **Step 3: Run rendering and full tests**

Expected: duplicate ids, mine filtering, grouping, navigation, and prior single-workspace tests pass.

### Task 4: Route details and mutations to the source workspace

**Files:**
- Modify: `ltui/ltui.py:2030-2078,2257-2410,2913-3285`
- Modify: `ltui/tests/test_profiles.py`

- [ ] **Step 1: Write failing routing tests**

Open an issue from the second profile and assert comments, status/priority/assignee/labels/project/comment mutations, and lazy member/label/project queries use only that profile’s key and close the temporary client. Give both workspaces the same team/project ids and assert member/label/project picker data remains isolated. Assert a mutation cancels an in-flight delayed refresh, updates only that profile’s cache, preserves selection/detail identity, and cannot be overwritten when the stale refresh returns. Press `n` in aggregate mode and assert a workspace picker appears before the composer.

- [ ] **Step 2: Implement scoped request routing**

Refactor response parsing into `_gql_client(client, query, variables)` and add `_gql_for_workspace`, `_gql_for_issue`, and `_gql_for_team`. Normal mode reuses the active long-lived client; aggregate mode creates and closes a client per detail/action request. Route every existing read/mutation call through the issue/team source and preserve the `_switching` mutation guard.

- [ ] **Step 3: Adapt team-specific actions and cache writes**

Resolve the issue’s team and workflow states from its source profile in aggregate mode. Key `_members`, `_team_labels`, and `_team_projects` with `_scoped_id(profile, team_id)`. Update cache writing to serialize only issues/states for the affected source team and strip internal tags. Prompt for a workspace before new-ticket composition, then tag and insert the created issue into the aggregate list without affecting other profiles.

- [ ] **Step 4: Run routing and full tests**

Expected: every action routes to its source profile, clients close, caches remain isolated, and all existing behavior passes.

### Task 5: Documentation and final verification

**Files:**
- Modify: `ltui/README.md:48-70,131-180,190-285,315-375`
- Modify: `ltui/ltui.py:1470-1545,3300-3345`
- Modify: `ltui/tools/screenshots.py`

- [ ] **Step 1: Update user documentation and help**

Document the virtual picker item, workspace badges/grouping, aggregate `mine`, new-ticket workspace prompt, per-request mutation routing, refresh behavior, and the fact that `LINEAR_API_KEY` remains a single-profile override.

- [ ] **Step 2: Keep the offline demo harness compatible**

Add a two-profile aggregate fixture or ensure its existing single-profile fixture remains valid without network access.

- [ ] **Step 3: Run fresh verification**

Run:

```sh
cd ltui
UV_CACHE_DIR=/private/tmp/ltui-uv-cache uv run --offline python -m unittest discover -s tests -v
UV_CACHE_DIR=/private/tmp/ltui-uv-cache uv run --offline python -m compileall -q ltui.py tests tools/screenshots.py
UV_CACHE_DIR=/private/tmp/ltui-uv-cache uv run --offline ltui --version
UV_CACHE_DIR=/private/tmp/ltui-uv-cache uv run --offline ltui --help
```

Expected: zero failures and successful CLI output.

- [ ] **Step 4: Audit the working tree and security invariants**

Run `git diff --check`, inspect `git status --short`, the complete diff, and searches for stale documentation/API-key-like strings. Confirm composite ids, client closure on success/error/cancellation, no key rendering, per-profile cache writes, mutation/switch exclusion, partial-failure isolation, and unchanged legacy/single-profile startup.
