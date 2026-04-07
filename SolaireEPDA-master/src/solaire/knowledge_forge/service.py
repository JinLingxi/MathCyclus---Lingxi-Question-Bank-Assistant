"""KnowledgeForge 领域服务：文件持久化 + 基础校验。

本阶段 M1 只交付「知识点节点」与「节点关系」以及「题库题目绑定」的最小闭环。
后续存储引擎可替换，但对外应保持语义一致（由 web API 层承担契约）。

注意：此模块不依赖 solaire.web.*，路径安全通过 solaire.common.security 处理。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from solaire.common.security import assert_within_project

_GRAPH_DIR_NAME = "graph"
_STATE_FILENAME = "state.yaml"

_ALLOWED_NODE_KINDS = frozenset({"concept", "skill", "causal"})

_ALLOWED_RELATION_TYPES = frozenset(
    {
        # 先修
        "prerequisite",
        # 组成
        "part_of",
        # 弱关联（含原「技能依赖」边迁移后的概念↔技能弱连接）
        "related",
        # 因果
        "causal",
    }
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ConceptNode(BaseModel):
    """图谱节点；需求书中的 Concept / Skill / Causal 以 node_kind 区分（同表存储）。"""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    node_kind: Literal["concept", "skill", "causal"] = Field(
        default="concept",
        description="节点类型：知识点 / 技能 / 因果",
    )
    aliases: list[str] = Field(default_factory=list)
    subject: str | None = None
    level: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    layout_x: float | None = None
    layout_y: float | None = None
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    @field_validator("node_kind", mode="before")
    @classmethod
    def _coerce_node_kind(cls, v: Any) -> str:
        if v is None or v == "":
            return "concept"
        s = str(v).strip()
        if s not in _ALLOWED_NODE_KINDS:
            raise ValueError(f"Invalid node_kind: {v}")
        return s


class GraphTaxonomy(BaseModel):
    """学科、层级等下拉选项（可由前端追加）。"""

    subjects: list[str] = Field(default_factory=lambda: ["数学"])
    levels: list[str] = Field(default_factory=lambda: ["高中", "高考"])


class NodeFileLink(BaseModel):
    id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1, description="相对 resource/ 的路径")
    created_at: datetime = Field(default_factory=_now_utc)


class NodeRelation(BaseModel):
    id: str = Field(min_length=1)
    from_node_id: str = Field(min_length=1)
    to_node_id: str = Field(min_length=1)
    relation_type: str


class QuestionBinding(BaseModel):
    question_qualified_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)


class GraphState(BaseModel):
    version: int = 1
    taxonomy: GraphTaxonomy = Field(default_factory=GraphTaxonomy)
    nodes: list[ConceptNode] = Field(default_factory=list)
    relations: list[NodeRelation] = Field(default_factory=list)
    bindings: list[QuestionBinding] = Field(default_factory=list)
    file_links: list[NodeFileLink] = Field(default_factory=list)


def _graph_dir(project_root: Path) -> Path:
    return (project_root / "resource" / _GRAPH_DIR_NAME).resolve()


def _state_path(project_root: Path) -> Path:
    return (_graph_dir(project_root) / _STATE_FILENAME).resolve()


def ensure_graph_layout(project_root: Path) -> None:
    """Ensure resource/graph/* exists."""
    graph_dir = _graph_dir(project_root)
    graph_dir.mkdir(parents=True, exist_ok=True)
    assert_within_project(project_root, graph_dir)

    sp = _state_path(project_root)
    assert_within_project(project_root, sp)
    if not sp.is_file():
        empty = GraphState()
        sp.write_text(
            yaml.safe_dump(empty.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def _migrate_legacy_graph_state(state: GraphState) -> bool:
    """将旧版 uses_skill 关系迁移为 related；技能语义由 node_kind=skill 表达。"""
    changed = False
    new_rels: list[NodeRelation] = []
    for r in state.relations:
        if r.relation_type == "uses_skill":
            new_rels.append(
                NodeRelation(
                    id=r.id,
                    from_node_id=r.from_node_id,
                    to_node_id=r.to_node_id,
                    relation_type="related",
                )
            )
            changed = True
        else:
            new_rels.append(r)
    state.relations = new_rels
    return changed


def _load_state(project_root: Path) -> GraphState:
    ensure_graph_layout(project_root)
    sp = _state_path(project_root)
    assert_within_project(project_root, sp)
    raw_text = sp.read_text(encoding="utf-8")
    if not raw_text.strip():
        return GraphState()
    data = yaml.safe_load(raw_text)
    if data is None:
        return GraphState()
    if not isinstance(data, dict):
        raise ValueError("Invalid graph state file")
    state = GraphState.model_validate(data)
    if _migrate_legacy_graph_state(state):
        _save_state(project_root, state)
    return state


def load_graph(project_root: Path) -> GraphState:
    """Load persisted graph state from ``resource/graph/state.yaml`` (public API)."""
    return _load_state(project_root)


def _node_kind_of(state: GraphState, node_id: str) -> str:
    for n in state.nodes:
        if n.id == node_id:
            return n.node_kind
    return "concept"


def _validate_relation_endpoints(state: GraphState, from_node_id: str, to_node_id: str) -> None:
    """技能节点与因果节点之间不可连边；至少一端须为知识点。"""
    kf = _node_kind_of(state, from_node_id)
    kt = _node_kind_of(state, to_node_id)
    if kf != "concept" and kt != "concept":
        raise ValueError("关系仅允许至少一端为知识点节点（技能与因果节点之间不可互连）")


def _save_state(project_root: Path, state: GraphState) -> None:
    ensure_graph_layout(project_root)
    sp = _state_path(project_root)
    assert_within_project(project_root, sp)
    payload = state.model_dump(mode="json")
    sp.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _slugify_name(name: str) -> str:
    buf: list[str] = []
    for ch in (name or "").strip():
        if ch.isascii() and ch.isalnum():
            buf.append(ch.lower())
        elif ch in " \t-_/":
            buf.append("-")
        elif "\u4e00" <= ch <= "\u9fff":
            buf.append(ch)
    s = "".join(buf).strip("-")
    s = re.sub(r"-+", "-", s)
    return (s[:48] if s else "node") or "node"


def generate_unique_node_id(project_root: Path, parent_node_id: str, canonical_name: str) -> str:
    parent = parent_node_id.strip().rstrip("/")
    if not parent:
        raise ValueError("parent_node_id required")
    base = f"{parent}/{_slugify_name(canonical_name)}"
    state = _load_state(project_root)
    existing = {n.id for n in state.nodes}
    if base not in existing:
        return base
    for _ in range(24):
        cand = f"{base}-{uuid.uuid4().hex[:6]}"
        if cand not in existing:
            return cand
    raise ValueError("Could not generate unique node id")


def get_taxonomy(project_root: Path) -> dict[str, Any]:
    state = _load_state(project_root)
    return state.taxonomy.model_dump(mode="json")


def set_taxonomy(project_root: Path, *, subjects: list[str] | None, levels: list[str] | None) -> None:
    state = _load_state(project_root)
    if subjects is not None:
        state.taxonomy.subjects = [s.strip() for s in subjects if s.strip()]
    if levels is not None:
        state.taxonomy.levels = [s.strip() for s in levels if s.strip()]
    _save_state(project_root, state)


def _resolve_resource_path(project_root: Path, relative_under_resource: str) -> Path:
    rel = relative_under_resource.strip().replace("\\", "/").lstrip("/")
    resource = (project_root / "resource").resolve()
    target = (resource / rel).resolve()
    try:
        target.relative_to(resource)
    except ValueError as e:
        raise ValueError("Path must stay under resource/") from e
    assert_within_project(project_root, target)
    return target


def list_resource_files(project_root: Path, query: str = "", *, limit: int = 800) -> list[dict[str, Any]]:
    """列出 resource/ 下文件（相对路径），供资料关联选择。"""
    resource = (project_root / "resource").resolve()
    assert_within_project(project_root, resource)
    q = (query or "").strip().lower()
    out: list[dict[str, Any]] = []
    if not resource.is_dir():
        return out
    for p in resource.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(resource).as_posix()
        except ValueError:
            continue
        if any(part.startswith(".") for part in Path(rel).parts):
            continue
        if q and q not in rel.lower():
            continue
        try:
            st = p.stat()
            sz = int(st.st_size)
        except OSError:
            sz = 0
        out.append({"path": rel, "size": sz})
        if len(out) >= limit * 4:
            break
    out.sort(key=lambda x: x["path"])
    return out[:limit]


def list_file_links_for_node(project_root: Path, node_id: str) -> list[dict[str, Any]]:
    state = _load_state(project_root)
    return [l.model_dump(mode="json") for l in state.file_links if l.node_id == node_id]


def attach_file_to_node(project_root: Path, node_id: str, relative_path: str) -> str:
    state = _load_state(project_root)
    if not any(n.id == node_id for n in state.nodes):
        raise ValueError(f"Node not found: {node_id}")
    rel = relative_path.strip().replace("\\", "/").lstrip("/")
    target = _resolve_resource_path(project_root, rel)
    if not target.is_file():
        raise ValueError("File does not exist")
    for l in state.file_links:
        if l.node_id == node_id and l.relative_path == rel:
            return l.id
    link_id = uuid.uuid4().hex
    state.file_links.append(
        NodeFileLink(id=link_id, node_id=node_id, relative_path=rel),
    )
    _save_state(project_root, state)
    return link_id


def detach_file_link(project_root: Path, link_id: str) -> None:
    state = _load_state(project_root)
    state.file_links = [l for l in state.file_links if l.id != link_id]
    _save_state(project_root, state)


def list_concept_nodes(project_root: Path, *, node_kind: str | None = None) -> list[dict[str, Any]]:
    state = _load_state(project_root)
    rows = [n.model_dump(mode="json") for n in state.nodes]
    if node_kind is not None:
        nk = node_kind.strip()
        if nk not in _ALLOWED_NODE_KINDS:
            raise ValueError(f"Invalid node_kind filter: {node_kind}")
        rows = [r for r in rows if r.get("node_kind") == nk]
    file_counts: dict[str, int] = {}
    for l in state.file_links:
        nid = l.node_id
        file_counts[nid] = file_counts.get(nid, 0) + 1
    for r in rows:
        r["file_link_count"] = file_counts.get(r["id"], 0)
    return rows


def count_nodes_by_kind(project_root: Path) -> dict[str, int]:
    state = _load_state(project_root)
    out: dict[str, int] = {k: 0 for k in sorted(_ALLOWED_NODE_KINDS)}
    for n in state.nodes:
        k = n.node_kind
        out[k] = out.get(k, 0) + 1
    return out


def get_concept_node(project_root: Path, node_id: str) -> dict[str, Any]:
    state = _load_state(project_root)
    for n in state.nodes:
        if n.id == node_id:
            return n.model_dump(mode="json")
    raise FileNotFoundError(f"Node not found: {node_id}")


def create_concept_node(project_root: Path, payload: dict[str, Any]) -> str:
    state = _load_state(project_root)
    node = ConceptNode.model_validate(payload)
    if any(n.id == node.id for n in state.nodes):
        raise ValueError(f"Node already exists: {node.id}")
    state.nodes.append(node)
    _save_state(project_root, state)
    return node.id


def update_concept_node(project_root: Path, node_id: str, payload: dict[str, Any]) -> None:
    state = _load_state(project_root)
    if not any(n.id == node_id for n in state.nodes):
        raise FileNotFoundError(f"Node not found: {node_id}")

    # ID 以 URL 为准；payload 中如果带 id 也会被覆盖，避免不一致。
    data = dict(payload)
    data["id"] = node_id
    updated = ConceptNode.model_validate(data)

    # 保留创建时间，仅更新 updated_at。
    for i, n in enumerate(state.nodes):
        if n.id == node_id:
            updated.created_at = n.created_at
            updated.updated_at = _now_utc()
            state.nodes[i] = updated
            break

    _save_state(project_root, state)


def delete_concept_node(project_root: Path, node_id: str) -> None:
    state = _load_state(project_root)
    if not any(n.id == node_id for n in state.nodes):
        # 删除不存在节点视为幂等
        pass

    state.nodes = [n for n in state.nodes if n.id != node_id]
    state.relations = [
        r for r in state.relations if r.from_node_id != node_id and r.to_node_id != node_id
    ]
    state.bindings = [b for b in state.bindings if b.node_id != node_id]
    state.file_links = [l for l in state.file_links if l.node_id != node_id]
    _save_state(project_root, state)


def list_node_relations(project_root: Path) -> list[dict[str, Any]]:
    state = _load_state(project_root)
    return [r.model_dump(mode="json") for r in state.relations]


def create_node_relation(project_root: Path, payload: dict[str, Any]) -> str:
    state = _load_state(project_root)
    node_ids = {n.id for n in state.nodes}

    from_node_id = str(payload.get("from_node_id") or "").strip()
    to_node_id = str(payload.get("to_node_id") or "").strip()
    relation_type = str(payload.get("relation_type") or "").strip()

    if not from_node_id or not to_node_id or not relation_type:
        raise ValueError("relation requires from_node_id, to_node_id, relation_type")
    if relation_type not in _ALLOWED_RELATION_TYPES:
        raise ValueError(f"Invalid relation_type: {relation_type}")
    if from_node_id not in node_ids or to_node_id not in node_ids:
        raise ValueError("Both from/to nodes must exist before creating relation")
    _validate_relation_endpoints(state, from_node_id, to_node_id)

    for r in state.relations:
        if (
            r.from_node_id == from_node_id
            and r.to_node_id == to_node_id
            and r.relation_type == relation_type
        ):
            return r.id

    rel_id = uuid.uuid4().hex
    rel = NodeRelation(
        id=rel_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        relation_type=relation_type,
    )
    state.relations.append(rel)
    _save_state(project_root, state)
    return rel_id


def delete_node_relation(project_root: Path, relation_id: str) -> None:
    state = _load_state(project_root)
    state.relations = [r for r in state.relations if r.id != relation_id]
    _save_state(project_root, state)


def bind_question_to_node(project_root: Path, payload: dict[str, Any]) -> None:
    state = _load_state(project_root)
    node_ids = {n.id for n in state.nodes}

    qid = str(payload.get("question_qualified_id") or "").strip()
    node_id = str(payload.get("node_id") or "").strip()
    if not qid or not node_id:
        raise ValueError("binding requires question_qualified_id and node_id")
    if node_id not in node_ids:
        raise ValueError(f"Node not found: {node_id}")

    pair = (qid, node_id)
    if any((b.question_qualified_id, b.node_id) == pair for b in state.bindings):
        return
    state.bindings.append(QuestionBinding(question_qualified_id=qid, node_id=node_id))
    _save_state(project_root, state)


def unbind_question_from_node(project_root: Path, payload: dict[str, Any]) -> None:
    state = _load_state(project_root)
    qid = str(payload.get("question_qualified_id") or "").strip()
    node_id = str(payload.get("node_id") or "").strip()
    state.bindings = [
        b for b in state.bindings if not (b.question_qualified_id == qid and b.node_id == node_id)
    ]
    _save_state(project_root, state)


def list_questions_for_node(project_root: Path, node_id: str) -> list[str]:
    state = _load_state(project_root)
    qids = [b.question_qualified_id for b in state.bindings if b.node_id == node_id]
    # 保序 + 去重（bindings 在文件里可能存在重复）
    seen: set[str] = set()
    out: list[str] = []
    for q in qids:
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
    return out


def list_nodes_for_question(project_root: Path, question_qualified_id: str) -> list[ConceptNode]:
    """Return concept nodes that have a binding to the given question qualified id."""
    state = _load_state(project_root)
    qid = (question_qualified_id or "").strip()
    if not qid:
        return []
    node_ids = {b.node_id for b in state.bindings if b.question_qualified_id == qid}
    by_id = {n.id: n for n in state.nodes}
    out: list[ConceptNode] = []
    seen: set[str] = set()
    for nid in sorted(node_ids):
        if nid in seen:
            continue
        n = by_id.get(nid)
        if n is not None:
            seen.add(nid)
            out.append(n)
    return out


def bind_questions_batch(
    project_root: Path,
    *,
    node_id: str,
    qualified_ids: list[str],
) -> dict[str, Any]:
    """Bind multiple questions to one node; idempotent for existing pairs."""
    state = _load_state(project_root)
    node_ids_set = {n.id for n in state.nodes}
    nid = (node_id or "").strip()
    if not nid:
        raise ValueError("node_id required")
    if nid not in node_ids_set:
        raise ValueError(f"Node not found: {nid}")
    added = 0
    skipped = 0
    existing_pairs = {(b.question_qualified_id, b.node_id) for b in state.bindings}
    for raw in qualified_ids:
        qid = (raw or "").strip()
        if not qid:
            skipped += 1
            continue
        pair = (qid, nid)
        if pair in existing_pairs:
            skipped += 1
            continue
        state.bindings.append(QuestionBinding(question_qualified_id=qid, node_id=nid))
        existing_pairs.add(pair)
        added += 1
    if added:
        _save_state(project_root, state)
    return {"added": added, "skipped": skipped}


def unbind_questions_batch(
    project_root: Path,
    *,
    node_id: str,
    qualified_ids: list[str],
) -> dict[str, Any]:
    """Remove bindings for multiple questions from one node."""
    state = _load_state(project_root)
    nid = (node_id or "").strip()
    if not nid:
        raise ValueError("node_id required")
    target = {(q or "").strip() for q in qualified_ids if (q or "").strip()}
    if not target:
        return {"removed": 0}
    before = len(state.bindings)
    state.bindings = [
        b for b in state.bindings if not (b.node_id == nid and b.question_qualified_id in target)
    ]
    removed = before - len(state.bindings)
    if removed:
        _save_state(project_root, state)
    return {"removed": removed}
