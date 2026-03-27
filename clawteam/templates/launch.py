from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError


class LaunchTemplateError(ValueError):
    """Base typed error for launch-boundary failures."""


class LaunchReferenceError(LaunchTemplateError):
    """Raised when a template references a task that is not launchable yet."""

    def __init__(self, *, task_subject: str, reference_kind: str, missing_refs: list[str]):
        self.task_subject = task_subject
        self.reference_kind = reference_kind
        self.missing_refs = missing_refs
        super().__init__(
            f"Template task '{task_subject}' references unknown or not-yet-created "
            f"{reference_kind} tasks: {', '.join(missing_refs)}"
        )


class LaunchTaskBuildError(LaunchTemplateError):
    """Raised when launch task input construction fails."""


class ScopeTaskValidationError(LaunchTemplateError):
    """Raised when a scope-task completion payload is missing or invalid."""


class FeatureScope(BaseModel):
    version: str = "v1"
    source_request: str = ""
    scoped_brief: str = ""
    in_scope: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    leader_assumptions: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    risks_blockers: list[str] = Field(default_factory=list)
    recommended_next_step: str = ""


class LaunchBriefSections(BaseModel):
    version: str = "v1"
    source_request: str = ""
    scoped_brief: str = ""
    unknowns: list[str] = Field(default_factory=list)
    leader_assumptions: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class NormalizedLaunchBrief(BaseModel):
    format: str = "prose_fallback"
    sections: LaunchBriefSections = Field(default_factory=LaunchBriefSections)
    feature_scope: FeatureScope | None = None


class PreparedTaskLaunchBrief(BaseModel):
    rendered_description: str
    normalized_brief: NormalizedLaunchBrief
    metadata_patch: dict[str, object] = Field(default_factory=dict)


class LaunchTaskInput(BaseModel):
    subject: str
    description: str
    owner: str
    blocked_by: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class LaunchExecutionResult(BaseModel):
    created_task_ids: dict[str, str] = Field(default_factory=dict)


def _build_deferred_workflow_definition(
    *,
    tasks,
    materialized_subjects: list[str],
    template_name: str | None = None,
) -> dict[str, object]:
    authored_tasks = []
    for task_def in tasks:
        authored_tasks.append(
            {
                "subject": task_def.subject,
                "owner": task_def.owner,
                "stage": task_def.stage.strip().lower() if task_def.stage else "",
                "blocked_by": list(task_def.blocked_by),
                "on_fail": list(task_def.on_fail),
                "message_type": task_def.message_type,
                "required_sections": list(task_def.required_sections),
                "feature_scope_required": bool(task_def.feature_scope_required),
                "description": task_def.description,
            }
        )

    deferred_subjects = [task_def.subject for task_def in tasks if task_def.subject not in materialized_subjects]
    return {
        "template_name": template_name,
        "preserved_definition": True,
        "materialization_mode": "post-scope",
        "authored_task_order": [task_def.subject for task_def in tasks],
        "materialized_subjects": list(materialized_subjects),
        "deferred_subjects": deferred_subjects,
        "tasks": authored_tasks,
    }


class TaskLaunchBriefView(BaseModel):
    format: str = "prose_fallback"
    source_request: str = ""
    scoped_brief: str = ""
    unknowns: list[str] = Field(default_factory=list)
    leader_assumptions: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class ScopeAuditWarning(BaseModel):
    code: str
    message: str
    details: list[str] = Field(default_factory=list)


_NO_INVENTION_ENTITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "endpoint": (r"\bendpoint(?:s)?\b", r"\broute(?:s)?\b"),
    "api": (r"\bapi(?:s)?\b",),
    "schema": (r"\bschema(?:s)?\b",),
    "page": (r"\bpage(?:s)?\b",),
    "tab": (r"\btab(?:s)?\b",),
    "workflow": (r"\bworkflow(?:s)?\b",),
    "deliverable": (r"\bdeliverable(?:s)?\b",),
}

_TIGHTENING_HARD_REQUIREMENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "must": (r"\bmust\b",),
    "required": (r"\brequired\b",),
    "mandatory": (r"\bmandatory\b",),
}

_TIGHTENING_ACCEPTANCE_PATTERNS: dict[str, tuple[str, ...]] = {
    "production-ready": (r"\bproduction[-\s]ready\b",),
    "full-coverage": (r"\bfull\s+coverage\b",),
    "all-cases": (r"\ball\s+cases\b",),
    "end-to-end": (r"\bend[-\s]to[-\s]end\b",),
    "no-regressions": (r"\bno\s+regressions\b",),
}

# Hard-fail only on explicit additive intent, not merely on new vocabulary.
_STRONG_ADDITIVE_INTENT_PATTERNS: tuple[str, ...] = (
    r"\badd\b",
    r"\bcreate\b",
    r"\bintroduce\b",
)

_NEGATED_ADDITIVE_PATTERNS: tuple[str, ...] = (
    r"\bwithout\s+adding\b",
    r"\bwithout\s+creating\b",
    r"\bwithout\s+introducing\b",
    r"\bno\s+new\b",
    r"\bnot\s+add(?:ing)?\b",
    r"\bnot\s+create(?:ing)?\b",
    r"\bnot\s+introduc(?:e|ing)\b",
)


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _has_positive_additive_intent(text: str, entity_patterns: tuple[str, ...]) -> bool:
    if _matches_any_pattern(text, _NEGATED_ADDITIVE_PATTERNS):
        return False
    if _matches_any_pattern(text, _STRONG_ADDITIVE_INTENT_PATTERNS):
        return True
    stripped_entity_patterns = tuple(
        pattern[2:] if pattern.startswith(r"\b") else pattern
        for pattern in entity_patterns
    )
    new_with_entity_patterns = tuple(rf"\bnew\s+{pattern}" for pattern in stripped_entity_patterns)
    if _matches_any_pattern(text, new_with_entity_patterns):
        return True
    action_with_new_entity_patterns = tuple(
        rf"\b(?:add|create|introduce)(?:\s+\w+){{0,3}}\s+new\s+{pattern}"
        for pattern in stripped_entity_patterns
    )
    return _matches_any_pattern(text, action_with_new_entity_patterns)


def find_scope_inventions(*, source_request: str, scoped_brief: str) -> list[str]:
    inventions: list[str] = []
    for label, patterns in _NO_INVENTION_ENTITY_PATTERNS.items():
        if not _has_positive_additive_intent(scoped_brief, patterns):
            continue
        if _matches_any_pattern(scoped_brief, patterns) and not _matches_any_pattern(source_request, patterns):
            inventions.append(label)
    return inventions


def find_scope_tightening(*, source_request: str, scoped_brief: str) -> list[str]:
    hard_requirement_labels = [
        label
        for label, patterns in _TIGHTENING_HARD_REQUIREMENT_PATTERNS.items()
        if _matches_any_pattern(scoped_brief, patterns) and not _matches_any_pattern(source_request, patterns)
    ]
    acceptance_labels = [
        label
        for label, patterns in _TIGHTENING_ACCEPTANCE_PATTERNS.items()
        if _matches_any_pattern(scoped_brief, patterns) and not _matches_any_pattern(source_request, patterns)
    ]
    if not hard_requirement_labels or not acceptance_labels:
        return []
    return hard_requirement_labels + acceptance_labels


def find_scope_audit_warnings(*, source_request: str, normalized: NormalizedLaunchBrief) -> list[ScopeAuditWarning]:
    warnings: list[ScopeAuditWarning] = []
    scoped_brief = normalized.sections.scoped_brief

    invented_entities = find_scope_inventions(source_request=source_request, scoped_brief=scoped_brief)
    if invented_entities:
        warnings.append(
            ScopeAuditWarning(
                code="scope_entities_added",
                message="Scoped Brief references risky scope entities that do not appear in Source Request.",
                details=invented_entities,
            )
        )

    tightened_requirements = find_scope_tightening(source_request=source_request, scoped_brief=scoped_brief)
    if tightened_requirements:
        warnings.append(
            ScopeAuditWarning(
                code="acceptance_tightening",
                message="Scoped Brief appears to introduce stricter acceptance language than Source Request.",
                details=tightened_requirements,
            )
        )

    relocated_unknowns = [
        item for item in normalized.sections.unknowns if item and item.lower() in scoped_brief.lower()
    ]
    if relocated_unknowns:
        warnings.append(
            ScopeAuditWarning(
                code="unknowns_promoted_to_scope",
                message="Items listed as Unknowns also appear as committed scope language in Scoped Brief.",
                details=relocated_unknowns,
            )
        )

    relocated_assumptions = [
        item for item in normalized.sections.leader_assumptions if item and item.lower() in scoped_brief.lower()
    ]
    if relocated_assumptions:
        warnings.append(
            ScopeAuditWarning(
                code="assumptions_promoted_to_scope",
                message="Items listed as Leader Assumptions also appear as committed scope language in Scoped Brief.",
                details=relocated_assumptions,
            )
        )

    return warnings


def _extract_feature_scope_block(text: str) -> str | None:
    match = re.search(r"(?:^|\n)##\s*FEATURE_SCOPE\s*\n(.*?)(?=\n##\s+[A-Za-z]|\Z)", text.strip(), flags=re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def _validate_feature_scope_matches_brief(
    *,
    payload: dict[str, object],
    normalized: NormalizedLaunchBrief,
) -> None:
    expected_sections = normalized.sections

    scalar_pairs = (
        ("source_request", expected_sections.source_request),
        ("scoped_brief", expected_sections.scoped_brief),
    )
    for key, expected_value in scalar_pairs:
        actual = payload.get(key)
        if actual is None:
            continue
        if not isinstance(actual, str) or actual.strip() != expected_value.strip():
            raise ScopeTaskValidationError(
                f"FEATURE_SCOPE {key} must match the corresponding structured scope section."
            )

    list_pairs = (
        ("unknowns", list(expected_sections.unknowns)),
        ("leader_assumptions", list(expected_sections.leader_assumptions)),
        ("out_of_scope", list(expected_sections.out_of_scope)),
    )
    for key, expected_values in list_pairs:
        actual = payload.get(key)
        if actual is None:
            continue
        if not isinstance(actual, list) or [str(item).strip() for item in actual] != expected_values:
            raise ScopeTaskValidationError(
                f"FEATURE_SCOPE {key} must match the corresponding structured scope section."
            )


def parse_feature_scope_block(
    text: str,
    *,
    normalized: NormalizedLaunchBrief | None = None,
) -> FeatureScope | None:
    block = _extract_feature_scope_block(text)
    if block is None:
        return None
    try:
        payload = json.loads(block)
    except json.JSONDecodeError as exc:
        raise ScopeTaskValidationError(
            "Scope task completion FEATURE_SCOPE block must be valid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise ScopeTaskValidationError(
            "Scope task completion FEATURE_SCOPE block must decode to an object."
        )
    payload = dict(payload)
    if "recommended_next_step" not in payload and "next_step" in payload:
        payload["recommended_next_step"] = payload["next_step"]
    raw_in_scope = payload.get("in_scope")
    raw_scoped_brief = payload.get("scoped_brief")
    has_raw_in_scope = isinstance(raw_in_scope, list) and any(str(item).strip() for item in raw_in_scope)
    has_raw_scoped_brief = isinstance(raw_scoped_brief, str) and raw_scoped_brief.strip()
    if not has_raw_in_scope and not has_raw_scoped_brief:
        raise ScopeTaskValidationError(
            "Scope task completion FEATURE_SCOPE block must include non-empty in_scope or scoped_brief data."
        )
    raw_next_step = payload.get("recommended_next_step")
    if not isinstance(raw_next_step, str) or not raw_next_step.strip():
        raise ScopeTaskValidationError(
            "Scope task completion FEATURE_SCOPE block must include a non-empty recommended_next_step value."
        )
    if normalized is not None:
        _validate_feature_scope_matches_brief(payload=payload, normalized=normalized)
        payload.setdefault("source_request", normalized.sections.source_request)
        payload.setdefault("scoped_brief", normalized.sections.scoped_brief)
        payload.setdefault("unknowns", list(normalized.sections.unknowns))
        payload.setdefault("leader_assumptions", list(normalized.sections.leader_assumptions))
        payload.setdefault("out_of_scope", list(normalized.sections.out_of_scope))
    if not payload.get("in_scope") and payload.get("scoped_brief"):
        payload["in_scope"] = [payload["scoped_brief"]]
    try:
        feature_scope = FeatureScope.model_validate(payload)
    except ValidationError as exc:
        raise ScopeTaskValidationError(
            "Scope task completion FEATURE_SCOPE block is malformed."
        ) from exc
    if not feature_scope.in_scope:
        raise ScopeTaskValidationError(
            "Scope task completion FEATURE_SCOPE block must include non-empty in_scope or scoped_brief data."
        )
    if not feature_scope.scoped_brief.strip():
        raise ScopeTaskValidationError(
            "Scope task completion FEATURE_SCOPE block must include a non-empty scoped_brief value."
        )
    return feature_scope


def validate_scope_task_completion(
    *,
    source_request: str,
    leader_brief: str,
    require_feature_scope: bool = False,
) -> NormalizedLaunchBrief:
    normalized = normalize_launch_brief(source_request=source_request, leader_brief=leader_brief)
    if normalized.format != "structured_sections":
        raise ScopeTaskValidationError(
            "Scope task completion must replace the task description with the exact structured sections."
        )
    if not normalized.sections.scoped_brief.strip():
        raise ScopeTaskValidationError("Scope task completion is missing a non-empty Scoped Brief section.")
    invented_entities = find_scope_inventions(
        source_request=source_request,
        scoped_brief=normalized.sections.scoped_brief,
    )
    if invented_entities:
        raise ScopeTaskValidationError(
            "Scope task completion invents new scope entities not present in the source request: "
            + ", ".join(invented_entities)
        )
    tightened_requirements = find_scope_tightening(
        source_request=source_request,
        scoped_brief=normalized.sections.scoped_brief,
    )
    if tightened_requirements:
        raise ScopeTaskValidationError(
            "Scope task completion adds stricter requirements not present in the source request: "
            + ", ".join(tightened_requirements)
        )
    feature_scope = parse_feature_scope_block(leader_brief, normalized=normalized)
    if require_feature_scope and feature_scope is None:
        raise ScopeTaskValidationError(
            "Scope task completion for feature delivery must include a valid FEATURE_SCOPE block."
        )
    return normalized.model_copy(update={"feature_scope": feature_scope})


def _coerce_normalized_launch_brief(value: NormalizedLaunchBrief | dict[str, object]) -> NormalizedLaunchBrief:
    if isinstance(value, NormalizedLaunchBrief):
        return value
    return NormalizedLaunchBrief.model_validate(value)


def render_resolved_scope_context(
    normalized: NormalizedLaunchBrief | dict[str, object],
    *,
    scope_audit_warnings: list[dict[str, object]] | list[ScopeAuditWarning] | None = None,
) -> str:
    normalized = _coerce_normalized_launch_brief(normalized)
    sections = normalized.sections

    def _bullet_lines(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) if values else "- none"

    def _render_scope_warnings(
        warnings: list[dict[str, object]] | list[ScopeAuditWarning] | None,
    ) -> str:
        if not warnings:
            return "- none"
        rendered: list[str] = []
        for warning in warnings:
            if isinstance(warning, ScopeAuditWarning):
                code = warning.code
                message = warning.message
                details = warning.details
            elif isinstance(warning, dict):
                code = str(warning.get("code") or "warning")
                message = str(warning.get("message") or code)
                raw_details = warning.get("details")
                details = [str(item) for item in raw_details] if isinstance(raw_details, list) else []
            else:
                continue
            line = f"- [{code}] {message}"
            if details:
                line += f" Details: {', '.join(details)}"
            rendered.append(line)
        return "\n".join(rendered) if rendered else "- none"

    return "\n\n".join(
        [
            "## Resolved Scope Context",
            f"### Source Request\n{sections.source_request or '- none'}",
            f"### Scoped Brief\n{sections.scoped_brief or '- none'}",
            f"### Scope Audit Warnings\n{_render_scope_warnings(scope_audit_warnings)}",
            f"### Unknowns\n{_bullet_lines(sections.unknowns)}",
            f"### Leader Assumptions\n{_bullet_lines(sections.leader_assumptions)}",
            f"### Out of Scope\n{_bullet_lines(sections.out_of_scope)}",
        ]
    )


def inject_resolved_scope_context(
    *,
    description: str,
    normalized: NormalizedLaunchBrief | dict[str, object],
    scope_audit_warnings: list[dict[str, object]] | list[ScopeAuditWarning] | None = None,
) -> str:
    normalized = _coerce_normalized_launch_brief(normalized)
    text = (description or "").strip()
    marker = "## Resolved Scope Context"
    task_brief_marker = "## Task Brief"
    if text.startswith(marker) and task_brief_marker in text:
        _, _, remainder = text.partition(task_brief_marker)
        text = remainder.strip()
    scope_block = render_resolved_scope_context(normalized, scope_audit_warnings=scope_audit_warnings)
    if not text:
        return scope_block
    return f"{scope_block}\n\n## Task Brief\n{text}"


NormalizedLaunchBrief.model_rebuild()
FeatureScope.model_rebuild()
PreparedTaskLaunchBrief.model_rebuild()
LaunchTaskInput.model_rebuild()
LaunchExecutionResult.model_rebuild()


def _normalize_lines(value: str) -> list[str]:
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        lines.append(stripped)
    return lines


def normalize_launch_brief(*, source_request: str, leader_brief: str) -> NormalizedLaunchBrief:
    """Normalize launch input into an explicit brief contract.

    Structured format is intentionally minimal and section-labeled:
    ## Source Request
    ## Scoped Brief
    ## Unknowns
    ## Leader Assumptions
    ## Out of Scope
    """
    text = leader_brief.strip()
    if not text:
        return NormalizedLaunchBrief(
            format="empty",
            sections=LaunchBriefSections(source_request=source_request),
        )

    labels = {
        "source request": "source_request",
        "scoped brief": "scoped_brief",
        "unknowns": "unknowns",
        "leader assumptions": "leader_assumptions",
        "out of scope": "out_of_scope",
    }
    current: str | None = None
    sections: dict[str, list[str]] = {value: [] for value in labels.values()}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("## "):
            key = lowered[3:].strip()
            current = labels.get(key)
            continue
        if current is not None:
            sections[current].append(line)

    if any(sections.values()):
        return NormalizedLaunchBrief(
            format="structured_sections",
            sections=LaunchBriefSections(
                source_request="\n".join(sections["source_request"]).strip() or source_request,
                scoped_brief="\n".join(sections["scoped_brief"]).strip(),
                unknowns=_normalize_lines("\n".join(sections["unknowns"])),
                leader_assumptions=_normalize_lines("\n".join(sections["leader_assumptions"])),
                out_of_scope=_normalize_lines("\n".join(sections["out_of_scope"])),
            ),
        )

    return NormalizedLaunchBrief(
        format="prose_fallback",
        sections=LaunchBriefSections(
            source_request=source_request,
            scoped_brief=text,
        ),
    )


def parse_launch_brief(*, source_request: str, leader_brief: str) -> LaunchBriefSections:
    """Backward-compatible helper returning only the normalized sections."""
    return normalize_launch_brief(
        source_request=source_request,
        leader_brief=leader_brief,
    ).sections


def _render_normalized_launch_brief(normalized: NormalizedLaunchBrief) -> str:
    sections = normalized.sections

    def _bullet_lines(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) if values else "- none"

    return "\n\n".join(
        [
            f"## Source Request\n{sections.source_request or '- none'}",
            f"## Scoped Brief\n{sections.scoped_brief or '- none'}",
            f"## Unknowns\n{_bullet_lines(sections.unknowns)}",
            f"## Leader Assumptions\n{_bullet_lines(sections.leader_assumptions)}",
            f"## Out of Scope\n{_bullet_lines(sections.out_of_scope)}",
            f"## Brief Format\n{normalized.format}",
            "## Interpretation Rules\n"
            "- Treat Source Request as the original user intent.\n"
            "- Treat Scoped Brief as the current working scope.\n"
            "- Do not silently convert Unknowns into requirements.\n"
            "- Treat Leader Assumptions as provisional, not confirmed fact.\n"
            "- Do not implement Out of Scope items in the current task.",
        ]
    )


def prepare_task_launch_brief(task: str, *, render_task, **variables: str) -> PreparedTaskLaunchBrief:
    """Single launch-boundary entrypoint for task brief preparation.

    This keeps render/normalize/metadata logic out of the CLI composition root.
    """
    rendered = render_task(task, **variables).strip()
    normalized = normalize_launch_brief(
        source_request=variables.get("goal", ""),
        leader_brief=rendered,
    )
    return PreparedTaskLaunchBrief(
        rendered_description=_render_normalized_launch_brief(normalized),
        normalized_brief=normalized,
        metadata_patch={"launch_brief": normalized.model_dump(mode="json", exclude_none=True)},
    )


def render_task_brief(task: str, *, render_task, **variables: str) -> str:
    """Backward-compatible helper returning only rendered launch description."""
    return prepare_task_launch_brief(task, render_task=render_task, **variables).rendered_description


def read_launch_brief_metadata(metadata: dict[str, object] | None) -> NormalizedLaunchBrief | None:
    """Read the canonical machine launch-brief contract from task metadata only."""
    if not metadata:
        return None

    launch_brief = metadata.get("launch_brief")
    if launch_brief is None:
        return None
    if not isinstance(launch_brief, dict):
        raise LaunchTaskBuildError("Task launch_brief metadata must be a mapping.")

    return NormalizedLaunchBrief.model_validate(launch_brief)


def read_feature_scope_metadata(metadata: dict[str, object] | None) -> FeatureScope | None:
    """Read the canonical structured feature scope contract from task metadata only."""
    if not metadata:
        return None

    feature_scope = metadata.get("feature_scope")
    if feature_scope is None:
        return None
    if not isinstance(feature_scope, dict):
        raise LaunchTaskBuildError("Task feature_scope metadata must be a mapping.")

    return FeatureScope.model_validate(feature_scope)


def read_task_launch_brief(task) -> TaskLaunchBriefView | None:
    """Return the canonical task launch-brief view from metadata only.

    Intentionally does not parse task.description. Human-facing description is presentation;
    task.metadata['launch_brief'] is the machine-readable contract boundary.
    """
    normalized = read_launch_brief_metadata(getattr(task, "metadata", None))
    if normalized is None:
        return None

    return TaskLaunchBriefView(
        format=normalized.format,
        source_request=normalized.sections.source_request,
        scoped_brief=normalized.sections.scoped_brief,
        unknowns=list(normalized.sections.unknowns),
        leader_assumptions=list(normalized.sections.leader_assumptions),
        out_of_scope=list(normalized.sections.out_of_scope),
    )


def build_launch_task_input(
    task_def,
    *,
    goal: str,
    team_name: str,
    created_task_ids: dict[str, str],
    render_task,
    materialization_mode: str = "immediate",
    deferred_workflow_definition: dict[str, object] | None = None,
) -> LaunchTaskInput:
    """Canonical launch-task preparation entrypoint.

    Produces the task payload consumed by the CLI create path so description,
    reference validation, and metadata stay derived from one launch-boundary
    decision.
    """
    missing_dependencies = [name for name in task_def.blocked_by if name not in created_task_ids]
    if missing_dependencies:
        raise LaunchReferenceError(
            task_subject=task_def.subject,
            reference_kind="blocked_by",
            missing_refs=missing_dependencies,
        )

    missing_fail_targets = [name for name in task_def.on_fail if name not in created_task_ids]
    if missing_fail_targets:
        raise LaunchReferenceError(
            task_subject=task_def.subject,
            reference_kind="on_fail",
            missing_refs=missing_fail_targets,
        )

    metadata: dict[str, object] = {}
    if task_def.on_fail:
        metadata["on_fail"] = [created_task_ids[name] for name in task_def.on_fail]
    if task_def.stage:
        metadata["template_stage"] = task_def.stage.strip().lower()
    if task_def.feature_scope_required:
        metadata["feature_scope_required"] = True
    if materialization_mode != "immediate":
        metadata["materialization_mode"] = materialization_mode
    if task_def.message_type:
        metadata["message_type"] = task_def.message_type
    if task_def.required_sections:
        metadata["required_sections"] = list(task_def.required_sections)

    prepared_brief = prepare_task_launch_brief(
        task_def.description,
        goal=goal,
        team_name=team_name,
        agent_name=task_def.owner,
        render_task=render_task,
    )
    metadata.update(prepared_brief.metadata_patch)
    if materialization_mode == "post-scope" and deferred_workflow_definition is not None:
        metadata["workflow_definition"] = deferred_workflow_definition
    if metadata.get("template_stage") == "scope" and materialization_mode == "post-scope":
        metadata["deferred_materialization_state"] = "pending_scope_completion"

    return LaunchTaskInput(
        subject=task_def.subject,
        description=prepared_brief.rendered_description,
        owner=task_def.owner,
        blocked_by=[created_task_ids[name] for name in task_def.blocked_by],
        metadata=metadata,
    )


def execute_template_launch(
    task_store,
    tasks,
    *,
    goal: str,
    team_name: str,
    render_task,
    materialization_mode: str = "immediate",
    template_name: str | None = None,
) -> LaunchExecutionResult:
    """Execute authored-order template task creation behind one launch boundary."""
    created_task_ids: dict[str, str] = {}
    tasks_to_launch = list(tasks)
    deferred_workflow_definition: dict[str, object] | None = None
    if materialization_mode == "post-scope":
        tasks_to_launch = [task_def for task_def in tasks if not task_def.blocked_by]
        deferred_workflow_definition = _build_deferred_workflow_definition(
            tasks=tasks,
            materialized_subjects=[task_def.subject for task_def in tasks_to_launch],
            template_name=template_name,
        )

    for task_def in tasks_to_launch:
        launch_task_input = build_launch_task_input(
            task_def,
            goal=goal,
            team_name=team_name,
            created_task_ids=created_task_ids,
            render_task=render_task,
            materialization_mode=materialization_mode,
            deferred_workflow_definition=deferred_workflow_definition,
        )
        task = task_store.create(
            subject=launch_task_input.subject,
            description=launch_task_input.description,
            owner=launch_task_input.owner,
            blocked_by=launch_task_input.blocked_by,
            metadata=launch_task_input.metadata,
        )
        created_task_ids[task_def.subject] = task.id

    return LaunchExecutionResult(created_task_ids=created_task_ids)
