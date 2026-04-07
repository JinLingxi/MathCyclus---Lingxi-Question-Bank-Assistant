"""Knowledge graph tools via knowledge_forge public API."""

from __future__ import annotations

from typing import Any

from solaire.agent_layer.models import InvocationContext, ToolResult
from solaire.knowledge_forge import (
    attach_file_to_node,
    bind_question_to_node,
    bind_questions_batch,
    count_nodes_by_kind,
    create_concept_node,
    create_node_relation,
    delete_concept_node,
    delete_node_relation,
    generate_unique_node_id,
    get_concept_node,
    list_concept_nodes,
    list_node_relations,
    update_concept_node,
)


def tool_list_nodes(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    nk = args.get("node_kind")
    nk_s = str(nk).strip() if nk else None
    try:
        nodes = list_concept_nodes(ctx.project_root, node_kind=nk_s or None)
        counts = count_nodes_by_kind(ctx.project_root)
    except ValueError as e:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message=str(e))
    return ToolResult(status="succeeded", data={"nodes": nodes, "kind_counts": counts})


def _node_payload_from_args(args: dict[str, Any]) -> dict[str, Any]:
    """Map agent args to ConceptNode fields (exclude None)."""
    keys = (
        "id",
        "canonical_name",
        "node_kind",
        "aliases",
        "subject",
        "level",
        "description",
        "tags",
        "source",
        "layout_x",
        "layout_y",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in args and args[k] is not None:
            out[k] = args[k]
    return out


def tool_create_node(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    root = ctx.project_root
    body = _node_payload_from_args(args)
    canonical_name = str(body.get("canonical_name") or "").strip()
    if not canonical_name:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="canonical_name 必填")
    node_id = str(args.get("id") or "").strip() or None
    parent = str(args.get("parent_node_id") or "").strip() or None
    payload = {k: v for k, v in body.items() if k != "id"}
    try:
        if not node_id:
            if not parent:
                return ToolResult(
                    status="failed",
                    error_code="invalid_arguments",
                    error_message="新建节点需提供 parent_node_id 以自动生成标识，或显式提供 id",
                )
            nid = generate_unique_node_id(root, parent, canonical_name)
            payload["id"] = nid
            create_concept_node(root, payload)
            create_node_relation(
                root,
                {"from_node_id": nid, "to_node_id": parent, "relation_type": "part_of"},
            )
            return ToolResult(status="succeeded", data={"ok": True, "node_id": nid})
        payload["id"] = node_id
        create_concept_node(root, payload)
        if parent:
            create_node_relation(
                root,
                {"from_node_id": node_id, "to_node_id": parent, "relation_type": "part_of"},
            )
        return ToolResult(status="succeeded", data={"ok": True, "node_id": node_id})
    except ValueError as e:
        return ToolResult(status="failed", error_code="conflict", error_message=str(e))


def tool_update_node(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    root = ctx.project_root
    node_id = str(args.get("node_id") or "").strip()
    if not node_id:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="node_id 必填")
    try:
        existing = get_concept_node(root, node_id)
    except FileNotFoundError:
        return ToolResult(status="failed", error_code="not_found", error_message="节点不存在")
    incoming = _node_payload_from_args(args)
    merged = {**existing, **incoming, "id": node_id}
    try:
        update_concept_node(root, node_id, merged)
    except (FileNotFoundError, ValueError) as e:
        return ToolResult(status="failed", error_code="runtime_error", error_message=str(e))
    return ToolResult(status="succeeded", data={"ok": True})


def tool_delete_node(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    node_id = str(args.get("node_id") or "").strip()
    if not node_id:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="node_id 必填")
    delete_concept_node(ctx.project_root, node_id)
    return ToolResult(status="succeeded", data={"ok": True})


def tool_create_relation(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    try:
        rel_id = create_node_relation(ctx.project_root, args)
    except ValueError as e:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message=str(e))
    return ToolResult(status="succeeded", data={"ok": True, "relation_id": rel_id})


def tool_delete_relation(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    rid = str(args.get("relation_id") or "").strip()
    if not rid:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="relation_id 必填")
    delete_node_relation(ctx.project_root, rid)
    return ToolResult(status="succeeded", data={"ok": True})


def tool_bind_question(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    try:
        bind_question_to_node(
            ctx.project_root,
            {
                "question_qualified_id": str(args.get("question_qualified_id") or ""),
                "node_id": str(args.get("node_id") or ""),
            },
        )
    except ValueError as e:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message=str(e))
    return ToolResult(status="succeeded", data={"ok": True})


def tool_attach_resource(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    node_id = str(args.get("node_id") or "").strip()
    rel_path = str(args.get("relative_path") or "").strip()
    if not node_id or not rel_path:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="node_id 与 relative_path 必填")
    try:
        link_id = attach_file_to_node(ctx.project_root, node_id, rel_path)
    except ValueError as e:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message=str(e))
    return ToolResult(status="succeeded", data={"ok": True, "link_id": link_id})


def tool_list_relations(ctx: InvocationContext, _args: dict[str, Any]) -> ToolResult:
    rels = list_node_relations(ctx.project_root)
    return ToolResult(status="succeeded", data={"relations": rels})


def _node_text_blob(n: dict[str, Any]) -> str:
    parts = [
        str(n.get("canonical_name") or ""),
        str(n.get("description") or ""),
        str(n.get("id") or ""),
    ]
    for a in n.get("aliases") or []:
        parts.append(str(a))
    return " ".join(parts).lower()


def tool_search_nodes(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    q_raw = str(args.get("query") or "").strip()
    if not q_raw:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="query 必填")
    nk = args.get("node_kind")
    nk_s = str(nk).strip() if nk else None
    max_hits = args.get("max_hits")
    try:
        mh = int(max_hits) if max_hits is not None else 30
    except (TypeError, ValueError):
        mh = 30
    mh = max(1, min(mh, 200))
    try:
        nodes = list_concept_nodes(ctx.project_root, node_kind=nk_s or None)
    except ValueError as e:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message=str(e))
    q = q_raw.lower()
    tokens = [t for t in q.split() if t]
    hits: list[dict[str, Any]] = []
    for n in nodes:
        blob = _node_text_blob(n)
        if q in blob or (tokens and all(t in blob for t in tokens)):
            hits.append(n)
            if len(hits) >= mh:
                break
    return ToolResult(
        status="succeeded",
        data={"nodes": hits, "total_scanned": len(nodes), "max_hits": mh},
    )


def tool_batch_create_nodes(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    raw = args.get("nodes")
    if not isinstance(raw, list) or not raw:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="nodes 须为非空数组")
    root = ctx.project_root
    created: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append({"index": i, "error": "条目须为对象"})
            continue
        body = _node_payload_from_args(item)
        canonical_name = str(body.get("canonical_name") or "").strip()
        if not canonical_name:
            errors.append({"index": i, "error": "canonical_name 必填"})
            continue
        node_id = str(item.get("id") or "").strip() or None
        parent = str(item.get("parent_node_id") or "").strip() or None
        payload = {k: v for k, v in body.items() if k != "id"}
        try:
            if not node_id:
                if not parent:
                    errors.append({"index": i, "error": "需提供 parent_node_id 或 id"})
                    continue
                nid = generate_unique_node_id(root, parent, canonical_name)
                payload["id"] = nid
                create_concept_node(root, payload)
                create_node_relation(
                    root,
                    {"from_node_id": nid, "to_node_id": parent, "relation_type": "part_of"},
                )
                created.append({"index": i, "node_id": nid})
            else:
                payload["id"] = node_id
                create_concept_node(root, payload)
                if parent:
                    create_node_relation(
                        root,
                        {"from_node_id": node_id, "to_node_id": parent, "relation_type": "part_of"},
                    )
                created.append({"index": i, "node_id": node_id})
        except ValueError as e:
            errors.append({"index": i, "error": str(e)})
    ok_n, err_n = len(created), len(errors)
    data: dict[str, Any] = {
        "created": created,
        "errors": errors,
        "ok_count": ok_n,
        "error_count": err_n,
        "partial_success": ok_n > 0 and err_n > 0,
    }
    if ok_n == 0 and err_n > 0:
        return ToolResult(
            status="failed",
            error_code="batch_all_failed",
            error_message="批量创建要点全部未成功，请查看 errors 明细。",
            data=data,
        )
    return ToolResult(status="succeeded", data=data)


def tool_batch_bind_questions(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    raw = args.get("bindings")
    if not isinstance(raw, list) or not raw:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="bindings 须为非空数组")
    root = ctx.project_root
    by_node: dict[str, list[str]] = {}
    errors: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append({"index": i, "error": "条目须为对象"})
            continue
        qid = str(item.get("question_qualified_id") or "").strip()
        nid = str(item.get("node_id") or "").strip()
        if not qid or not nid:
            errors.append({"index": i, "error": "question_qualified_id 与 node_id 必填"})
            continue
        by_node.setdefault(nid, []).append(qid)
    batches: list[dict[str, Any]] = []
    for node_id, qids in by_node.items():
        try:
            stats = bind_questions_batch(root, node_id=node_id, qualified_ids=qids)
            batches.append({"node_id": node_id, **stats})
        except ValueError as e:
            batches.append({"node_id": node_id, "error": str(e)})
    ok_batches = [b for b in batches if "error" not in b]
    failed_batches = [b for b in batches if "error" in b]
    parse_err_n = len(errors)
    data = {
        "batches": batches,
        "parse_errors": errors,
        "ok_count": len(ok_batches),
        "error_count": len(failed_batches) + parse_err_n,
        "partial_success": (len(failed_batches) > 0 or parse_err_n > 0) and len(ok_batches) > 0,
    }
    if not batches and errors:
        return ToolResult(
            status="failed",
            error_code="batch_all_failed",
            error_message="未能解析任何有效的题目与要点绑定项。",
            data=data,
        )
    if batches and not ok_batches:
        return ToolResult(
            status="failed",
            error_code="batch_all_failed",
            error_message="按要点批量挂接全部未成功，请查看 batches 中的 error。",
            data=data,
        )
    return ToolResult(status="succeeded", data=data)


def tool_batch_create_relations(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    raw = args.get("relations")
    if not isinstance(raw, list) or not raw:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="relations 须为非空数组")
    root = ctx.project_root
    created: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append({"index": i, "error": "条目须为对象"})
            continue
        try:
            rel_id = create_node_relation(
                root,
                {
                    "from_node_id": str(item.get("from_node_id") or ""),
                    "to_node_id": str(item.get("to_node_id") or ""),
                    "relation_type": str(item.get("relation_type") or ""),
                },
            )
            created.append({"index": i, "relation_id": rel_id})
        except ValueError as e:
            errors.append({"index": i, "error": str(e)})
    ok_n, err_n = len(created), len(errors)
    data = {
        "created": created,
        "errors": errors,
        "ok_count": ok_n,
        "error_count": err_n,
        "partial_success": ok_n > 0 and err_n > 0,
    }
    if ok_n == 0 and err_n > 0:
        return ToolResult(
            status="failed",
            error_code="batch_all_failed",
            error_message="批量建立关联全部未成功，请查看 errors 明细。",
            data=data,
        )
    return ToolResult(status="succeeded", data=data)
