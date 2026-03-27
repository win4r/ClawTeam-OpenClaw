"""Tests for clawteam.templates — loading, parsing, and variable substitution."""

import pytest

from clawteam.templates import (
    AgentDef,
    FeatureScope,
    LaunchBriefSections,
    LaunchExecutionResult,
    LaunchReferenceError,
    LaunchTaskBuildError,
    LaunchTaskInput,
    LaunchTemplateError,
    NormalizedLaunchBrief,
    ScopeTaskValidationError,
    PreparedTaskLaunchBrief,
    TaskDef,
    TaskLaunchBriefView,
    TemplateDef,
    _SafeDict,
    build_launch_task_input,
    execute_template_launch,
    find_scope_audit_warnings,
    find_scope_inventions,
    find_scope_tightening,
    inject_resolved_scope_context,
    list_templates,
    render_resolved_scope_context,
    load_template,
    normalize_launch_brief,
    parse_feature_scope_block,
    parse_launch_brief,
    prepare_task_launch_brief,
    read_feature_scope_metadata,
    read_launch_brief_metadata,
    read_task_launch_brief,
    render_task,
    render_task_brief,
    resolve_template_topology,
)


class TestRenderTask:
    def test_basic_substitution(self):
        result = render_task("Analyze {goal} for {team_name}", goal="AAPL", team_name="alpha")
        assert result == "Analyze AAPL for alpha"

    def test_unknown_placeholders_kept(self):
        """Variables we don't provide should stay as {placeholder}."""
        result = render_task("Hello {name}, team is {team_name}", name="bob")
        assert result == "Hello bob, team is {team_name}"

    def test_no_variables(self):
        result = render_task("plain text with no placeholders")
        assert result == "plain text with no placeholders"

    def test_empty_string(self):
        assert render_task("") == ""

    def test_multiple_same_variable(self):
        result = render_task("{x} and {x}", x="foo")
        assert result == "foo and foo"


class _FakeCreatedTask:
    def __init__(self, task_id: str):
        self.id = task_id


class _FakeTask:
    def __init__(self, *, description: str = "", metadata: dict[str, object] | None = None):
        self.description = description
        self.metadata = metadata or {}


class _FakeTaskStore:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def create(self, *, subject: str, description: str, owner: str, blocked_by: list[str], metadata: dict[str, object]):
        task_id = f"task-{len(self.calls) + 1}"
        call = {
            "subject": subject,
            "description": description,
            "owner": owner,
            "blocked_by": blocked_by,
            "metadata": metadata,
            "id": task_id,
        }
        self.calls.append(call)
        return _FakeCreatedTask(task_id)


class TestLaunchBrief:
    def test_normalize_launch_brief_marks_prose_fallback(self):
        normalized = normalize_launch_brief(
            source_request="Ship the feature safely",
            leader_brief="Clarify scope and acceptance criteria.",
        )

        assert normalized == NormalizedLaunchBrief(
            format="prose_fallback",
            sections=LaunchBriefSections(
                source_request="Ship the feature safely",
                scoped_brief="Clarify scope and acceptance criteria.",
                unknowns=[],
                leader_assumptions=[],
                out_of_scope=[],
            ),
        )

    def test_parse_launch_brief_falls_back_to_scoped_brief(self):
        parsed = parse_launch_brief(
            source_request="Ship the feature safely",
            leader_brief="Clarify scope and acceptance criteria.",
        )

        assert parsed == LaunchBriefSections(
            source_request="Ship the feature safely",
            scoped_brief="Clarify scope and acceptance criteria.",
            unknowns=[],
            leader_assumptions=[],
            out_of_scope=[],
        )

    def test_normalize_launch_brief_empty(self):
        normalized = normalize_launch_brief(
            source_request="Original request",
            leader_brief="   ",
        )

        assert normalized == NormalizedLaunchBrief(
            format="empty",
            sections=LaunchBriefSections(
                source_request="Original request",
                scoped_brief="",
                unknowns=[],
                leader_assumptions=[],
                out_of_scope=[],
            ),
        )

    def test_normalize_launch_brief_structured_sections(self):
        normalized = normalize_launch_brief(
            source_request="Original request",
            leader_brief="""
## Source Request
User asked for a safe rollout.

## Scoped Brief
Deliver the smallest safe change.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""".strip(),
        )

        assert normalized.format == "structured_sections"
        assert normalized.sections.source_request == "User asked for a safe rollout."
        assert normalized.sections.scoped_brief == "Deliver the smallest safe change."
        assert normalized.sections.unknowns == ["final prod env"]
        assert normalized.sections.leader_assumptions == ["existing tests are representative"]
        assert normalized.sections.out_of_scope == ["dashboard rewrite"]

    def test_parse_launch_brief_structured_sections(self):
        parsed = parse_launch_brief(
            source_request="Original request",
            leader_brief="""
## Source Request
User asked for a safe rollout.

## Scoped Brief
Deliver the smallest safe change.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""".strip(),
        )

        assert parsed.source_request == "User asked for a safe rollout."
        assert parsed.scoped_brief == "Deliver the smallest safe change."
        assert parsed.unknowns == ["final prod env"]
        assert parsed.leader_assumptions == ["existing tests are representative"]
        assert parsed.out_of_scope == ["dashboard rewrite"]

    def test_parse_feature_scope_block_merges_structured_scope_sections(self):
        normalized = normalize_launch_brief(
            source_request="Ship the feature safely",
            leader_brief="""
## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the minimal safe fix.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## FEATURE_SCOPE
{"scoped_brief":"Deliver only the minimal safe fix.","in_scope":["Deliver only the minimal safe fix."],"risks_blockers":["Final prod env remains unverified."],"recommended_next_step":"setup","execution_shape":"backend-only","change_budget":{"allowed_layers":["backend","api"],"allowed_operations":["edit-existing","add-backend-module"],"allowed_roots":["server/"],"forbidden_layers":["web-ui","mobile-ui"]},"initial_targets":[{"kind":"api-handler","path":"server/src/routes/member.ts","exists":true,"why_in_scope":"member API change required by scoped brief","evidence":["rg hit: server/src/routes/member.ts"]}]}
""".strip(),
        )

        parsed = parse_feature_scope_block(
            """
## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the minimal safe fix.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## FEATURE_SCOPE
{"scoped_brief":"Deliver only the minimal safe fix.","in_scope":["Deliver only the minimal safe fix."],"risks_blockers":["Final prod env remains unverified."],"recommended_next_step":"setup","execution_shape":"backend-only","change_budget":{"allowed_layers":["backend","api"],"allowed_operations":["edit-existing","add-backend-module"],"allowed_roots":["server/"],"forbidden_layers":["web-ui","mobile-ui"]},"initial_targets":[{"kind":"api-handler","path":"server/src/routes/member.ts","exists":true,"why_in_scope":"member API change required by scoped brief","evidence":["rg hit: server/src/routes/member.ts"]}]}
""".strip(),
            normalized=normalized,
        )

        assert parsed == FeatureScope(
            source_request="Ship the feature safely",
            scoped_brief="Deliver only the minimal safe fix.",
            in_scope=["Deliver only the minimal safe fix."],
            unknowns=["final prod env"],
            leader_assumptions=["existing tests are representative"],
            out_of_scope=["dashboard rewrite"],
            risks_blockers=["Final prod env remains unverified."],
            recommended_next_step="setup",
            execution_shape="backend-only",
            change_budget={"allowed_layers": ["backend", "api"], "allowed_operations": ["edit-existing", "add-backend-module"], "allowed_roots": ["server/"], "forbidden_layers": ["web-ui", "mobile-ui"]},
            initial_targets=[{"kind": "api-handler", "path": "server/src/routes/member.ts", "exists": True, "why_in_scope": "member API change required by scoped brief", "evidence": ["rg hit: server/src/routes/member.ts"]}],
        )

    def test_parse_feature_scope_block_requires_execution_shape(self):
        with pytest.raises(
            ScopeTaskValidationError,
            match=r"FEATURE_SCOPE\.execution_shape.*ui-only \| backend-only \| full-stack",
        ):
            parse_feature_scope_block(
                """
## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the minimal safe fix.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## FEATURE_SCOPE
{"scoped_brief":"Deliver only the minimal safe fix.","in_scope":["Deliver only the minimal safe fix."],"risks_blockers":["Final prod env remains unverified."],"recommended_next_step":"setup"}
""".strip(),
            )

    def test_parse_feature_scope_block_rejects_invalid_execution_shape(self):
        with pytest.raises(
            ScopeTaskValidationError,
            match=r"FEATURE_SCOPE\.execution_shape.*ui-only \| backend-only \| full-stack",
        ):
            parse_feature_scope_block(
                """
## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the minimal safe fix.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## FEATURE_SCOPE
{"scoped_brief":"Deliver only the minimal safe fix.","in_scope":["Deliver only the minimal safe fix."],"risks_blockers":["Final prod env remains unverified."],"recommended_next_step":"setup","execution_shape":"frontend-only","change_budget":{"allowed_layers":["web-ui"],"allowed_operations":["edit-existing"],"allowed_roots":["dashboard/"],"forbidden_layers":["backend"]},"initial_targets":[{"kind":"web-page","path":"dashboard/src/pages/members.tsx","exists":true,"why_in_scope":"member list UI exists","evidence":["rg hit: dashboard/src/pages/members.tsx"]}]}
""".strip(),
            )

    def test_parse_feature_scope_block_rejects_ui_scope_without_validated_initial_target(self):
        with pytest.raises(
            ScopeTaskValidationError,
            match="initial_targets must include at least one validated web target",
        ):
            parse_feature_scope_block(
                """
## Source Request
Polish the member list page UI only

## Scoped Brief
Deliver only the member list UI update.

## Unknowns
- none

## Leader Assumptions
- existing web route should already exist

## Out of Scope
- backend rewrite

## FEATURE_SCOPE
{"scoped_brief":"Deliver only the member list UI update.","in_scope":["member list UI update"],"unknowns":["none"],"leader_assumptions":["existing web route should already exist"],"out_of_scope":["backend rewrite"],"risks_blockers":["none"],"recommended_next_step":"setup","execution_shape":"ui-only","change_budget":{"allowed_layers":["web-ui"],"allowed_operations":["edit-existing","add-ui-component"],"allowed_roots":["dashboard/"],"forbidden_layers":["backend","api","schema","db","crawler","auth","mobile-ui"]},"initial_targets":[]}
""".strip(),
            )

    def test_find_scope_inventions_flags_explicit_additive_entities_missing_from_source_request(self):
        inventions = find_scope_inventions(
            source_request="Add a small UI polish to the member list.",
            scoped_brief="Add a new API endpoint and schema for member list data.",
        )

        assert inventions == ["endpoint", "api", "schema"]

    def test_find_scope_inventions_requires_new_to_attach_to_risky_entity(self):
        inventions = find_scope_inventions(
            source_request="Polish the member list UI.",
            scoped_brief="Document new acceptance notes for the existing member list behavior.",
        )

        assert inventions == []

    def test_find_scope_inventions_allows_entities_when_already_in_source_request(self):
        inventions = find_scope_inventions(
            source_request="Add a new API endpoint for member list data.",
            scoped_brief="Implement the API endpoint and validate the response.",
        )

        assert inventions == []

    def test_find_scope_inventions_does_not_treat_new_vocabulary_alone_as_invention(self):
        inventions = find_scope_inventions(
            source_request="Polish the member list UI.",
            scoped_brief="Clarify the API behavior used by the current member list UI.",
        )

        assert inventions == []

    def test_find_scope_inventions_ignores_negated_additive_language(self):
        inventions = find_scope_inventions(
            source_request="Polish the member list UI.",
            scoped_brief="Clarify the API behavior used by the current member list UI without adding new endpoints.",
        )

        assert inventions == []

    def test_find_scope_inventions_accepts_bare_new_without_risky_entity_phrase(self):
        inventions = find_scope_inventions(
            source_request="Polish the member list UI.",
            scoped_brief="Clarify the current flow and note new context for reviewers.",
        )

        assert inventions == []

    def test_find_scope_tightening_flags_only_explicit_hard_requirement_plus_new_acceptance_combo(self):
        tightenings = find_scope_tightening(
            source_request="Polish the member list UI.",
            scoped_brief="Polish the member list UI and it must be production-ready with no regressions.",
        )

        assert tightenings == ["must", "production-ready", "no-regressions"]

    def test_find_scope_tightening_ignores_quality_wording_without_hard_requirement_upgrade(self):
        tightenings = find_scope_tightening(
            source_request="Polish the member list UI.",
            scoped_brief="Polish the member list UI and ensure it is production-ready with no regressions.",
        )

        assert tightenings == []

    def test_find_scope_tightening_allows_existing_requirement_language_from_source_request(self):
        tightenings = find_scope_tightening(
            source_request="Polish the member list UI and it must be production-ready with no regressions.",
            scoped_brief="Polish the member list UI and it must be production-ready with no regressions.",
        )

        assert tightenings == []

    def test_find_scope_audit_warnings_flags_unknowns_and_assumptions_promoted_into_scope(self):
        normalized = normalize_launch_brief(
            source_request="Polish the member list UI.",
            leader_brief="""## Source Request
Polish the member list UI.

## Scoped Brief
Polish the member list UI using the existing tests are representative assumption while final prod env remains required for rollout.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""",
        )

        warnings = find_scope_audit_warnings(
            source_request="Polish the member list UI.",
            normalized=normalized,
        )

        assert [warning.code for warning in warnings] == [
            "unknowns_promoted_to_scope",
            "assumptions_promoted_to_scope",
        ]
        assert warnings[0].details == ["final prod env"]
        assert warnings[1].details == ["existing tests are representative"]

    def test_prepare_task_launch_brief_is_single_entrypoint(self):
        prepared = prepare_task_launch_brief(
            "Goal:\nClarify {goal} into a minimal deliverable.",
            goal="Ship the feature safely",
            team_name="delivery-demo",
            agent_name="leader",
        )

        assert prepared == PreparedTaskLaunchBrief(
            rendered_description=prepared.rendered_description,
            normalized_brief=NormalizedLaunchBrief(
                format="prose_fallback",
                sections=LaunchBriefSections(
                    source_request="Ship the feature safely",
                    scoped_brief="Goal:\nClarify Ship the feature safely into a minimal deliverable.",
                    unknowns=[],
                    leader_assumptions=[],
                    out_of_scope=[],
                ),
            ),
            metadata_patch={
                "launch_brief": {
                    "format": "prose_fallback",
                    "sections": {
                        "version": "v1",
                        "source_request": "Ship the feature safely",
                        "scoped_brief": "Goal:\nClarify Ship the feature safely into a minimal deliverable.",
                        "unknowns": [],
                        "leader_assumptions": [],
                        "out_of_scope": [],
                    },
                }
            },
        )
        assert "## Brief Format\nprose_fallback" in prepared.rendered_description

    def test_render_resolved_scope_context_includes_visible_scope_audit_warnings(self):
        normalized = normalize_launch_brief(
            source_request="Polish the member list UI.",
            leader_brief="""## Source Request
Polish the member list UI.

## Scoped Brief
Polish the member list UI using the existing tests are representative assumption while final prod env remains required for rollout.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""",
        )
        warnings = find_scope_audit_warnings(
            source_request="Polish the member list UI.",
            normalized=normalized,
        )

        rendered = render_resolved_scope_context(normalized, scope_audit_warnings=warnings)

        assert "### Scope Audit Warnings" in rendered
        assert "[unknowns_promoted_to_scope]" in rendered
        assert "final prod env" in rendered
        assert "[assumptions_promoted_to_scope]" in rendered
        assert "existing tests are representative" in rendered

    def test_inject_resolved_scope_context_keeps_task_brief_and_shows_scope_audit_warnings(self):
        normalized = normalize_launch_brief(
            source_request="Polish the member list UI.",
            leader_brief="""## Source Request
Polish the member list UI.

## Scoped Brief
Polish the member list UI using the existing tests are representative assumption while final prod env remains required for rollout.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""",
        )
        warnings = find_scope_audit_warnings(
            source_request="Polish the member list UI.",
            normalized=normalized,
        )

        injected = inject_resolved_scope_context(
            description="Implement the downstream work exactly as scoped.",
            normalized=normalized,
            scope_audit_warnings=warnings,
        )

        assert "### Scope Audit Warnings" in injected
        assert "[unknowns_promoted_to_scope]" in injected
        assert "## Task Brief" in injected
        assert injected.endswith("Implement the downstream work exactly as scoped.")

    def test_build_launch_task_input_keeps_description_and_metadata_same_source(self):
        task_input = build_launch_task_input(
            TaskDef(
                subject="Implement",
                description="Clarify {goal} into a minimal deliverable.",
                owner="dev1",
                blocked_by=["Scope"],
                on_fail=["Scope"],
            ),
            goal="Ship the feature safely",
            team_name="delivery-demo",
            created_task_ids={"Scope": "task-scope-1"},
        )

        assert task_input == LaunchTaskInput(
            subject="Implement",
            description=task_input.description,
            owner="dev1",
            blocked_by=["task-scope-1"],
            metadata={
                "on_fail": ["task-scope-1"],
                "launch_brief": {
                    "format": "prose_fallback",
                    "sections": {
                        "version": "v1",
                        "source_request": "Ship the feature safely",
                        "scoped_brief": "Clarify Ship the feature safely into a minimal deliverable.",
                        "unknowns": [],
                        "leader_assumptions": [],
                        "out_of_scope": [],
                    },
                },
            },
        )
        assert "## Source Request" in task_input.description
        assert "## Brief Format\nprose_fallback" in task_input.description

    def test_build_launch_task_input_marks_explicitly_flagged_scope_tasks_as_feature_scope_required(self):
        task_input = build_launch_task_input(
            TaskDef(
                subject="Scope",
                description="Clarify {goal} into a minimal deliverable.",
                owner="leader",
                stage="scope",
                feature_scope_required=True,
            ),
            goal="Ship the feature safely",
            team_name="delivery-demo",
            created_task_ids={},
        )

        assert task_input.metadata["template_stage"] == "scope"
        assert task_input.metadata["feature_scope_required"] is True

    def test_build_launch_task_input_does_not_auto_require_feature_scope_for_generic_scope_stage(self):
        task_input = build_launch_task_input(
            TaskDef(
                subject="Scope",
                description="Clarify {goal} into a minimal deliverable.",
                owner="leader",
                stage="scope",
            ),
            goal="Ship the feature safely",
            team_name="delivery-demo",
            created_task_ids={},
        )

        assert task_input.metadata["template_stage"] == "scope"
        assert "feature_scope_required" not in task_input.metadata

    def test_build_launch_task_input_rejects_unknown_blocked_by_reference(self):
        with pytest.raises(LaunchReferenceError, match="blocked_by tasks: MissingScope") as exc:
            build_launch_task_input(
                TaskDef(
                    subject="Implement",
                    description="Clarify {goal} into a minimal deliverable.",
                    owner="dev1",
                    blocked_by=["MissingScope"],
                ),
                goal="Ship the feature safely",
                team_name="delivery-demo",
                created_task_ids={},
            )

        assert exc.value.task_subject == "Implement"
        assert exc.value.reference_kind == "blocked_by"
        assert exc.value.missing_refs == ["MissingScope"]

    def test_build_launch_task_input_rejects_unknown_on_fail_reference(self):
        with pytest.raises(LaunchReferenceError, match="on_fail tasks: MissingImplement") as exc:
            build_launch_task_input(
                TaskDef(
                    subject="QA",
                    description="Validate the deliverable.",
                    owner="qa1",
                    on_fail=["MissingImplement"],
                ),
                goal="Ship the feature safely",
                team_name="delivery-demo",
                created_task_ids={},
            )

        assert exc.value.task_subject == "QA"
        assert exc.value.reference_kind == "on_fail"
        assert exc.value.missing_refs == ["MissingImplement"]

    def test_execute_template_launch_immediate_mode_keeps_full_authored_topology(self):
        store = _FakeTaskStore()

        result = execute_template_launch(
            store,
            [
                TaskDef(
                    subject="Scope",
                    description="Clarify {goal}.",
                    owner="lead",
                ),
                TaskDef(
                    subject="Implement",
                    description="Build the change.",
                    owner="dev1",
                    blocked_by=["Scope"],
                    on_fail=["Scope"],
                ),
            ],
            goal="Ship the feature safely",
            team_name="delivery-demo",
        )

        assert result == LaunchExecutionResult(
            created_task_ids={
                "Scope": "task-1",
                "Implement": "task-2",
            }
        )
        assert [call["subject"] for call in store.calls] == ["Scope", "Implement"]
        assert store.calls[1]["blocked_by"] == ["task-1"]
        assert store.calls[1]["metadata"]["on_fail"] == ["task-1"]
        assert store.calls[1]["metadata"]["launch_brief"]["format"] == "prose_fallback"
        assert "materialization_mode" not in store.calls[0]["metadata"]
        assert "materialization_mode" not in store.calls[1]["metadata"]
        assert "deferred_materialization_state" not in store.calls[0]["metadata"]
        assert "## Interpretation Rules" in store.calls[1]["description"]

    def test_execute_template_launch_surfaces_reference_error_without_partial_hidden_logic(self):
        store = _FakeTaskStore()

        assert issubclass(LaunchReferenceError, LaunchTemplateError)

        with pytest.raises(LaunchReferenceError, match="blocked_by tasks: MissingScope") as exc:
            execute_template_launch(
                store,
                [
                    TaskDef(
                        subject="Implement",
                        description="Build the change.",
                        owner="dev1",
                        blocked_by=["MissingScope"],
                    )
                ],
                goal="Ship the feature safely",
                team_name="delivery-demo",
            )

        assert exc.value.task_subject == "Implement"
        assert exc.value.reference_kind == "blocked_by"
        assert exc.value.missing_refs == ["MissingScope"]
        assert store.calls == []

    def test_execute_template_launch_post_scope_materialization_only_creates_entry_tasks(self):
        store = _FakeTaskStore()

        result = execute_template_launch(
            store,
            [
                TaskDef(
                    subject="Scope",
                    description="Clarify {goal}.",
                    owner="lead",
                    stage="scope",
                ),
                TaskDef(
                    subject="Setup",
                    description="Prepare the baseline.",
                    owner="config1",
                    blocked_by=["Scope"],
                    stage="setup",
                ),
                TaskDef(
                    subject="Preflight",
                    description="Capture baseline signals before implementation starts.",
                    owner="lead",
                ),
                TaskDef(
                    subject="Implement",
                    description="Build the change.",
                    owner="dev1",
                    blocked_by=["Setup"],
                    stage="implement",
                ),
            ],
            goal="Ship the feature safely",
            team_name="delivery-demo",
            materialization_mode="post-scope",
        )

        assert result == LaunchExecutionResult(
            created_task_ids={
                "Scope": "task-1",
                "Preflight": "task-2",
            }
        )
        assert [call["subject"] for call in store.calls] == ["Scope", "Preflight"]
        assert store.calls[0]["metadata"]["materialization_mode"] == "post-scope"
        assert store.calls[0]["metadata"]["deferred_materialization_state"] == "pending_scope_completion"
        assert store.calls[1]["metadata"]["materialization_mode"] == "post-scope"
        assert "deferred_materialization_state" not in store.calls[1]["metadata"]

    def test_read_launch_brief_metadata_returns_normalized_contract(self):
        normalized = read_launch_brief_metadata(
            {
                "launch_brief": {
                    "format": "structured_sections",
                    "sections": {
                        "version": "v1",
                        "source_request": "Ship the feature safely",
                        "scoped_brief": "Implement only the minimal flow.",
                        "unknowns": ["Final API timeout"],
                        "leader_assumptions": ["Existing auth can be reused"],
                        "out_of_scope": ["Billing redesign"],
                    },
                }
            }
        )

        assert normalized == NormalizedLaunchBrief(
            format="structured_sections",
            sections=LaunchBriefSections(
                source_request="Ship the feature safely",
                scoped_brief="Implement only the minimal flow.",
                unknowns=["Final API timeout"],
                leader_assumptions=["Existing auth can be reused"],
                out_of_scope=["Billing redesign"],
            ),
        )

    def test_read_feature_scope_metadata_returns_structured_contract(self):
        feature_scope = read_feature_scope_metadata(
            {
                "feature_scope": {
                    "version": "v1",
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "Deliver only the minimal safe fix.",
                    "in_scope": ["Deliver only the minimal safe fix."],
                    "unknowns": ["Final API timeout"],
                    "leader_assumptions": ["Existing auth can be reused"],
                    "out_of_scope": ["Billing redesign"],
                    "risks_blockers": ["Production deploy window not confirmed"],
                    "recommended_next_step": "setup",
                    "execution_shape": "backend-only",
                    "change_budget": {
                        "allowed_layers": ["backend", "api"],
                        "allowed_operations": ["edit-existing", "add-backend-module"],
                        "allowed_roots": ["server/"],
                        "forbidden_layers": ["web-ui", "mobile-ui"],
                    },
                    "initial_targets": [
                        {
                            "kind": "api-handler",
                            "path": "server/src/routes/member.ts",
                            "exists": True,
                            "why_in_scope": "member API change required by scoped brief",
                            "evidence": ["rg hit: server/src/routes/member.ts"],
                        }
                    ],
                }
            }
        )

        assert feature_scope == FeatureScope(
            source_request="Ship the feature safely",
            scoped_brief="Deliver only the minimal safe fix.",
            in_scope=["Deliver only the minimal safe fix."],
            unknowns=["Final API timeout"],
            leader_assumptions=["Existing auth can be reused"],
            out_of_scope=["Billing redesign"],
            risks_blockers=["Production deploy window not confirmed"],
            recommended_next_step="setup",
            execution_shape="backend-only",
            change_budget={"allowed_layers": ["backend", "api"], "allowed_operations": ["edit-existing", "add-backend-module"], "allowed_roots": ["server/"], "forbidden_layers": ["web-ui", "mobile-ui"]},
            initial_targets=[{"kind": "api-handler", "path": "server/src/routes/member.ts", "exists": True, "why_in_scope": "member API change required by scoped brief", "evidence": ["rg hit: server/src/routes/member.ts"]}],
        )

    def test_read_task_launch_brief_prefers_metadata_contract(self):
        task = _FakeTask(
            description="## Source Request\nWRONG\n\n## Scoped Brief\nWRONG",
            metadata={
                "launch_brief": {
                    "format": "prose_fallback",
                    "sections": {
                        "version": "v1",
                        "source_request": "Ship the feature safely",
                        "scoped_brief": "Implement only the minimal flow.",
                        "unknowns": [],
                        "leader_assumptions": ["Existing auth can be reused"],
                        "out_of_scope": ["Billing redesign"],
                    },
                }
            },
        )

        assert read_task_launch_brief(task) == TaskLaunchBriefView(
            format="prose_fallback",
            source_request="Ship the feature safely",
            scoped_brief="Implement only the minimal flow.",
            unknowns=[],
            leader_assumptions=["Existing auth can be reused"],
            out_of_scope=["Billing redesign"],
        )

    def test_read_task_launch_brief_does_not_parse_description_without_metadata(self):
        task = _FakeTask(
            description=(
                "## Source Request\nWrong source\n\n"
                "## Scoped Brief\nWrong scope\n\n"
                "## Unknowns\n- Wrong unknown"
            ),
            metadata={},
        )

        assert read_task_launch_brief(task) is None

    def test_read_launch_brief_metadata_rejects_non_mapping_contract(self):
        with pytest.raises(LaunchTaskBuildError, match="launch_brief metadata must be a mapping"):
            read_launch_brief_metadata({"launch_brief": "not-a-mapping"})

    def test_render_task_brief_wraps_old_prose_into_sections(self):
        rendered = render_task_brief(
            "Goal:\nClarify {goal} into a minimal deliverable.",
            goal="Ship the feature safely",
            team_name="delivery-demo",
            agent_name="leader",
        )

        assert "## Source Request" in rendered
        assert "Ship the feature safely" in rendered
        assert "## Scoped Brief" in rendered
        assert "Clarify Ship the feature safely into a minimal deliverable." in rendered
        assert "## Unknowns" in rendered
        assert "## Leader Assumptions" in rendered
        assert "## Out of Scope" in rendered
        assert "## Brief Format\nprose_fallback" in rendered
        assert "## Interpretation Rules" in rendered
        assert "Do not silently convert Unknowns into requirements." in rendered


class TestSafeDict:
    def test_missing_key_returns_placeholder(self):
        d = _SafeDict(a="1")
        assert d["a"] == "1"
        # missing key wrapped back into braces
        assert "{missing}".format_map(d) == "{missing}"


class TestModels:
    def test_agent_def_defaults(self):
        a = AgentDef(name="worker")
        assert a.type == "general-purpose"
        assert a.task == ""
        assert a.command is None

    def test_task_def(self):
        t = TaskDef(subject="Build feature", description="details", owner="alice")
        assert t.subject == "Build feature"

    def test_task_def_blocked_by(self):
        t = TaskDef(subject="Build feature", blocked_by=["Setup"])
        assert t.blocked_by == ["Setup"]

    def test_task_def_on_fail(self):
        t = TaskDef(subject="Run QA", on_fail=["Implement"])
        assert t.on_fail == ["Implement"]

    def test_task_def_stage(self):
        t = TaskDef(subject="Run QA", stage="qa")
        assert t.stage == "qa"

    def test_task_def_message_contract(self):
        t = TaskDef(
            subject="Run QA",
            message_type="QA_RESULT",
            required_sections=["status", "summary", "evidence"],
        )
        assert t.message_type == "QA_RESULT"
        assert t.required_sections == ["status", "summary", "evidence"]

    def test_template_def_defaults(self):
        leader = AgentDef(name="lead")
        t = TemplateDef(name="my-tmpl", leader=leader)
        assert t.description == ""
        assert t.command == ["openclaw"]
        assert t.backend == "tmux"
        assert t.topology_mode == "explicit"
        assert t.agents == []
        assert t.tasks == []


class TestTopologyResolver:
    def test_delivery_default_resolver_fills_missing_edges(self):
        tmpl = TemplateDef(
            name="delivery",
            topology_mode="delivery-default",
            leader=AgentDef(name="leader"),
            tasks=[
                TaskDef(subject="Scope", owner="leader", stage="scope"),
                TaskDef(subject="Setup", owner="config1", stage="setup"),
                TaskDef(subject="Implement backend", owner="dev1", stage="implement"),
                TaskDef(subject="Implement frontend", owner="dev2", stage="implement"),
                TaskDef(subject="QA", owner="qa1", stage="qa"),
                TaskDef(subject="Review", owner="review1", stage="review"),
                TaskDef(subject="Deliver", owner="leader", stage="deliver"),
            ],
        )

        resolved = resolve_template_topology(tmpl)
        by_subject = {task.subject: task for task in resolved.tasks}
        assert by_subject["Setup"].blocked_by == ["Scope"]
        assert by_subject["Implement backend"].blocked_by == ["Setup"]
        assert by_subject["Implement frontend"].blocked_by == ["Setup"]
        assert by_subject["QA"].blocked_by == ["Implement backend", "Implement frontend"]
        assert by_subject["QA"].on_fail == ["Implement backend", "Implement frontend"]
        assert by_subject["Review"].blocked_by == ["QA"]
        assert by_subject["Review"].on_fail == ["Implement backend", "Implement frontend"]
        assert by_subject["Deliver"].blocked_by == ["Review"]

    def test_delivery_default_resolver_fails_closed_without_stage(self):
        tmpl = TemplateDef(
            name="broken",
            topology_mode="delivery-default",
            leader=AgentDef(name="leader"),
            tasks=[TaskDef(subject="Scope", owner="leader")],
        )

        with pytest.raises(ValueError, match="missing stage"):
            resolve_template_topology(tmpl)


class TestLoadBuiltinTemplate:
    def test_load_hedge_fund(self):
        tmpl = load_template("hedge-fund")
        assert tmpl.name == "hedge-fund"
        assert tmpl.leader.name == "portfolio-manager"
        assert len(tmpl.agents) > 0
        assert len(tmpl.tasks) > 0

    def test_leader_type(self):
        tmpl = load_template("hedge-fund")
        assert tmpl.leader.type == "portfolio-manager"

    def test_agents_have_tasks(self):
        tmpl = load_template("hedge-fund")
        for agent in tmpl.agents:
            assert agent.task != "", f"Agent '{agent.name}' has no task text"

    def test_task_owners_match_agents(self):
        tmpl = load_template("hedge-fund")
        agent_names = {tmpl.leader.name} | {a.name for a in tmpl.agents}
        for task in tmpl.tasks:
            if task.owner:
                assert task.owner in agent_names, f"Task owner '{task.owner}' not in agents"

    def test_five_step_delivery_post_scope_only_preserves_workflow_definition(self):
        """five-step-delivery keeps the full authored DAG; only materialization policy changes."""
        tmpl = load_template("five-step-delivery")

        assert tmpl.topology_mode == "post-scope-only"
        assert tmpl.materialization_mode == "post-scope"
        assert tmpl.name == "five-step-delivery"

        agent_names = {tmpl.leader.name} | {a.name for a in tmpl.agents}
        assert {"leader", "config1", "dev1", "dev2", "qa1", "qa2", "review1"}.issubset(agent_names)

        by_subject = {task.subject: task for task in tmpl.tasks}
        assert len(by_subject) == 8

        scope_task = by_subject["Scope the task into a minimal deliverable"]
        setup_task = by_subject["Prepare repo, branch, env, and runnable baseline"]
        impl_a = by_subject["Implement assigned change slice A with real validation"]
        impl_b = by_subject["Implement assigned change slice B with real validation"]
        qa_a = by_subject["Run scoped QA pass A on the real change"]
        qa_b = by_subject["Run scoped QA pass B on the real change"]
        review_task = by_subject["Review code quality, maintainability, and release readiness"]
        deliver_task = by_subject["Prepare final delivery package and human decision summary"]

        assert scope_task.stage == "scope"
        assert scope_task.feature_scope_required is True
        assert scope_task.owner == "leader"
        assert "## FEATURE_SCOPE" in scope_task.description
        assert "execution_shape" in scope_task.description
        assert "ui-only | backend-only | full-stack" in scope_task.description

        assert setup_task.stage == "setup"
        assert setup_task.message_type == "SETUP_RESULT"
        assert setup_task.blocked_by == [scope_task.subject]

        assert impl_a.stage == "implement"
        assert impl_b.stage == "implement"
        assert impl_a.message_type == "DEV_RESULT"
        assert impl_b.message_type == "DEV_RESULT"
        assert impl_a.blocked_by == [setup_task.subject]
        assert impl_b.blocked_by == [setup_task.subject]

        assert qa_a.stage == "qa"
        assert qa_b.stage == "qa"
        assert qa_a.message_type == "QA_RESULT"
        assert qa_b.message_type == "QA_RESULT"
        assert qa_a.blocked_by == [impl_a.subject, impl_b.subject]
        assert qa_b.blocked_by == [impl_a.subject, impl_b.subject]
        assert qa_a.on_fail == [impl_a.subject, impl_b.subject]
        assert qa_b.on_fail == [impl_a.subject, impl_b.subject]

        assert review_task.stage == "review"
        assert review_task.message_type == "REVIEW_RESULT"
        assert review_task.blocked_by == [qa_a.subject, qa_b.subject]
        assert review_task.on_fail == [impl_a.subject, impl_b.subject]

        assert deliver_task.stage == "deliver"
        assert deliver_task.blocked_by == [review_task.subject]

    def test_five_step_delivery_launch_creates_only_scope_task_in_post_scope_mode(self):
        """Launch materializes only root/scope tasks while keeping downstream definition deferred."""
        tmpl = load_template("five-step-delivery")
        store = _FakeTaskStore()

        result = execute_template_launch(
            store,
            tmpl.tasks,
            materialization_mode=tmpl.materialization_mode,
            goal="Test goal for five-step-delivery",
            team_name="test-team",
            template_name=tmpl.name,
        )

        assert result == LaunchExecutionResult(
            created_task_ids={"Scope the task into a minimal deliverable": "task-1"}
        )
        assert len(store.calls) == 1

        scope_call = store.calls[0]
        assert scope_call["subject"] == "Scope the task into a minimal deliverable"
        assert scope_call["blocked_by"] == []
        assert scope_call["owner"] == "leader"
        assert scope_call["metadata"]["template_stage"] == "scope"
        assert scope_call["metadata"]["feature_scope_required"] is True
        assert scope_call["metadata"]["materialization_mode"] == "post-scope"
        assert "change_budget" in scope_call["description"]
        assert "initial_targets" in scope_call["description"]
        assert scope_call["metadata"]["deferred_materialization_state"] == "pending_scope_completion"

        workflow_definition = scope_call["metadata"]["workflow_definition"]
        assert workflow_definition["template_name"] == "five-step-delivery"
        assert workflow_definition["preserved_definition"] is True
        assert workflow_definition["materialized_subjects"] == ["Scope the task into a minimal deliverable"]
        assert workflow_definition["deferred_subjects"] == [
            "Prepare repo, branch, env, and runnable baseline",
            "Implement assigned change slice A with real validation",
            "Implement assigned change slice B with real validation",
            "Run scoped QA pass A on the real change",
            "Run scoped QA pass B on the real change",
            "Review code quality, maintainability, and release readiness",
            "Prepare final delivery package and human decision summary",
        ]
        assert [task["stage"] for task in workflow_definition["tasks"]] == [
            "scope",
            "setup",
            "implement",
            "implement",
            "qa",
            "qa",
            "review",
            "deliver",
        ]



class TestLoadTemplateNotFound:
    def test_missing_template_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_template("this-does-not-exist-anywhere")


class TestUserTemplateOverride:
    def test_user_template_takes_priority(self, tmp_path, monkeypatch):
        """User templates in ~/.clawteam/templates/ override builtins."""
        user_tpl_dir = tmp_path / ".clawteam" / "templates"
        user_tpl_dir.mkdir(parents=True)

        toml_content = """\
[template]
name = "custom"
description = "User override"

[template.leader]
name = "my-leader"
type = "custom-leader"
"""
        (user_tpl_dir / "custom.toml").write_text(toml_content)

        # patch the module-level _USER_DIR
        import clawteam.templates as tmod

        monkeypatch.setattr(tmod, "_USER_DIR", user_tpl_dir)

        tmpl = load_template("custom")
        assert tmpl.name == "custom"
        assert tmpl.leader.name == "my-leader"
        assert tmpl.description == "User override"


class TestListTemplates:
    def test_list_includes_builtin(self):
        templates = list_templates()
        names = {t["name"] for t in templates}
        assert "hedge-fund" in names

    def test_list_entry_format(self):
        templates = list_templates()
        for t in templates:
            assert "name" in t
            assert "description" in t
            assert "source" in t
            assert t["source"] in ("builtin", "user")
