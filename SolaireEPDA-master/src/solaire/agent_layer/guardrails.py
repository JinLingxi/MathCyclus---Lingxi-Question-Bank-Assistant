"""Guardrails: tool risk tiers, confirmation, session-level auto-approve for writes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from solaire.agent_layer import registry as tool_registry
from solaire.agent_layer.models import GuardrailDecision, InvocationContext, SessionState, ToolRisk
from solaire.common.security import assert_within_project


@dataclass(frozen=True)
class ToolPolicy:
    risk: ToolRisk
    requires_confirmation_override: bool | None = None


SAFETY_MODE_MODERATO = "moderato"
SAFETY_MODE_ALLEGRO = "allegro"
SAFETY_MODE_VIVACE = "vivace"
SAFETY_MODE_PRESTISSIMO = "prestissimo"
SAFETY_MODE_CHOICES = (
    SAFETY_MODE_MODERATO,
    SAFETY_MODE_ALLEGRO,
    SAFETY_MODE_VIVACE,
    SAFETY_MODE_PRESTISSIMO,
)
_SAFETY_MODE_FILE = "safety_mode.json"

SAFETY_MODE_LABELS: dict[str, str] = {
    SAFETY_MODE_MODERATO: "Moderato Mode",
    SAFETY_MODE_ALLEGRO: "Allegro Mode",
    SAFETY_MODE_VIVACE: "Vivace Mode",
    SAFETY_MODE_PRESTISSIMO: "Prestissimo Mode",
}

def _safety_mode_path(project_root: Path) -> Path:
    p = (project_root / ".solaire" / "agent" / _SAFETY_MODE_FILE).resolve()
    assert_within_project(project_root, p)
    return p


def load_safety_mode(project_root: Path | None) -> str:
    if project_root is None:
        return SAFETY_MODE_ALLEGRO
    p = _safety_mode_path(project_root)
    if not p.is_file():
        return SAFETY_MODE_ALLEGRO
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SAFETY_MODE_ALLEGRO
    mode = str(raw.get("mode") or "").strip().lower()
    if mode in SAFETY_MODE_CHOICES:
        return mode
    return SAFETY_MODE_ALLEGRO


def save_safety_mode(project_root: Path, mode: str) -> None:
    m = mode.strip().lower()
    if m not in SAFETY_MODE_CHOICES:
        raise ValueError("invalid safety mode")
    p = _safety_mode_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mode": m}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_safety_modes_public() -> list[dict[str, str]]:
    return [
        {
            "id": SAFETY_MODE_MODERATO,
            "label": SAFETY_MODE_LABELS[SAFETY_MODE_MODERATO],
            "description": "新增、编辑、删除都需要确认；查看类操作直接执行。",
        },
        {
            "id": SAFETY_MODE_ALLEGRO,
            "label": SAFETY_MODE_LABELS[SAFETY_MODE_ALLEGRO],
            "description": "新增直接执行；编辑与删除需要确认。",
        },
        {
            "id": SAFETY_MODE_VIVACE,
            "label": SAFETY_MODE_LABELS[SAFETY_MODE_VIVACE],
            "description": "大多数操作直接执行；高危操作会先快速复核，疑似风险时再确认。",
        },
        {
            "id": SAFETY_MODE_PRESTISSIMO,
            "label": SAFETY_MODE_LABELS[SAFETY_MODE_PRESTISSIMO],
            "description": "所有操作都直接执行，不再进行确认。",
        },
    ]


def policy_for(tool_name: str) -> ToolPolicy:
    rt = tool_registry.get_registered_tool(tool_name)
    if rt is None:
        return ToolPolicy(ToolRisk.READ)
    return ToolPolicy(risk=rt.risk, requires_confirmation_override=rt.requires_confirmation_override)


def vivace_needs_fast_model_review(tool_name: str) -> bool:
    """Whether Vivace mode runs the extra fast-model safety pass for this tool (see tool_executor)."""
    rt = tool_registry.get_registered_tool(tool_name)
    return bool(rt and rt.vivace_fast_review)


def check_tool_call(
    tool_name: str,
    args: dict,
    ctx: InvocationContext,
    *,
    safety_mode: str | None = None,
) -> GuardrailDecision:
    mode = (safety_mode or load_safety_mode(ctx.project_root)).strip().lower()
    pol = policy_for(tool_name)
    if pol.requires_confirmation_override is True:
        return GuardrailDecision.NEEDS_CONFIRMATION
    if mode == SAFETY_MODE_PRESTISSIMO:
        return GuardrailDecision.AUTO_APPROVE
    if mode == SAFETY_MODE_MODERATO:
        return GuardrailDecision.AUTO_APPROVE if pol.risk == ToolRisk.READ else GuardrailDecision.NEEDS_CONFIRMATION
    if mode == SAFETY_MODE_ALLEGRO:
        if pol.risk == ToolRisk.READ:
            return GuardrailDecision.AUTO_APPROVE
        if pol.risk == ToolRisk.DESTRUCTIVE:
            return GuardrailDecision.NEEDS_CONFIRMATION
        rt = tool_registry.get_registered_tool(tool_name)
        allegro_add = bool(rt and rt.allegro_auto_add)
        return GuardrailDecision.AUTO_APPROVE if allegro_add else GuardrailDecision.NEEDS_CONFIRMATION
    if mode == SAFETY_MODE_VIVACE:
        # Vivace 下默认放行；高危动作由 orchestrator 的快速复核进一步判定
        return GuardrailDecision.AUTO_APPROVE

    if pol.risk == ToolRisk.READ:
        return GuardrailDecision.AUTO_APPROVE
    if pol.risk == ToolRisk.DESTRUCTIVE:
        return GuardrailDecision.NEEDS_CONFIRMATION
    # WRITE
    if ctx.mode == "suggest":
        return GuardrailDecision.NEEDS_CONFIRMATION
    session = ctx.session
    if session is None:
        return GuardrailDecision.NEEDS_CONFIRMATION
    key = ctx.approved_key(tool_name, args)
    if key in session.approved_write_keys:
        return GuardrailDecision.AUTO_APPROVE
    return GuardrailDecision.NEEDS_CONFIRMATION


def human_confirmation_message(tool_name: str, args: dict) -> str:
    rt = tool_registry.get_registered_tool(tool_name)
    label = (rt.action_label if rt and rt.action_label else None) or "一项可能影响数据的操作"
    return f"助手请求执行：{label}。请确认是否继续。"


def register_approval(session: SessionState, ctx: InvocationContext, tool_name: str, args: dict) -> None:
    session.approved_write_keys.append(ctx.approved_key(tool_name, args))
