"""Tests for M3 agent_layer registry, memory, guardrails (no live LLM)."""

from __future__ import annotations

from pathlib import Path

from solaire.agent_layer.guardrails import (
    GuardrailDecision,
    SAFETY_MODE_PRESTISSIMO,
    SAFETY_MODE_VIVACE,
    check_tool_call,
    save_safety_mode,
    vivace_needs_fast_model_review,
)
from solaire.agent_layer.memory import (
    ensure_memory_layout,
    list_topic_filenames,
    merge_index_bullet,
    read_index,
    write_index,
    write_topic,
)
from solaire.agent_layer.models import InvocationContext, SessionState
from solaire.agent_layer.plan_document import load_plan_steps_from_rel_path, steps_from_plan_body
from solaire.agent_layer.registry import invoke_registered_tool, openai_tools_payload, select_tools_for_turn
from solaire.agent_layer.tool_executor import consecutive_subtask_tool_indices
from solaire.agent_layer.tools import file_tools


def test_openai_tools_payload_contains_analysis_and_memory():
    tools = openai_tools_payload()
    names = {t["function"]["name"] for t in tools}
    assert "analysis.list_datasets" in names
    assert "memory.read_index" in names
    assert "agent.set_task_plan" in names
    assert "agent.run_subtask" in names
    assert "graph.search_nodes" in names
    assert "graph.batch_bind_questions" in names
    assert "web.search" in names
    assert "agent.run_tool_pipeline" in names
    assert "agent.read_skill_reference" in names


def test_read_skill_reference_builtin_primebrush(tmp_path: Path) -> None:
    """技能 references 不在教师项目内，须通过专用工具从技能包读取。"""
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool(
        "agent.read_skill_reference",
        {"name": "primebrush_diagrams", "path": "references/geometry-2d.md"},
        ctx,
    )
    assert tr.status == "succeeded"
    content = tr.data.get("content", "")
    assert "geometry_2d" in content


def test_read_skill_reference_rejects_path_traversal(tmp_path: Path) -> None:
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool(
        "agent.read_skill_reference",
        {"name": "primebrush_diagrams", "path": "references/../../../pyproject.toml"},
        ctx,
    )
    assert tr.status == "failed"


def test_invoke_list_datasets(tmp_path: Path) -> None:
    # No result port configured in isolated tmp project — expect failure or empty
    from solaire.edu_analysis.ports import configure as configure_edu
    from solaire.web.result_service import ResultServiceAdapter

    configure_edu(result_port=ResultServiceAdapter())
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool("analysis.list_datasets", {}, ctx)
    assert tr.status == "succeeded"
    assert "datasets" in tr.data


def test_memory_layout(tmp_path: Path) -> None:
    ensure_memory_layout(tmp_path)
    idx = read_index(tmp_path)
    assert "记忆索引" in idx
    write_topic(tmp_path, "analysis_history.md", "- test line\n")
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool("memory.read_topic", {"topic": "analysis_history.md"}, ctx)
    assert tr.status == "succeeded"
    assert "test line" in tr.data.get("content", "")


def test_merge_index_self_heal(tmp_path: Path) -> None:
    ensure_memory_layout(tmp_path)
    write_index(tmp_path, "## 记忆索引\n- [分析记录](analysis_history.md): 月考薄弱点为函数\n")
    assert merge_index_bullet(
        tmp_path,
        "[分析记录](analysis_history.md): 月考薄弱点为函数与几何综合题",
    )
    idx = read_index(tmp_path)
    assert "几何" in idx
    assert idx.count("[分析记录]") <= 1


def test_list_topics_after_write(tmp_path: Path) -> None:
    ensure_memory_layout(tmp_path)
    write_topic(tmp_path, "note_a.md", "hello")
    names = list_topic_filenames(tmp_path)
    assert "note_a.md" in names


def test_agent_task_plan_tools(tmp_path: Path) -> None:
    sess = SessionState(session_id="t1")
    ctx = InvocationContext(project_root=tmp_path, session_id="t1", session=sess)
    tr = invoke_registered_tool(
        "agent.set_task_plan",
        {"steps": [{"title": "查数据", "status": "pending"}, {"title": "写结论", "status": "pending"}]},
        ctx,
    )
    assert tr.status == "succeeded"
    assert len(sess.task_plan) == 2
    tr2 = invoke_registered_tool("agent.update_task_step", {"index": 0, "status": "done"}, ctx)
    assert tr2.status == "succeeded"
    assert sess.task_plan[0]["status"] == "done"


def test_graph_search_nodes_empty_project(tmp_path: Path) -> None:
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool("graph.search_nodes", {"query": "测试"}, ctx)
    assert tr.status == "succeeded"
    assert "nodes" in tr.data


def test_guardrail_read_vs_export(tmp_path: Path) -> None:
    sess = SessionState(session_id="x")
    ctx = InvocationContext(project_root=tmp_path, session_id="x", session=sess, mode="execute")
    assert check_tool_call("analysis.list_datasets", {}, ctx) == GuardrailDecision.AUTO_APPROVE
    assert check_tool_call("exam.export_paper", {}, ctx) == GuardrailDecision.NEEDS_CONFIRMATION


def test_openai_compat_assistant_tool_calls_get_reasoning_placeholder() -> None:
    """thinking 网关要求回放 assistant+tool_calls 时含 reasoning_content（子任务等路径此前会漏）。"""
    from solaire.agent_layer.llm.openai_compat import _ensure_assistant_tool_calls_have_reasoning

    msgs: list = [
        {"role": "system", "content": "x"},
        {"role": "user", "content": "y"},
        {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
    ]
    _ensure_assistant_tool_calls_have_reasoning(msgs)
    assert msgs[2].get("reasoning_content") == ""
    msgs2 = [{"role": "assistant", "tool_calls": [{"id": "c1"}], "reasoning_content": "已有"}]
    _ensure_assistant_tool_calls_have_reasoning(msgs2)
    assert msgs2[0]["reasoning_content"] == "已有"


def test_compact_for_llm_preserves_graph_node_total() -> None:
    """超大 graph.list_nodes 结果不得被压成空 dict，否则模型会误判图谱无节点。"""
    from solaire.agent_layer.compactor import compact_for_llm
    from solaire.agent_layer.context import tool_result_to_content

    big_nodes = [
        {
            "id": f"math/n{i}",
            "canonical_name": f"节点{i}" * 30,
            "node_kind": "concept",
            "subject": "数学",
            "level": "高考",
            "description": "x" * 400,
        }
        for i in range(120)
    ]
    payload = {"nodes": big_nodes, "kind_counts": {"causal": 0, "concept": 120, "skill": 0}}
    compacted, _ = compact_for_llm(payload, max_chars=10000)
    assert isinstance(compacted, dict)
    assert compacted.get("node_total") == 120
    assert compacted.get("kind_counts") == payload["kind_counts"]
    assert isinstance(compacted.get("nodes"), list)
    assert len(compacted["nodes"]) >= 1
    text = tool_result_to_content("graph.list_nodes", payload)
    assert "node_total" in text
    assert '"120"' in text or "120" in text


def test_vivace_needs_fast_model_review_flags() -> None:
    assert vivace_needs_fast_model_review("graph.delete_node") is True
    assert vivace_needs_fast_model_review("memory.read_index") is False


def test_vivace_pipeline_blocks_fast_review_tool(tmp_path: Path) -> None:
    save_safety_mode(tmp_path, SAFETY_MODE_VIVACE)
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool(
        "agent.run_tool_pipeline",
        {
            "steps": [
                {"tool": "graph.delete_node", "arguments": {"node_id": "missing"}},
            ]
        },
        ctx,
    )
    assert tr.status == "failed"
    assert tr.error_code == "needs_confirmation"
    assert tr.error_message and "管道" in tr.error_message


def test_vivace_pipeline_allows_read_step(tmp_path: Path) -> None:
    ensure_memory_layout(tmp_path)
    save_safety_mode(tmp_path, SAFETY_MODE_VIVACE)
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool(
        "agent.run_tool_pipeline",
        {"steps": [{"tool": "memory.read_index", "arguments": {}}]},
        ctx,
    )
    assert tr.status == "succeeded"


def test_batch_create_nodes_all_failed_status(tmp_path: Path) -> None:
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool(
        "graph.batch_create_nodes",
        {"nodes": [{"canonical_name": "", "parent_node_id": "p"}]},
        ctx,
    )
    assert tr.status == "failed"
    assert tr.error_code == "batch_all_failed"
    assert tr.data.get("error_count", 0) >= 1


def test_batch_create_nodes_partial_success_reports_counts(tmp_path: Path) -> None:
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool(
        "graph.batch_create_nodes",
        {
            "nodes": [
                {"canonical_name": ""},
                {"id": "math/t1", "canonical_name": "测试根要点", "node_kind": "concept"},
            ]
        },
        ctx,
    )
    assert tr.status == "succeeded"
    assert tr.data.get("partial_success") is True
    assert tr.data.get("ok_count") == 1
    assert tr.data.get("error_count") == 1
    from solaire.agent_layer.compactor import summarize_tool_result

    summ = summarize_tool_result("graph.batch_create_nodes", tr.data)
    assert "成功" in summ and "未成功" in summ


def test_batch_bind_questions_parse_only_fails(tmp_path: Path) -> None:
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=SessionState(session_id="s1"))
    tr = invoke_registered_tool(
        "graph.batch_bind_questions",
        {"bindings": [{"question_qualified_id": "", "node_id": ""}]},
        ctx,
    )
    assert tr.status == "failed"
    assert tr.error_code == "batch_all_failed"


def test_consecutive_subtask_indices_two_under_prestissimo(tmp_path: Path) -> None:
    save_safety_mode(tmp_path, SAFETY_MODE_PRESTISSIMO)
    sess = SessionState(session_id="s1")
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=sess, mode="execute")
    tcs = [
        {"function": {"name": "agent.run_subtask", "arguments": '{"objective":"a"}'}},
        {"function": {"name": "agent.run_subtask", "arguments": '{"objective":"b"}'}},
    ]
    idx = consecutive_subtask_tool_indices(tcs, 0, ctx, SAFETY_MODE_PRESTISSIMO)
    assert idx == [0, 1]


def test_select_tools_plan_mode_merges_file_write_edit(tmp_path: Path) -> None:
    names = {
        t.name
        for t in select_tools_for_turn(
            current_page=None,
            skill_id=None,
            include_subtask=False,
            current_focus="general",
            project_root=tmp_path,
            plan_mode_active=True,
        )
    }
    assert "file.write" in names
    assert "file.edit" in names


def test_plan_mode_write_restricted_to_plans_dir(tmp_path: Path) -> None:
    sess = SessionState(session_id="s1", plan_mode_active=True)
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=sess)
    tr = file_tools.tool_file_write(ctx, {"path": "other/file.md", "content": "x"})
    assert tr.status == "failed"
    assert tr.error_message and "plans" in tr.error_message


def test_plan_mode_plan_md_requires_yaml_todos(tmp_path: Path) -> None:
    sess = SessionState(session_id="s1", plan_mode_active=True)
    ctx = InvocationContext(project_root=tmp_path, session_id="s1", session=sess)
    rel = ".solaire/agent/plans/p.md"
    bad_fm = file_tools.tool_file_write(ctx, {"path": rel, "content": "# no frontmatter\n"})
    assert bad_fm.status == "failed"
    good = file_tools.tool_file_write(
        ctx,
        {
            "path": rel,
            "content": (
                "---\n"
                "name: t\n"
                "overview: o\n"
                "todos:\n"
                "  - id: a\n"
                "    content: c\n"
                "    status: pending\n"
                "---\n"
                "\n"
                "## 正文\n"
            ),
        },
    )
    assert good.status == "succeeded"


def test_steps_from_plan_body_maps_todos() -> None:
    text = (
        "---\n"
        "name: n\n"
        "overview: o\n"
        "todos:\n"
        "  - id: x1\n"
        "    content: 第一步\n"
        "    status: pending\n"
        "  - id: x2\n"
        "    content: 第二步\n"
        "    status: done\n"
        "---\n"
        "\n"
        "## 正文\n"
    )
    steps = steps_from_plan_body(text)
    assert len(steps) == 2
    assert steps[0]["title"] == "x1: 第一步"
    assert steps[0]["status"] == "pending"
    assert steps[1]["title"] == "x2: 第二步"
    assert steps[1]["status"] == "done"


def test_load_plan_steps_from_rel_path_reads_file(tmp_path: Path) -> None:
    rel = ".solaire/agent/plans/t.md"
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        "name: n\n"
        "overview: o\n"
        "todos:\n"
        "  - id: only\n"
        "    content: 任务\n"
        "    status: pending\n"
        "---\n\n",
        encoding="utf-8",
    )
    steps = load_plan_steps_from_rel_path(tmp_path, rel)
    assert len(steps) == 1
    assert "任务" in steps[0]["title"]
