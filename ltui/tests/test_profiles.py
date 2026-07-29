import asyncio
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import ltui
from textual.worker import WorkerCancelled, WorkerState


def profile_resolution() -> ltui.ProfileResolution:
    return ltui.ProfileResolution(
        (
            ltui.WorkspaceProfile("work", "Work", "work-secret"),
            ltui.WorkspaceProfile("personal", "Personal", "personal-secret"),
        ),
        "work",
        "multi",
    )


def boot_data(name: str) -> dict:
    slug = name.lower()
    return {
        "teams": {
            "nodes": [
                {"id": f"{slug}-team", "key": slug[:3].upper(), "name": name, "color": "#123456"}
            ]
        },
        "viewer": {"id": f"{slug}-viewer", "displayName": f"{name} User"},
        "organization": {"name": f"{name} Org"},
    }


def aggregate_issue(name: str) -> dict:
    prefix = name[0].upper()
    return {
        "id": "shared-issue",
        "identifier": f"{prefix}-1",
        "title": f"{name} issue",
        "priority": 3,
        "updatedAt": "2026-07-28T12:00:00Z",
        "createdAt": "2026-07-27T12:00:00Z",
        "url": f"https://linear.app/{name.lower()}/issue",
        "branchName": f"{name.lower()}-issue",
        "assignee": {"id": "shared-viewer", "displayName": f"{name} User"},
        "labels": {"nodes": []},
        "relations": {"nodes": []},
        "inverseRelations": {"nodes": []},
        "project": {"id": "shared-project", "name": f"{name} Project", "color": "#abcdef"},
        "cycle": aggregate_cycle(name, "current"),
        "parent": None,
        "state": {
            "id": "shared-state",
            "name": "Todo",
            "color": "#654321",
            "type": "unstarted",
            "position": 1,
        },
    }


def aggregate_cycle(name: str, mode: str, cycle_id: str | None = None) -> dict:
    number = {"previous": 11, "current": 12, "next": 13}[mode]
    return {
        "id": cycle_id or f"shared-{mode}-cycle",
        "name": f"{name} {mode.title()}",
        "number": number,
        "startsAt": f"2026-07-{number:02d}T00:00:00Z",
        "endsAt": f"2026-07-{number + 6:02d}T00:00:00Z",
        "isActive": mode == "current",
        "isFuture": mode == "next",
        "isPast": mode == "previous",
        "isPrevious": mode == "previous",
        "isNext": mode == "next",
    }


def aggregate_cycles(name: str) -> list[dict]:
    return [
        aggregate_cycle(name, "previous"),
        aggregate_cycle(name, "current"),
        aggregate_cycle(name, "next"),
    ]


def aggregate_status_issues(workspace: str) -> list[dict]:
    issues = []
    for index, state_type in enumerate(ltui.KNOWN_STATUS_TYPES, start=1):
        issue = aggregate_issue(workspace.title())
        issue["id"] = f"{workspace}-{state_type}"
        issue["identifier"] = f"{workspace[:1].upper()}-{index}"
        issue["title"] = f"{workspace} {state_type}"
        issue["state"] = {
            "id": f"{workspace}-{state_type}-state",
            "name": state_type.title(),
            "color": "#654321",
            "type": state_type,
            "position": index,
        }
        issue["_workspace"] = workspace
        issues.append(issue)
    return issues


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(self, key: str, fail_boot: bool = False, delay_boot: bool = False) -> None:
        self.key = key
        self.fail_boot = fail_boot
        self.delay_boot = delay_boot
        self.closed = False
        self.calls: list[str] = []

    async def post(self, _url: str, json: dict) -> FakeResponse:
        query = json["query"]
        self.calls.append(query)
        if query == ltui.QL_BOOT:
            if self.delay_boot:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    # Model a transport that returns a response during cancellation.
                    pass
            if self.fail_boot:
                return FakeResponse({"errors": [{"message": "boot failed"}]})
            name = "Work" if self.key == "work-secret" else "Personal"
            return FakeResponse({"data": boot_data(name)})
        if query == ltui.QL_ISSUES:
            return FakeResponse(
                {
                    "data": {
                        "team": {
                            "issues": {"nodes": []},
                            "states": {"nodes": []},
                        }
                    }
                }
            )
        if query == ltui.QL_CYCLES:
            return FakeResponse(
                {
                    "data": {
                        "team": {
                            "cycles": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False},
                            }
                        }
                    }
                }
            )
        raise AssertionError("unexpected GraphQL query")

    async def aclose(self) -> None:
        self.closed = True


class AggregateFakeClient:
    def __init__(
        self,
        key: str,
        calls: list[tuple],
        fail_boot: bool = False,
        delay_boot: bool = False,
        mutation_gate: asyncio.Event | None = None,
        mutation_started: asyncio.Event | None = None,
        boot_gate: asyncio.Event | None = None,
        boot_started: asyncio.Event | None = None,
        cycles_has_next: bool = False,
        issue_state_type: str = "unstarted",
    ) -> None:
        self.key = key
        self.calls = calls
        self.fail_boot = fail_boot
        self.delay_boot = delay_boot
        self.mutation_gate = mutation_gate
        self.mutation_started = mutation_started
        self.boot_gate = boot_gate
        self.boot_started = boot_started
        self.cycles_has_next = cycles_has_next
        self.issue_state_type = issue_state_type
        self.closed = False

    @property
    def name(self) -> str:
        return "Work" if self.key == "work-secret" else "Personal"

    async def post(self, _url: str, json: dict) -> FakeResponse:
        query = json["query"]
        variables = json.get("variables") or {}
        self.calls.append((self.key, query, variables))
        if query == ltui.QL_BOOT:
            if self.boot_started is not None:
                self.boot_started.set()
            if self.boot_gate is not None:
                await self.boot_gate.wait()
            if self.delay_boot:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    pass
            if self.fail_boot:
                return FakeResponse({"errors": [{"message": "boot failed"}]})
            return FakeResponse(
                {
                    "data": {
                        "teams": {
                            "nodes": [
                                {
                                    "id": "shared-team",
                                    "key": self.name[:1].upper(),
                                    "name": f"{self.name} Team",
                                    "color": "#123456",
                                }
                            ]
                        },
                        "viewer": {
                            "id": f"{self.name.lower()}-viewer",
                            "displayName": f"{self.name} User",
                        },
                        "organization": {"name": f"{self.name} Org"},
                    }
                }
            )
        if query == ltui.QL_ISSUES:
            issue = aggregate_issue(self.name)
            issue["assignee"]["id"] = "personal-viewer"
            issue["state"]["type"] = self.issue_state_type
            issue["state"]["name"] = self.issue_state_type.title()
            return FakeResponse(
                {
                    "data": {
                        "team": {
                            "issues": {"nodes": [issue]},
                            "states": {"nodes": [issue["state"]]},
                        }
                    }
                }
            )
        if query == ltui.QL_CYCLES:
            return FakeResponse(
                {
                    "data": {
                        "team": {
                            "cycles": {
                                "nodes": aggregate_cycles(self.name),
                                "pageInfo": {
                                    "hasNextPage": self.cycles_has_next
                                },
                            },
                        }
                    }
                }
            )
        if query == ltui.M_PRIORITY:
            if self.mutation_started is not None:
                self.mutation_started.set()
            if self.mutation_gate is not None:
                await self.mutation_gate.wait()
            return FakeResponse({"data": {"issueUpdate": {"success": True}}})
        if query == ltui.QL_COMMENTS:
            return FakeResponse(
                {
                    "data": {
                        "issue": {
                            "parent": None,
                            "children": {"nodes": []},
                            "comments": {"nodes": []},
                        }
                    }
                }
            )
        if query == ltui.QL_MEMBERS:
            return FakeResponse(
                {
                    "data": {
                        "team": {
                            "members": {
                                "nodes": [
                                    {
                                        "id": "shared-member",
                                        "displayName": f"{self.name} Member",
                                    }
                                ]
                            }
                        }
                    }
                }
            )
        raise AssertionError("unexpected aggregate GraphQL query")

    async def aclose(self) -> None:
        self.closed = True


class TrackingLTUI(ltui.LTUI):
    def __init__(self, *args, **kwargs) -> None:
        self.interval_calls = 0
        super().__init__(*args, **kwargs)

    def set_interval(self, *args, **kwargs):
        self.interval_calls += 1
        return super().set_interval(*args, **kwargs)


async def wait_for_workers(app: ltui.LTUI) -> None:
    for _ in range(20):
        active = [
            worker
            for worker in app.workers
            if worker.state in (WorkerState.PENDING, WorkerState.RUNNING)
        ]
        if not active:
            return
        try:
            await app.workers.wait_for_complete(active)
        except WorkerCancelled:
            # Aggregate mutations intentionally cancel an in-flight refresh.
            pass
        await asyncio.sleep(0)
    raise AssertionError("workers did not settle")


class ProfileConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.storage = ltui.StoragePaths(
            config=root / "config" / "config.toml",
            linear_config=root / "linear-cli.toml",
            state_root=root / "state",
            cache_root=root / "cache",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_config(self, text: str) -> None:
        self.storage.config.parent.mkdir(parents=True, exist_ok=True)
        self.storage.config.write_text(text)
        if os.name != "nt":
            self.storage.config.chmod(0o600)

    def test_multi_profile_config_and_saved_active(self) -> None:
        self.write_config(
            'default_workspace = "work"\n'
            '[workspaces.work]\nlabel = "Work"\napi_key = "work-secret"\n'
            '[workspaces.personal]\nlabel = "Personal"\napi_key = "home-secret"\n'
        )
        ltui.save_global_state(self.storage, {"active_workspace": "personal"})

        resolved = ltui.resolve_workspace_profiles(self.storage, environ={})

        self.assertEqual(resolved.source, "multi")
        self.assertEqual(resolved.active, "personal")
        self.assertEqual([p.name for p in resolved.profiles], ["work", "personal"])
        self.assertEqual(resolved.profile("work").label, "Work")
        self.assertFalse(resolved.allow_legacy_storage)

    def test_invalid_saved_active_falls_back_but_invalid_default_errors(self) -> None:
        data = {
            "default_workspace": "work",
            "workspaces": {"work": {"label": "Work", "api_key": "secret"}},
        }
        self.assertEqual(
            ltui.parse_workspace_profiles(data, saved_active="missing").active,
            "work",
        )
        data["default_workspace"] = "missing"
        with self.assertRaises(ltui.ProfileConfigError) as caught:
            ltui.parse_workspace_profiles(data)
        self.assertNotIn("secret", str(caught.exception))

    def test_environment_then_multi_then_legacy_then_linear_cli_precedence(self) -> None:
        self.write_config(
            'api_key = "legacy-secret"\n'
            '[workspaces.work]\napi_key = "multi-secret"\n'
        )
        env = ltui.resolve_workspace_profiles(
            self.storage, environ={"LINEAR_API_KEY": "env-secret"}
        )
        self.assertEqual(env.source, "environment")
        self.assertEqual(env.profile(env.active).api_key, "env-secret")

        multi = ltui.resolve_workspace_profiles(self.storage, environ={})
        self.assertEqual(multi.source, "multi")
        self.assertEqual(multi.profile("work").api_key, "multi-secret")

        self.write_config('api_key = "legacy-secret"\n')
        legacy = ltui.resolve_workspace_profiles(self.storage, environ={})
        self.assertEqual(legacy.source, "legacy")
        self.assertTrue(legacy.allow_legacy_storage)

        self.storage.config.unlink()
        self.storage.linear_config.write_text(
            'current = "main"\n[workspaces.main]\napi_key = "cli-secret"\n'
        )
        cli = ltui.resolve_workspace_profiles(self.storage, environ={})
        self.assertEqual(cli.source, "linear-cli")
        self.assertEqual(cli.profile(cli.active).api_key, "cli-secret")

    def test_missing_credentials_is_distinct_from_invalid_configuration(self) -> None:
        with self.assertRaises(ltui.CredentialsNotFound):
            ltui.resolve_workspace_profiles(self.storage, environ={})

        original = 'default_workspace = "missing"\n[workspaces.work]\napi_key = "secret"\n'
        self.write_config(original)
        with self.assertRaises(ltui.ProfileConfigError):
            ltui.resolve_workspace_profiles(self.storage, environ={})
        self.assertEqual(self.storage.config.read_text(), original)

        self.write_config('[workspace.work]\napi_key = "typo-secret"\n')
        with self.assertRaises(ltui.ProfileConfigError):
            ltui.resolve_workspace_profiles(self.storage, environ={})

    def test_profile_repr_redacts_api_key(self) -> None:
        profile = ltui.WorkspaceProfile("work", "Work", "do-not-print-me")
        self.assertNotIn("do-not-print-me", repr(profile))

    @unittest.skipIf(os.name == "nt", "Unix config modes are not enforceable")
    def test_onboarding_key_is_written_privately(self) -> None:
        ltui.save_api_key("saved-secret", self.storage)
        self.assertEqual(stat.S_IMODE(self.storage.config.stat().st_mode), 0o600)
        self.assertEqual(
            stat.S_IMODE(self.storage.config.parent.stat().st_mode), 0o700
        )
        self.assertEqual(
            ltui.resolve_workspace_profiles(self.storage, environ={})
            .profile("default")
            .api_key,
            "saved-secret",
        )

    def test_unsafe_profile_names_are_rejected_without_secret_leaks(self) -> None:
        for name in ("../work", "work/personal", "", ".", "has space"):
            with self.subTest(name=name):
                with self.assertRaises(ltui.ProfileConfigError) as caught:
                    ltui.parse_workspace_profiles(
                        {"workspaces": {name: {"api_key": "do-not-print-me"}}}
                    )
                self.assertNotIn("do-not-print-me", str(caught.exception))

    def test_all_workspace_id_is_reserved_and_restored_only_for_multiple_profiles(self) -> None:
        with self.assertRaises(ltui.ProfileConfigError):
            ltui.parse_workspace_profiles(
                {"workspaces": {"__all__": {"api_key": "secret"}}}
            )
        data = {
            "workspaces": {
                "work": {"api_key": "work-secret"},
                "personal": {"api_key": "personal-secret"},
            }
        }
        self.assertEqual(
            ltui.parse_workspace_profiles(
                data, saved_active=ltui.ALL_WORKSPACES
            ).active,
            ltui.ALL_WORKSPACES,
        )
        single = {"workspaces": {"work": {"api_key": "work-secret"}}}
        self.assertEqual(
            ltui.parse_workspace_profiles(
                single, saved_active=ltui.ALL_WORKSPACES
            ).active,
            "work",
        )
        self.write_config(
            '[workspaces.work]\napi_key = "work-secret"\n'
            '[workspaces.personal]\napi_key = "personal-secret"\n'
        )
        ltui.save_global_state(
            self.storage, {"active_workspace": ltui.ALL_WORKSPACES}
        )
        self.assertEqual(ltui.load_api_key(self.storage), "work-secret")

    def test_linear_cli_reserved_current_name_is_remapped(self) -> None:
        self.storage.linear_config.write_text(
            'current = "__all__"\n[workspaces.__all__]\napi_key = "cli-secret"\n'
        )
        resolved = ltui.resolve_workspace_profiles(self.storage, environ={})
        self.assertEqual(resolved.active, "linear-cli")
        self.assertEqual(resolved.profile("linear-cli").api_key, "cli-secret")

    def test_scoped_ids_are_strings_and_collision_free(self) -> None:
        first = ltui.scoped_id("ab", "c")
        second = ltui.scoped_id("a", "bc")
        self.assertIsInstance(first, str)
        self.assertNotEqual(first, second)

    @unittest.skipIf(os.name == "nt", "Unix config modes are not enforceable")
    def test_insecure_multi_profile_config_warns(self) -> None:
        self.write_config('[workspaces.work]\napi_key = "secret"\n')
        self.storage.config.chmod(0o644)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            ltui.resolve_workspace_profiles(self.storage, environ={})
        warning = stderr.getvalue()
        self.assertIn("chmod 600", warning)
        self.assertNotIn("secret", warning)


class ProfileStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.storage = ltui.StoragePaths(
            config=root / "config.toml",
            linear_config=root / "linear.toml",
            state_root=root / "state",
            cache_root=root / "cache",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_state_and_cache_are_profile_scoped(self) -> None:
        ltui.save_state(self.storage, "work", {"mine": True})
        ltui.save_state(self.storage, "personal", {"mine": False})
        ltui.write_cache(self.storage, "work", "boot", {"organization": "Work"})
        ltui.write_cache(
            self.storage, "personal", "boot", {"organization": "Personal"}
        )

        self.assertTrue(ltui.load_state(self.storage, "work")["mine"])
        self.assertFalse(ltui.load_state(self.storage, "personal")["mine"])
        self.assertEqual(
            ltui.read_cache(self.storage, "work", "boot")["organization"], "Work"
        )
        self.assertEqual(
            ltui.read_cache(self.storage, "personal", "boot")["organization"],
            "Personal",
        )
        self.assertNotEqual(
            ltui.profile_state_path(self.storage, "work"),
            ltui.profile_state_path(self.storage, "personal"),
        )

    def test_legacy_fallback_is_source_gated_not_name_gated(self) -> None:
        self.storage.state_root.mkdir(parents=True)
        self.storage.legacy_state.write_text(json.dumps({"mine": True}))
        self.storage.cache_root.mkdir(parents=True)
        (self.storage.cache_root / "boot.json").write_text(
            json.dumps({"organization": "Legacy"})
        )

        self.assertEqual(ltui.load_state(self.storage, "default"), {})
        self.assertIsNone(ltui.read_cache(self.storage, "default", "boot"))
        self.assertTrue(
            ltui.load_state(self.storage, "default", allow_legacy=True)["mine"]
        )
        self.assertEqual(
            ltui.read_cache(
                self.storage, "default", "boot", allow_legacy=True
            )["organization"],
            "Legacy",
        )

    def test_path_components_and_symlinks_are_rejected(self) -> None:
        for value in ("../x", "x/y", ".", "with space"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ltui.profile_cache_path(self.storage, value, "boot")
                with self.assertRaises(ValueError):
                    ltui.profile_cache_path(self.storage, "work", value)

        if hasattr(os, "symlink"):
            outside = Path(self.temp.name) / "outside"
            outside.mkdir()
            self.storage.cache_root.mkdir()
            (self.storage.cache_root / "work").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                ltui.write_cache(self.storage, "work", "boot", {"x": 1})

    @unittest.skipIf(os.name == "nt", "Unix modes are not enforceable")
    def test_private_permissions_are_set_from_creation_time(self) -> None:
        ltui.save_state(self.storage, "work", {"mine": True})
        ltui.write_cache(self.storage, "work", "boot", {"ok": True})
        state = ltui.profile_state_path(self.storage, "work")
        cache = ltui.profile_cache_path(self.storage, "work", "boot")
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.storage.state_root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(cache.parent.stat().st_mode), 0o700)

    def test_clear_cache_only_removes_the_selected_profile(self) -> None:
        ltui.write_cache(self.storage, "work", "boot", {"x": 1})
        ltui.write_cache(self.storage, "personal", "boot", {"x": 2})
        self.assertEqual(ltui.clear_cache(self.storage, "work"), 1)
        self.assertIsNone(ltui.read_cache(self.storage, "work", "boot"))
        self.assertIsNotNone(ltui.read_cache(self.storage, "personal", "boot"))

    def test_legacy_clear_removes_fallback_cache(self) -> None:
        self.storage.cache_root.mkdir(parents=True)
        (self.storage.cache_root / "boot.json").write_text('{"old":true}')
        self.assertEqual(
            ltui.clear_cache(
                self.storage, "default", allow_legacy=True
            ),
            1,
        )
        self.assertIsNone(
            ltui.read_cache(
                self.storage, "default", "boot", allow_legacy=True
            )
        )


class ViewFilterTests(unittest.TestCase):
    def test_active_is_only_unstarted_and_started(self) -> None:
        view = ltui.DEFAULT_STATUS_VIEW

        self.assertEqual(view.mode, "include")
        self.assertEqual(view.types, frozenset({"unstarted", "started"}))
        self.assertTrue(ltui.status_view_matches(view, "unstarted"))
        self.assertTrue(ltui.status_view_matches(view, "started"))
        for state_type in (
            "triage",
            "backlog",
            "completed",
            "canceled",
            "duplicate",
        ):
            with self.subTest(state_type=state_type):
                self.assertFalse(ltui.status_view_matches(view, state_type))

    def test_everything_and_everything_without_done_are_future_proof(self) -> None:
        everything = ltui.StatusView("exclude", frozenset())
        without_done = ltui.toggle_done_in_status_view(everything)

        self.assertTrue(ltui.status_view_matches(everything, "future-type"))
        self.assertFalse(ltui.status_view_matches(without_done, "completed"))
        self.assertTrue(ltui.status_view_matches(without_done, "future-type"))
        self.assertEqual(
            ltui.toggle_done_in_status_view(without_done), everything
        )

    def test_completed_only_done_toggle_falls_back_to_active(self) -> None:
        completed_only = ltui.StatusView("include", frozenset({"completed"}))

        self.assertEqual(
            ltui.toggle_done_in_status_view(completed_only),
            ltui.DEFAULT_STATUS_VIEW,
        )

    def test_status_view_state_round_trip_and_invalid_fallback(self) -> None:
        custom = ltui.StatusView(
            "include", frozenset({"backlog", "canceled"})
        )
        encoded = ltui.status_view_to_state(custom)

        self.assertEqual(ltui.status_view_from_state(encoded), custom)
        self.assertEqual(
            ltui.status_view_from_state(
                {"mode": "exclude", "types": ["completed"]}
            ),
            ltui.StatusView("exclude", frozenset({"completed"})),
        )
        for invalid in (
            None,
            {},
            {"mode": "include", "types": []},
            {"mode": "unknown", "types": ["started"]},
            {"mode": "include", "types": [1]},
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(
                    ltui.status_view_from_state(invalid),
                    ltui.DEFAULT_STATUS_VIEW,
                )


class GroupedHeaderScrollTests(unittest.IsolatedAsyncioTestCase):
    async def test_returning_to_first_issue_reveals_first_group_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storage = ltui.StoragePaths(
                config=root / "config.toml",
                linear_config=root / "linear.toml",
                state_root=root / "state",
                cache_root=root / "cache",
            )
            ltui.save_state(storage, "work", {"welcomed": True})
            app = ltui.LTUI(
                profile_resolution(),
                storage,
                lambda key: FakeClient(key),
            )
            async with app.run_test(size=(70, 14)) as pilot:
                await wait_for_workers(app)
                issues = []
                for index in range(30):
                    issue = aggregate_issue("Work")
                    issue["id"] = f"issue-{index}"
                    issue["identifier"] = f"WRK-{index}"
                    issue["title"] = f"Grouped issue {index}"
                    issues.append(issue)
                app._set_issues(
                    issues,
                    [issues[0]["state"]],
                    aggregate_cycles("Work"),
                    True,
                )
                app.render_issues()
                await pilot.pause()
                issue_list = app.query_one("#issues", ltui.NavList)
                self.assertTrue(issue_list.get_option_at_index(0).disabled)
                self.assertEqual(issue_list.highlighted, 1)

                for _ in range(8):
                    await pilot.press("j")
                await pilot.pause()
                self.assertGreater(issue_list.scroll_y, 0)
                await pilot.press("g")
                await pilot.pause()
                after_first = issue_list.scroll_y

                issue_list.scroll_home(animate=False, immediate=True)
                for _ in range(8):
                    await pilot.press("j")
                await pilot.pause()
                for _ in range(8):
                    await pilot.press("k")
                await pilot.pause()
                after_cursor_up = issue_list.scroll_y

                self.assertEqual(issue_list.highlighted, 1)
                issue_list.scroll_to(y=8, animate=False, immediate=True)
                await pilot.pause()
                self.assertGreater(issue_list.scroll_y, 0)
                await pilot.press("g")
                await pilot.pause()
                after_first_while_selected = issue_list.scroll_y

                self.assertEqual(
                    (after_first, after_cursor_up, after_first_while_selected),
                    (0, 0, 0),
                )


class ThemeReadabilityTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        ltui.set_palette(False)

    def test_urgent_priority_has_a_visible_marker(self) -> None:
        marker = ltui.priority_cell(1)

        self.assertEqual(marker.plain, "!!!")
        self.assertTrue(marker.spans)

    def test_transparent_theme_modals_use_terminal_background(self) -> None:
        themes = {theme.name: theme for theme in ltui.THEMES}

        for name in ltui.TERMINAL_THEMES:
            with self.subTest(theme=name):
                self.assertEqual(
                    themes[name].variables["ltui-modal-bg"],
                    "ansi_default",
                )

    async def test_transparent_themes_use_terminal_text_and_reverse_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storage = ltui.StoragePaths(
                config=root / "config.toml",
                linear_config=root / "linear.toml",
                state_root=root / "state",
                cache_root=root / "cache",
            )
            ltui.save_state(storage, "work", {"welcomed": True})
            app = ltui.LTUI(
                profile_resolution(),
                storage,
                lambda key: FakeClient(key),
            )
            async with app.run_test(size=(80, 18)) as pilot:
                await wait_for_workers(app)
                issue = aggregate_issue("Work")
                app._set_issues(
                    [issue],
                    [issue["state"]],
                    aggregate_cycles("Work"),
                    True,
                )
                app.render_issues()

                app.theme = "clear"
                await pilot.pause()
                self.assertEqual(ltui.C_TEXT, "default")
                self.assertEqual(ltui.C_SUB, "default")

                app.theme = "system"
                await pilot.pause()
                issue_list = app.query_one("#issues", ltui.NavList)
                highlighted = issue_list.highlighted
                self.assertIsNotNone(highlighted)
                line = (
                    issue_list._index_to_line[highlighted]
                    - issue_list.scroll_offset.y
                )
                visible_segments = [
                    segment
                    for segment in issue_list.render_line(line)
                    if segment.text.strip()
                ]
                self.assertTrue(visible_segments)
                for segment in visible_segments:
                    with self.subTest(text=segment.text):
                        self.assertTrue(segment.style.reverse)
                        self.assertTrue(segment.style.color.is_default)
                        self.assertTrue(segment.style.bgcolor.is_default)


class PanelVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.storage = ltui.StoragePaths(
            config=root / "config.toml",
            linear_config=root / "linear.toml",
            state_root=root / "state",
            cache_root=root / "cache",
        )
        ltui.save_state(self.storage, "work", {"welcomed": True})
        self.calls: list[tuple] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def factory(self, key: str) -> AggregateFakeClient:
        return AggregateFakeClient(key, self.calls)

    async def test_teams_and_issues_panels_toggle_with_safe_focus(self) -> None:
        app = ltui.LTUI(profile_resolution(), self.storage, self.factory)
        async with app.run_test(size=(100, 24)) as pilot:
            await wait_for_workers(app)

            app.action_toggle_teams_panel()
            await pilot.pause()
            self.assertTrue(app.query_one("#sidebar").has_class("collapsed"))
            self.assertTrue(app.query_one("#split-left").has_class("collapsed"))
            self.assertEqual(app.focused.id, "issues")

            app.action_toggle_teams_panel()
            await pilot.pause()
            self.assertFalse(app.query_one("#sidebar").has_class("collapsed"))
            self.assertFalse(app.query_one("#split-left").has_class("collapsed"))
            self.assertEqual(app.focused.id, "teams")

            app.action_toggle_issues_panel()
            await pilot.pause()
            self.assertTrue(app.query_one("#centre").has_class("collapsed"))
            self.assertEqual(app.focused.id, "teams")

    async def test_detail_only_mode_restores_issues_when_detail_closes(self) -> None:
        app = ltui.LTUI(profile_resolution(), self.storage, self.factory)
        async with app.run_test(size=(80, 20)) as pilot:
            await wait_for_workers(app)

            app.action_toggle_detail_panel()
            await wait_for_workers(app)
            await pilot.pause()
            detail = app.query_one("#detail")
            self.assertTrue(detail.has_class("open"))
            self.assertEqual(app.focused.id, "d-scroll")
            split_width = detail.outer_size.width

            app.action_toggle_teams_panel()
            app.action_toggle_issues_panel()
            await pilot.pause()
            self.assertTrue(app.query_one("#sidebar").has_class("collapsed"))
            self.assertTrue(app.query_one("#centre").has_class("collapsed"))
            self.assertFalse(detail.has_class("collapsed"))
            self.assertEqual(
                detail.outer_size.width,
                app.query_one("#main").content_size.width,
            )

            app.action_toggle_issues_panel()
            await pilot.pause()
            self.assertEqual(detail.outer_size.width, split_width)
            app.action_toggle_issues_panel()
            await pilot.pause()

            app.action_toggle_detail_panel()
            await pilot.pause()
            self.assertFalse(app.query_one("#detail").has_class("open"))
            self.assertFalse(app.query_one("#centre").has_class("collapsed"))
            self.assertEqual(app.focused.id, "issues")

    async def test_panel_visibility_is_persisted_per_workspace(self) -> None:
        app = ltui.LTUI(profile_resolution(), self.storage, self.factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            app.action_toggle_teams_panel()
            await pilot.pause()

        state = ltui.load_state(self.storage, "work")
        self.assertFalse(state["teams_panel_visible"])
        self.assertTrue(state["issues_panel_visible"])

        fresh = ltui.LTUI(profile_resolution(), self.storage, self.factory)
        async with fresh.run_test() as pilot:
            await wait_for_workers(fresh)
            await pilot.pause()
            self.assertTrue(fresh.query_one("#sidebar").has_class("collapsed"))
            self.assertFalse(fresh.query_one("#centre").has_class("collapsed"))

    async def test_arrow_navigation_skips_collapsed_panels(self) -> None:
        app = ltui.LTUI(profile_resolution(), self.storage, self.factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)

            app.action_toggle_detail_panel()
            await wait_for_workers(app)
            app.action_toggle_issues_panel()
            app.query_one("#teams", ltui.NavList).focus()
            await pilot.pause()
            app.action_focus_right()
            await pilot.pause()
            self.assertEqual(app.focused.id, "d-scroll")

            app.action_focus_left()
            await pilot.pause()
            self.assertEqual(app.focused.id, "teams")

    def test_panel_toggle_bindings_are_remappable(self) -> None:
        bindings = {binding.key: binding.action for binding in ltui.build_bindings({})}

        self.assertEqual(bindings["1"], "toggle_teams_panel")
        self.assertEqual(bindings["2"], "toggle_issues_panel")
        self.assertEqual(bindings["3"], "toggle_detail_panel")
        self.assertIn("1 / 2 / 3", ltui.HELP)


class CycleViewTests(unittest.TestCase):
    def test_issue_and_cycle_queries_are_split_below_complexity_limit(self) -> None:
        for field in (
            "id",
            "name",
            "number",
            "startsAt",
            "endsAt",
            "isActive",
            "isFuture",
            "isPast",
            "isPrevious",
            "isNext",
        ):
            with self.subTest(field=field):
                self.assertIn(field, ltui.ISSUE_FIELDS)
                self.assertIn(field, ltui.QL_ISSUES)
                self.assertIn(field, ltui.QL_CYCLES)
        self.assertNotIn("cycles(first: 250)", ltui.QL_ISSUES)
        self.assertIn("cycles(first: 250)", ltui.QL_CYCLES)
        self.assertIn("pageInfo { hasNextPage }", ltui.QL_CYCLES)

    def test_cycle_view_state_is_discriminated_and_strict(self) -> None:
        named = ltui.CycleView(
            "named",
            workspace="work",
            team_id="team-1",
            cycle_id="cycle-1",
        )
        self.assertEqual(
            ltui.cycle_view_from_state(ltui.cycle_view_to_state(named)), named
        )
        for mode in ("all", "current", "next", "previous", "none"):
            view = ltui.CycleView(mode)
            self.assertEqual(
                ltui.cycle_view_from_state(ltui.cycle_view_to_state(view)), view
            )
        for invalid in (
            None,
            {},
            {"mode": "future"},
            {"mode": "named", "workspace": "work"},
            {
                "mode": "named",
                "workspace": "",
                "team_id": "team-1",
                "cycle_id": "cycle-1",
            },
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(
                    ltui.cycle_view_from_state(invalid), ltui.DEFAULT_CYCLE_VIEW
                )

    def test_cycle_semantic_and_named_matching(self) -> None:
        active = {
            "id": "shared-cycle",
            "isActive": True,
            "isNext": False,
            "isPrevious": False,
        }
        issue = {"cycle": active}

        self.assertTrue(
            ltui.cycle_view_matches(ltui.CycleView("current"), issue, "work")
        )
        self.assertFalse(
            ltui.cycle_view_matches(ltui.CycleView("next"), issue, "work")
        )
        self.assertFalse(
            ltui.cycle_view_matches(ltui.CycleView("none"), issue, "work")
        )
        self.assertTrue(
            ltui.cycle_view_matches(ltui.CycleView("none"), {}, "work")
        )
        self.assertTrue(
            ltui.cycle_view_matches(
                ltui.CycleView(
                    "named",
                    workspace="work",
                    team_id="shared-team",
                    cycle_id="shared-cycle",
                ),
                issue,
                "work",
            )
        )
        self.assertFalse(
            ltui.cycle_view_matches(
                ltui.CycleView(
                    "named",
                    workspace="personal",
                    team_id="shared-team",
                    cycle_id="shared-cycle",
                ),
                issue,
                "work",
            )
        )

    def test_cycle_ids_are_scoped_across_workspaces(self) -> None:
        self.assertNotEqual(
            ltui.cycle_key("work", "shared-cycle"),
            ltui.cycle_key("personal", "shared-cycle"),
        )


class WorkspaceSwitchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.storage = ltui.StoragePaths(
            config=root / "config.toml",
            linear_config=root / "linear.toml",
            state_root=root / "state",
            cache_root=root / "cache",
        )
        ltui.save_state(
            self.storage,
            "work",
            {"welcomed": True, "mine": False, "group_by": "status", "theme": "mocha"},
        )
        ltui.save_state(
            self.storage,
            "personal",
            {"welcomed": True, "mine": True, "group_by": "project", "theme": "nord"},
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    async def test_picker_switches_workspace_preferences_storage_and_client(self) -> None:
        clients: list[FakeClient] = []

        def factory(key: str) -> FakeClient:
            client = FakeClient(key)
            clients.append(client)
            return client

        app = TrackingLTUI(profile_resolution(), self.storage, factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            self.assertEqual(app._org, "Work Org")
            self.assertEqual(app._team["id"], "work-team")
            timer_count = app.interval_calls

            await pilot.press("w")
            await pilot.pause()
            self.assertIsInstance(app.screen, ltui.PickerModal)
            picker = app.screen.query_one("#picker-list", ltui.NavList)
            displayed = " ".join(
                str(picker.get_option_at_index(index).prompt)
                for index in range(picker.option_count)
            )
            self.assertNotIn("work-secret", displayed)
            self.assertNotIn("personal-secret", displayed)
            await pilot.press("down", "enter")
            await pilot.pause()
            await wait_for_workers(app)

            self.assertEqual(app.active_workspace, "personal")
            self.assertEqual(app._org, "Personal Org")
            self.assertEqual(app._team["id"], "personal-team")
            self.assertTrue(app._mine)
            self.assertEqual(app._group_by, "project")
            self.assertEqual(app.theme, "nord")
            self.assertTrue(clients[0].closed)
            self.assertEqual(app.interval_calls, timer_count)
            self.assertEqual(
                ltui.load_global_state(self.storage)["active_workspace"], "personal"
            )
            self.assertIsNotNone(
                ltui.read_cache(self.storage, "personal", "boot")
            )
            self.assertIn(
                "Personal",
                str(app.query_one("#profile", ltui.Static).content),
            )
        self.assertTrue(clients[-1].closed)

    async def test_switch_guard_blocks_overlap_mutation_and_mutation_graphql(self) -> None:
        clients: list[FakeClient] = []

        def factory(key: str) -> FakeClient:
            client = FakeClient(key)
            clients.append(client)
            return client

        app = ltui.LTUI(profile_resolution(), self.storage, factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            blocker = asyncio.Event()
            mutation = app.run_worker(blocker.wait(), group="mutate")
            await pilot.pause()
            self.assertFalse(app._begin_workspace_switch("personal"))
            mutation.cancel()
            try:
                await mutation.wait()
            except Exception:
                pass

            self.assertTrue(app._begin_workspace_switch("personal"))
            self.assertFalse(app._begin_workspace_switch("personal"))
            with self.assertRaisesRegex(RuntimeError, "switch in progress"):
                await app.gql("mutation { issueUpdate { success } }")
            await wait_for_workers(app)

    async def test_cancelled_old_response_cannot_write_old_cache(self) -> None:
        clients: list[FakeClient] = []

        def factory(key: str) -> FakeClient:
            client = FakeClient(key, delay_boot=(key == "work-secret"))
            clients.append(client)
            return client

        app = ltui.LTUI(profile_resolution(), self.storage, factory)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertTrue(app._begin_workspace_switch("personal"))
            await wait_for_workers(app)
            self.assertIsNone(ltui.read_cache(self.storage, "work", "boot"))
            self.assertEqual(app._org, "Personal Org")
            self.assertTrue(clients[0].closed)

    async def test_failed_new_boot_leaves_no_old_workspace_data(self) -> None:
        def factory(key: str) -> FakeClient:
            return FakeClient(key, fail_boot=(key == "personal-secret"))

        app = ltui.LTUI(profile_resolution(), self.storage, factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            self.assertEqual(app._org, "Work Org")
            self.assertTrue(app._begin_workspace_switch("personal"))
            await pilot.pause()
            await wait_for_workers(app)
            self.assertEqual(app.active_workspace, "personal")
            self.assertIsNone(app._org)
            self.assertEqual(app._teams, [])
            self.assertEqual(app._issues, [])

    async def test_invalid_config_does_not_open_onboarding(self) -> None:
        original = (
            'default_workspace = "missing"\n'
            '[workspaces.work]\napi_key = "secret"\n'
        )
        self.storage.config.write_text(original)
        if os.name != "nt":
            self.storage.config.chmod(0o600)
        app = ltui.LTUI(storage=self.storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertNotIsInstance(app.screen, ltui.OnboardModal)
            self.assertIsNone(app.client)
            self.assertEqual(self.storage.config.read_text(), original)


class AllWorkspacesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.storage = ltui.StoragePaths(
            config=root / "config.toml",
            linear_config=root / "linear.toml",
            state_root=root / "state",
            cache_root=root / "cache",
        )
        for profile in ("work", "personal"):
            ltui.save_state(self.storage, profile, {"welcomed": True})
        ltui.save_state(
            self.storage,
            ltui.ALL_WORKSPACES,
            {"welcomed": True, "group_by": "workspace", "mine": False},
        )
        base = profile_resolution()
        self.resolution = ltui.ProfileResolution(
            base.profiles, ltui.ALL_WORKSPACES, "multi"
        )
        self.calls: list[tuple] = []
        self.clients: list[AggregateFakeClient] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def factory(self, key: str) -> AggregateFakeClient:
        client = AggregateFakeClient(key, self.calls)
        self.clients.append(client)
        return client

    def seed_caches(self) -> None:
        for profile_name, label in (("work", "Work"), ("personal", "Personal")):
            boot = {
                "teams": {
                    "nodes": [
                        {
                            "id": "shared-team",
                            "key": label[0],
                            "name": f"{label} Team",
                            "color": "#123456",
                        }
                    ]
                },
                "viewer": {
                    "id": f"{label.lower()}-viewer",
                    "displayName": f"{label} User",
                },
                "organization": {"name": f"{label} Org"},
            }
            issue = aggregate_issue(label)
            issue["assignee"]["id"] = "personal-viewer"
            ltui.write_cache(self.storage, profile_name, "boot", boot)
            ltui.write_cache(
                self.storage,
                profile_name,
                "team-shared-team",
                {
                    "issues": [issue],
                    "states": [issue["state"]],
                    "cycles": aggregate_cycles(label),
                    "cycles_complete": True,
                },
            )

    async def test_all_view_merges_duplicate_ids_with_workspace_badges(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            self.assertEqual(app.active_workspace, ltui.ALL_WORKSPACES)
            self.assertEqual(len(app._issues), 2)
            self.assertEqual(len(app._issue_by_id), 2)
            self.assertEqual(
                {issue["_workspace"] for issue in app._issues},
                {"work", "personal"},
            )
            self.assertEqual(set(app._workspace_viewers), {"work", "personal"})
            self.assertEqual(app._group_by, "workspace")
            rows = app.query_one("#issues", ltui.NavList)
            displayed = " ".join(
                str(rows.get_option_at_index(index).prompt)
                for index in range(rows.option_count)
            )
            self.assertIn("Work", displayed)
            self.assertIn("Personal", displayed)
            self.assertNotIn("work-secret", displayed)
            self.assertNotIn("personal-secret", displayed)
            self.assertEqual(len(app._header_indices), 2)
            app.action_toggle_group()
            self.assertEqual(app._group_by, "status")
            self.assertEqual(len(app._header_indices), 2)
            app.action_toggle_group()
            self.assertEqual(app._group_by, "project")
            self.assertEqual(len(app._header_indices), 2)
            app.action_toggle_group()
            self.assertEqual(app._group_by, "workspace")
            app._mine = True
            app.render_issues()
            self.assertEqual(
                set(app._opt_index),
                {
                    app._issue_key(
                        next(
                            issue
                            for issue in app._issues
                            if issue["_workspace"] == "personal"
                        )
                    )
                },
            )
            self.assertTrue(all(client.closed for client in self.clients))

    async def test_partial_failure_keeps_cached_workspace_and_live_others(self) -> None:
        self.seed_caches()
        personal_cache = ltui.read_cache(
            self.storage, "personal", "team-shared-team"
        )
        personal_cache["issues"][0]["title"] = "Cached personal issue"
        ltui.write_cache(
            self.storage,
            "personal",
            "team-shared-team",
            personal_cache,
        )

        def failing_factory(key: str) -> AggregateFakeClient:
            client = AggregateFakeClient(
                key,
                self.calls,
                fail_boot=key == "personal-secret",
            )
            self.clients.append(client)
            return client

        app = ltui.LTUI(self.resolution, self.storage, failing_factory)
        async with app.run_test():
            await wait_for_workers(app)
            issues = {issue["_workspace"]: issue for issue in app._issues}
            self.assertEqual(issues["work"]["title"], "Work issue")
            self.assertEqual(
                issues["personal"]["title"], "Cached personal issue"
            )
            issue_queries = [
                key for key, query, _ in self.calls if query == ltui.QL_ISSUES
            ]
            self.assertEqual(issue_queries, ["work-secret"])
            cycle_queries = [
                key for key, query, _ in self.calls if query == ltui.QL_CYCLES
            ]
            self.assertEqual(cycle_queries, ["work-secret"])
            self.assertTrue(all(client.closed for client in self.clients))

    async def test_details_and_duplicate_projects_route_and_remain_distinct(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            personal = next(
                issue for issue in app._issues if issue["_workspace"] == "personal"
            )
            app.show_detail(personal)
            await wait_for_workers(app)
            comment_keys = [
                key for key, query, _ in self.calls if query == ltui.QL_COMMENTS
            ]
            self.assertEqual(comment_keys, ["personal-secret"])
            app.close_detail()
            app.action_pick_project()
            await pilot.pause()
            picker = app.screen.query_one("#picker-list", ltui.NavList)
            self.assertEqual(picker.option_count, 3)
            project_rows = " ".join(
                str(picker.get_option_at_index(index).prompt)
                for index in range(picker.option_count)
            )
            self.assertIn("Work Project", project_rows)
            self.assertIn("Personal Project", project_rows)

    async def test_refresh_rebinds_open_detail_to_the_fresh_issue(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test():
            await wait_for_workers(app)
            personal = next(
                issue for issue in app._issues if issue["_workspace"] == "personal"
            )
            app.show_detail(personal)
            await wait_for_workers(app)

            app._render_all_workspaces(dict(app._workspace_snapshots))

            fresh = next(
                issue for issue in app._issues if issue["_workspace"] == "personal"
            )
            self.assertIs(app._detail_issue, fresh)

    async def test_aggregate_mutation_routes_and_updates_only_source_cache(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test():
            await wait_for_workers(app)
            personal = next(
                issue for issue in app._issues if issue["_workspace"] == "personal"
            )
            app.apply_priority(personal, 1)
            await wait_for_workers(app)
            mutation_keys = [
                key for key, query, _ in self.calls if query == ltui.M_PRIORITY
            ]
            self.assertEqual(mutation_keys, ["personal-secret"])
            cached = ltui.read_cache(
                self.storage, "personal", "team-shared-team"
            )
            self.assertEqual(cached["issues"][0]["priority"], 1)
            work_cache = ltui.read_cache(
                self.storage, "work", "team-shared-team"
            )
            self.assertEqual(work_cache["issues"][0]["priority"], 3)
            self.assertTrue(all(client.closed for client in self.clients))

    async def test_duplicate_team_ids_keep_member_queries_isolated(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            work = next(i for i in app._issues if i["_workspace"] == "work")
            personal = next(
                i for i in app._issues if i["_workspace"] == "personal"
            )
            app.pick_assignee(work)
            await wait_for_workers(app)
            work_picker = app.screen.query_one("#picker-list", ltui.NavList)
            work_rows = " ".join(
                str(work_picker.get_option_at_index(index).prompt)
                for index in range(work_picker.option_count)
            )
            self.assertIn("Work Member", work_rows)
            self.assertNotIn("Personal Member", work_rows)
            await pilot.press("escape")
            await pilot.pause()

            app.pick_assignee(personal)
            await wait_for_workers(app)
            personal_picker = app.screen.query_one("#picker-list", ltui.NavList)
            personal_rows = " ".join(
                str(personal_picker.get_option_at_index(index).prompt)
                for index in range(personal_picker.option_count)
            )
            self.assertIn("Personal Member", personal_rows)
            self.assertNotIn("Work Member", personal_rows)
            self.assertEqual(len(app._members), 2)

    async def test_new_ticket_prompts_for_workspace_and_picker_offers_all(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            app.action_new_ticket()
            await pilot.pause()
            self.assertIsInstance(app.screen, ltui.PickerModal)
            choices = app.screen.query_one("#picker-list", ltui.NavList)
            self.assertEqual(choices.option_count, 2)

        normal = ltui.LTUI(profile_resolution(), self.storage, self.factory)
        async with normal.run_test() as pilot:
            await wait_for_workers(normal)
            await pilot.press("w")
            await pilot.pause()
            picker = normal.screen.query_one("#picker-list", ltui.NavList)
            labels = " ".join(
                str(picker.get_option_at_index(index).prompt)
                for index in range(picker.option_count)
            )
            self.assertEqual(picker.option_count, 3)
            self.assertIn("All workspaces", labels)

    async def test_clear_all_caches_preserves_aggregate_preferences(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test():
            await wait_for_workers(app)
            self.assertIsNotNone(
                ltui.read_cache(self.storage, "work", "boot")
            )
            self.assertIsNotNone(
                ltui.read_cache(self.storage, "personal", "boot")
            )
            self.assertEqual(app._clear_active_cache(), 4)
            self.assertIsNone(ltui.read_cache(self.storage, "work", "boot"))
            self.assertIsNone(
                ltui.read_cache(self.storage, "personal", "boot")
            )
            self.assertEqual(
                ltui.load_state(self.storage, ltui.ALL_WORKSPACES)["group_by"],
                "workspace",
            )

    async def test_mutation_invalidates_cancellation_suppressing_refresh(self) -> None:
        self.seed_caches()

        def delayed_factory(key: str) -> AggregateFakeClient:
            client = AggregateFakeClient(key, self.calls, delay_boot=True)
            self.clients.append(client)
            return client

        app = ltui.LTUI(self.resolution, self.storage, delayed_factory)
        async with app.run_test() as pilot:
            for _ in range(20):
                await pilot.pause(0.02)
                if sum(query == ltui.QL_BOOT for _, query, _ in self.calls) == 2:
                    break
            personal = next(
                issue for issue in app._issues if issue["_workspace"] == "personal"
            )
            app.apply_priority(personal, 1)
            await wait_for_workers(app)
            await pilot.pause()
            cached = ltui.read_cache(
                self.storage, "personal", "team-shared-team"
            )
            self.assertEqual(cached["issues"][0]["priority"], 1)
            current = next(
                issue for issue in app._issues if issue["_workspace"] == "personal"
            )
            self.assertEqual(current["priority"], 1)

    async def test_refresh_is_blocked_while_mutation_is_running(self) -> None:
        gate = asyncio.Event()
        started = asyncio.Event()

        def gated_factory(key: str) -> AggregateFakeClient:
            client = AggregateFakeClient(
                key,
                self.calls,
                mutation_gate=gate,
                mutation_started=started,
            )
            self.clients.append(client)
            return client

        app = ltui.LTUI(self.resolution, self.storage, gated_factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            personal = next(
                issue for issue in app._issues if issue["_workspace"] == "personal"
            )
            app.apply_priority(personal, 1)
            await asyncio.wait_for(started.wait(), timeout=2)
            boot_count = sum(
                query == ltui.QL_BOOT for _, query, _ in self.calls
            )
            app.action_refresh()
            app._auto_refresh_board()
            await pilot.pause()
            self.assertEqual(
                sum(query == ltui.QL_BOOT for _, query, _ in self.calls),
                boot_count,
            )
            gate.set()
            await wait_for_workers(app)


class StatusViewInteractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.storage = ltui.StoragePaths(
            config=root / "config.toml",
            linear_config=root / "linear.toml",
            state_root=root / "state",
            cache_root=root / "cache",
        )
        for profile in ("work", "personal"):
            ltui.save_state(self.storage, profile, {"welcomed": True})
        ltui.save_state(
            self.storage,
            ltui.ALL_WORKSPACES,
            {"welcomed": True, "group_by": "workspace"},
        )
        base = profile_resolution()
        self.resolution = ltui.ProfileResolution(
            base.profiles, ltui.ALL_WORKSPACES, "multi"
        )
        self.calls: list[tuple] = []
        self.clients: list[AggregateFakeClient] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def factory(self, key: str) -> AggregateFakeClient:
        client = AggregateFakeClient(key, self.calls)
        self.clients.append(client)
        return client

    async def test_aggregate_status_views_cover_every_workflow_type(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test():
            await wait_for_workers(app)
            app._issues = aggregate_status_issues("work") + aggregate_status_issues(
                "personal"
            )
            app._issue_by_id = {
                app._issue_key(issue): issue for issue in app._issues
            }

            app.render_issues()
            self.assertEqual(len(app._opt_index), 4)
            self.assertEqual(
                {
                    issue["state"]["type"]
                    for issue in app._issues
                    if app._issue_key(issue) in app._opt_index
                },
                {"unstarted", "started"},
            )

            app.action_toggle_done()
            self.assertEqual(
                {
                    issue["state"]["type"]
                    for issue in app._issues
                    if app._issue_key(issue) in app._opt_index
                },
                {"unstarted", "started", "completed"},
            )

            app._set_status_view(ltui.EVERYTHING_STATUS_VIEW)
            self.assertEqual(len(app._opt_index), 14)
            app.action_toggle_done()
            self.assertNotIn(
                "completed",
                {
                    issue["state"]["type"]
                    for issue in app._issues
                    if app._issue_key(issue) in app._opt_index
                },
            )
            self.assertIn(
                "canceled",
                {
                    issue["state"]["type"]
                    for issue in app._issues
                    if app._issue_key(issue) in app._opt_index
                },
            )

            app._set_status_view(
                ltui.StatusView("include", frozenset({"backlog", "canceled"}))
            )
            self.assertEqual(
                {
                    issue["state"]["type"]
                    for issue in app._issues
                    if app._issue_key(issue) in app._opt_index
                },
                {"backlog", "canceled"},
            )

    async def test_status_picker_and_preferences_are_view_scoped(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            await pilot.press("F")
            await pilot.pause()
            self.assertIsInstance(app.screen, ltui.StatusFilterModal)
            rows = app.screen.query_one("#status-list", ltui.NavList)
            displayed = " ".join(
                str(rows.get_option_at_index(index).prompt)
                for index in range(rows.option_count)
            )
            for label in (
                "Active",
                "Everything",
                "Triage",
                "Backlog",
                "Todo",
                "Started",
                "Done",
                "Canceled",
                "Duplicate",
            ):
                self.assertIn(label, displayed)

            app.screen._sel = {"triage", "canceled"}
            app.screen.action_apply()
            await pilot.pause()
            saved_all = ltui.load_state(self.storage, ltui.ALL_WORKSPACES)
            self.assertEqual(
                ltui.status_view_from_state(saved_all["status_view"]),
                ltui.StatusView("include", frozenset({"triage", "canceled"})),
            )
            self.assertNotIn("status_view", ltui.load_state(self.storage, "work"))


class CycleViewInteractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.storage = ltui.StoragePaths(
            config=root / "config.toml",
            linear_config=root / "linear.toml",
            state_root=root / "state",
            cache_root=root / "cache",
        )
        for profile in ("work", "personal"):
            ltui.save_state(self.storage, profile, {"welcomed": True})
        ltui.save_state(
            self.storage,
            ltui.ALL_WORKSPACES,
            {"welcomed": True, "group_by": "workspace"},
        )
        base = profile_resolution()
        self.resolution = ltui.ProfileResolution(
            base.profiles, ltui.ALL_WORKSPACES, "multi"
        )
        self.calls: list[tuple] = []
        self.clients: list[AggregateFakeClient] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def factory(self, key: str) -> AggregateFakeClient:
        client = AggregateFakeClient(key, self.calls)
        self.clients.append(client)
        return client

    def seed_legacy_caches(self) -> None:
        for profile_name, label in (("work", "Work"), ("personal", "Personal")):
            boot = boot_data(label)
            boot["teams"]["nodes"][0]["id"] = "shared-team"
            issue = aggregate_issue(label)
            ltui.write_cache(self.storage, profile_name, "boot", boot)
            ltui.write_cache(
                self.storage,
                profile_name,
                "team-shared-team",
                {"issues": [issue], "states": [issue["state"]]},
            )

    async def test_cycle_picker_modes_and_duplicate_ids_are_isolated(self) -> None:
        app = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with app.run_test() as pilot:
            await wait_for_workers(app)
            app.action_pick_cycle()
            await pilot.pause()
            picker = app.screen.query_one("#picker-list", ltui.NavList)
            self.assertEqual(picker.option_count, 11)
            displayed = " ".join(
                str(picker.get_option_at_index(index).prompt)
                for index in range(picker.option_count)
            )
            for label in (
                "All cycles",
                "Current",
                "Next",
                "Previous",
                "No cycle",
                "Work Current",
                "Personal Current",
            ):
                self.assertIn(label, displayed)
            await pilot.press("escape")
            await pilot.pause()

            app._set_cycle_view(ltui.CycleView("current"))
            self.assertEqual(len(app._opt_index), 2)
            app._set_cycle_view(
                ltui.CycleView(
                    "named",
                    workspace="personal",
                    team_id="shared-team",
                    cycle_id="shared-current-cycle",
                )
            )
            self.assertEqual(len(app._opt_index), 1)
            selected = next(
                issue
                for issue in app._issues
                if app._issue_key(issue) in app._opt_index
            )
            self.assertEqual(selected["_workspace"], "personal")
            saved = ltui.load_state(self.storage, ltui.ALL_WORKSPACES)
            self.assertEqual(
                ltui.cycle_view_from_state(saved["cycle_view"]), app._cycle_view
            )
            self.assertNotIn("cycle_view", ltui.load_state(self.storage, "work"))

    async def test_legacy_cache_without_cycles_remains_usable(self) -> None:
        self.seed_legacy_caches()

        def delayed_factory(key: str) -> AggregateFakeClient:
            client = AggregateFakeClient(key, self.calls, delay_boot=True)
            self.clients.append(client)
            return client

        app = ltui.LTUI(self.resolution, self.storage, delayed_factory)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(len(app._issues), 2)
            self.assertEqual(app._workspace_cycles, {"work": [], "personal": []})

    async def test_stale_named_cycle_resets_only_for_complete_connections(self) -> None:
        missing = ltui.CycleView(
            "named",
            workspace="work",
            team_id="shared-team",
            cycle_id="missing-cycle",
        )
        state = ltui.load_state(self.storage, ltui.ALL_WORKSPACES)
        state["cycle_view"] = ltui.cycle_view_to_state(missing)
        ltui.save_state(self.storage, ltui.ALL_WORKSPACES, state)

        complete = ltui.LTUI(self.resolution, self.storage, self.factory)
        async with complete.run_test():
            await wait_for_workers(complete)
            self.assertEqual(complete._cycle_view, ltui.DEFAULT_CYCLE_VIEW)

        state["cycle_view"] = ltui.cycle_view_to_state(missing)
        ltui.save_state(self.storage, ltui.ALL_WORKSPACES, state)

        def truncated_factory(key: str) -> AggregateFakeClient:
            client = AggregateFakeClient(
                key,
                self.calls,
                cycles_has_next=key == "work-secret",
            )
            self.clients.append(client)
            return client

        truncated = ltui.LTUI(self.resolution, self.storage, truncated_factory)
        async with truncated.run_test():
            await wait_for_workers(truncated)
            self.assertEqual(truncated._cycle_view, missing)

    async def test_named_cycle_resets_when_switching_teams(self) -> None:
        normal = ltui.LTUI(profile_resolution(), self.storage, self.factory)
        async with normal.run_test():
            await wait_for_workers(normal)
            normal._set_cycle_view(
                ltui.CycleView(
                    "named",
                    workspace="work",
                    team_id="shared-team",
                    cycle_id="shared-current-cycle",
                )
            )
            normal.load_team(
                {
                    "id": "other-team",
                    "key": "OTH",
                    "name": "Other",
                    "color": "#123456",
                }
            )
            await wait_for_workers(normal)
            self.assertEqual(normal._cycle_view, ltui.DEFAULT_CYCLE_VIEW)
            saved = ltui.load_state(self.storage, "work")
            self.assertEqual(
                ltui.cycle_view_from_state(saved["cycle_view"]),
                ltui.DEFAULT_CYCLE_VIEW,
            )

    async def test_filter_changes_during_refresh_apply_to_live_merge(self) -> None:
        self.seed_legacy_caches()
        state = ltui.load_state(self.storage, ltui.ALL_WORKSPACES)
        state["status_view"] = ltui.status_view_to_state(
            ltui.EVERYTHING_STATUS_VIEW
        )
        ltui.save_state(self.storage, ltui.ALL_WORKSPACES, state)
        gate = asyncio.Event()

        def gated_factory(key: str) -> AggregateFakeClient:
            client = AggregateFakeClient(
                key,
                self.calls,
                boot_gate=gate,
                issue_state_type="completed",
            )
            self.clients.append(client)
            return client

        app = ltui.LTUI(self.resolution, self.storage, gated_factory)
        async with app.run_test() as pilot:
            for _ in range(20):
                await pilot.pause(0.02)
                if sum(query == ltui.QL_BOOT for _, query, _ in self.calls) == 2:
                    break
            app._set_status_view(ltui.DEFAULT_STATUS_VIEW)
            app._set_cycle_view(ltui.CycleView("current"))
            gate.set()
            await wait_for_workers(app)
            self.assertEqual(app._status_view, ltui.DEFAULT_STATUS_VIEW)
            self.assertEqual(app._cycle_view, ltui.CycleView("current"))
            self.assertEqual(
                {issue["state"]["type"] for issue in app._issues}, {"completed"}
            )
            self.assertEqual(app._opt_index, {})


if __name__ == "__main__":
    unittest.main()
