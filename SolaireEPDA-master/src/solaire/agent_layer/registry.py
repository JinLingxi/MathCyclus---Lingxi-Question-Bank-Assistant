"""Unified tool registry + OpenAI function schemas."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from solaire.agent_layer.models import InvocationContext, ToolResult, ToolRisk
from solaire.agent_layer.tools import (
    analysis_tools,
    bank_tools,
    doc_tools,
    exam_tools,
    file_tools,
    graph_tools,
    memory_tools,
    pipeline_tools,
    session_tools,
    web_tools,
)

ToolHandler = Callable[[InvocationContext, dict[str, Any]], ToolResult]


@dataclass
class RegisteredTool:
    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: ToolHandler
    risk: ToolRisk = ToolRisk.WRITE
    ui_label: str | None = None
    requires_confirmation_override: bool | None = None
    allegro_auto_add: bool = False
    vivace_fast_review: bool = False
    action_label: str | None = None


def _fn(
    name: str,
    description: str,
    parameters: dict[str, Any],
    handler: ToolHandler,
    *,
    risk: ToolRisk = ToolRisk.WRITE,
    ui_label: str | None = None,
    requires_confirmation_override: bool | None = None,
    allegro_auto_add: bool = False,
    vivace_fast_review: bool = False,
    action_label: str | None = None,
) -> RegisteredTool:
    return RegisteredTool(
        name=name,
        description=description,
        parameters_schema=parameters,
        handler=handler,
        risk=risk,
        ui_label=ui_label,
        requires_confirmation_override=requires_confirmation_override,
        allegro_auto_add=allegro_auto_add,
        vivace_fast_review=vivace_fast_review,
        action_label=action_label,
    )


def _analysis(
    name: str,
    description: str,
    parameters: dict[str, Any],
    *,
    risk: ToolRisk = ToolRisk.WRITE,
    ui_label: str | None = None,
    allegro_auto_add: bool = False,
    vivace_fast_review: bool = False,
    action_label: str | None = None,
) -> RegisteredTool:
    return _fn(
        name,
        description,
        parameters,
        lambda ctx, args: analysis_tools.run_analysis_tool(ctx, name, args),
        risk=risk,
        ui_label=ui_label,
        allegro_auto_add=allegro_auto_add,
        vivace_fast_review=vivace_fast_review,
        action_label=action_label,
    )


_RAW_TOOLS: list[RegisteredTool] = [
    _analysis(
        "analysis.list_datasets",
        "列出当前项目中可用的考试成绩数据集（考试与批次）。",
        {"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.READ,
        ui_label="正在读取考试数据列表…",
    ),
    _analysis(
        "analysis.list_builtins",
        "列出可用的内置分析流水线标识。",
        {"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.READ,
        ui_label="正在读取可用分析类型…",
    ),
    _analysis(
        "analysis.run_builtin",
        "运行一条内置分析流水线并创建作业；完成后可用 analysis.get_job 取结果。",
        {
            "type": "object",
            "properties": {
                "builtin_id": {"type": "string"},
                "exam_id": {"type": "string"},
                "batch_id": {"type": "string"},
                "recompute": {"type": "boolean"},
                "request_id": {"type": "string"},
            },
            "required": ["builtin_id", "exam_id", "batch_id"],
            "additionalProperties": False,
        },
        ui_label="正在启动学情分析…",
        allegro_auto_add=True,
    ),
    _analysis(
        "analysis.save_script",
        "保存或更新一条分析脚本（执行受沙箱限制）。",
        {
            "type": "object",
            "properties": {
                "script_id": {"type": "string"},
                "name": {"type": "string"},
                "language": {"type": "string"},
                "code": {"type": "string"},
            },
            "required": ["name", "code"],
            "additionalProperties": False,
        },
        ui_label="正在保存分析脚本…",
    ),
    _analysis(
        "analysis.run_script",
        "在沙箱中运行已保存的分析脚本。",
        {
            "type": "object",
            "properties": {
                "script_id": {"type": "string"},
                "exam_id": {"type": "string"},
                "batch_id": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["script_id", "exam_id", "batch_id"],
            "additionalProperties": False,
        },
        ui_label="正在运行分析脚本…",
        allegro_auto_add=True,
    ),
    _analysis(
        "analysis.get_job",
        "按作业标识获取分析作业状态与输出。",
        {
            "type": "object",
            "properties": {"job_id": {"type": "string"}, "include_output": {"type": "boolean"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
        risk=ToolRisk.READ,
        ui_label="正在查询分析进度…",
    ),
    _fn(
        "exam.list_templates",
        "列出项目内试卷模板（路径、小节与版式信息）。",
        {"type": "object", "properties": {}, "additionalProperties": False},
        exam_tools.tool_list_templates,
        risk=ToolRisk.READ,
        ui_label="正在读取试卷模板…",
    ),
    _fn(
        "exam.get_template_preview",
        "读取指定模板 YAML 的结构化预览。",
        {
            "type": "object",
            "properties": {"template_path": {"type": "string"}},
            "required": ["template_path"],
            "additionalProperties": False,
        },
        exam_tools.tool_template_preview,
        risk=ToolRisk.READ,
        ui_label="正在预览模板结构…",
    ),
    _fn(
        "exam.validate_paper",
        "校验当前选题与试卷模板是否匹配（卷面结构、题目是否存在等），并写入临时校验用配置。"
        "默认不做试卷版式编译；将 include_latex_check 设为 true 时，会额外试跑与导出相同的版式编译以提前发现版式错误。"
        "返回中的 math_warnings 为题干内数学公式定界符等静态提示，不能替代完整导出。",
        {
            "type": "object",
            "properties": {
                "template_ref": {"type": "string"},
                "template_path": {"type": "string"},
                "include_latex_check": {
                    "type": "boolean",
                    "description": "为 true 时试跑版式编译（较慢，需本机已安装 latexmk）",
                },
                "include_math_static": {
                    "type": "boolean",
                    "description": "为 false 时跳过题干内数学公式定界符静态检查（默认 true）",
                },
                "selected_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section_id": {"type": "string"},
                            "question_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["section_id", "question_ids"],
                    },
                },
            },
            "required": ["template_ref", "template_path", "selected_items"],
            "additionalProperties": False,
        },
        exam_tools.tool_validate_paper,
        ui_label="正在校验组卷…",
    ),
    _fn(
        "exam.export_paper",
        "校验通过后导出学生版与教师版 PDF（高影响操作，需确认）。",
        {
            "type": "object",
            "properties": {
                "template_ref": {"type": "string"},
                "template_path": {"type": "string"},
                "selected_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section_id": {"type": "string"},
                            "question_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["section_id", "question_ids"],
                    },
                },
                "export_label": {"type": "string"},
                "subject": {"type": "string"},
                "metadata_title": {"type": "string"},
            },
            "required": ["template_ref", "template_path", "selected_items", "export_label", "subject"],
            "additionalProperties": False,
        },
        exam_tools.tool_export_paper,
        risk=ToolRisk.DESTRUCTIVE,
        ui_label="正在准备导出试卷…",
        vivace_fast_review=True,
    ),
    _fn(
        "bank.search_items",
        "在题库中按关键词或题型筛选题目，返回完整标识与内容摘要。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，可匹配题干摘要或标识；留空则仅按题型筛选"},
                "question_type": {
                    "type": "string",
                    "description": "题型：choice / fill / judge / short_answer / reasoning / essay；可留空",
                },
                "max_hits": {"type": "integer", "description": "最多返回条数，默认 30，最大 80"},
            },
            "additionalProperties": False,
        },
        bank_tools.tool_bank_search_items,
        risk=ToolRisk.READ,
        ui_label="正在检索题库…",
    ),
    _fn(
        "bank.get_item",
        "读取单道独立题目的完整内容与结构（题组请改用软件界面编辑）。",
        {
            "type": "object",
            "properties": {"qualified_id": {"type": "string", "description": "题目完整标识，如 科目/题集/题目编号"}},
            "required": ["qualified_id"],
            "additionalProperties": False,
        },
        bank_tools.tool_bank_get_item,
        risk=ToolRisk.READ,
        ui_label="正在打开题目详情…",
    ),
    _fn(
        "bank.update_item",
        "修改已有独立题目的题干、答案、解析或选项（写入操作，可能需确认）。",
        {
            "type": "object",
            "properties": {
                "qualified_id": {"type": "string"},
                "content": {"type": "string"},
                "answer": {"type": "string"},
                "analysis": {"type": "string"},
                "options": {"type": "string", "description": "选择题选项，JSON 对象字符串，如 {\"A\":\"...\",\"B\":\"...\"}"},
                "metadata": {"type": "string", "description": "附加说明字段的 JSON 字符串"},
            },
            "required": ["qualified_id"],
            "additionalProperties": False,
        },
        bank_tools.tool_bank_update_item,
        ui_label="正在保存题目修改…",
    ),
    _fn(
        "bank.create_item",
        "在指定题集中新建一道独立题目（须符合题型与选项规则）。",
        {
            "type": "object",
            "properties": {
                "collection_namespace": {
                    "type": "string",
                    "description": "题集路径，格式 科目/题集，如 math/unit1",
                },
                "question_id": {"type": "string"},
                "question_type": {"type": "string"},
                "content": {"type": "string"},
                "answer": {"type": "string"},
                "analysis": {"type": "string"},
                "options": {"type": "string", "description": "选择题必填，JSON 对象字符串"},
                "metadata": {"type": "string", "description": "JSON 对象字符串"},
            },
            "required": ["collection_namespace", "question_id", "question_type", "content", "answer"],
            "additionalProperties": False,
        },
        bank_tools.tool_bank_create_item,
        ui_label="正在新建题目…",
        allegro_auto_add=True,
    ),
    _fn(
        "graph.list_nodes",
        "列出知识图谱节点，可按类型筛选。",
        {
            "type": "object",
            "properties": {"node_kind": {"type": "string", "description": "concept / skill / causal，可留空"}},
            "additionalProperties": False,
        },
        graph_tools.tool_list_nodes,
        risk=ToolRisk.READ,
        ui_label="正在读取知识要点…",
    ),
    _fn(
        "graph.search_nodes",
        "按关键词在知识要点名称、别名与说明中检索，返回有限条结果（避免一次加载全量图谱）。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，可多个词（需同时匹配）"},
                "node_kind": {"type": "string", "description": "concept / skill / causal，可留空"},
                "max_hits": {"type": "integer", "description": "最多返回条数，默认 30，最大 200"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        graph_tools.tool_search_nodes,
        risk=ToolRisk.READ,
        ui_label="正在搜索知识要点…",
    ),
    _fn(
        "graph.create_node",
        "创建图谱节点；无 id 时需 parent_node_id 与 canonical_name 以自动生成标识。",
        {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "parent_node_id": {"type": "string"},
                "canonical_name": {"type": "string"},
                "node_kind": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}},
                "subject": {"type": "string"},
                "level": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["canonical_name"],
            "additionalProperties": False,
        },
        graph_tools.tool_create_node,
        ui_label="正在创建知识要点…",
        allegro_auto_add=True,
    ),
    _fn(
        "graph.batch_create_nodes",
        "批量创建知识要点节点；每项规则同 graph.create_node（可混用自动生成 id 与显式 id）。",
        {
            "type": "object",
            "properties": {
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "parent_node_id": {"type": "string"},
                            "canonical_name": {"type": "string"},
                            "node_kind": {"type": "string"},
                            "aliases": {"type": "array", "items": {"type": "string"}},
                            "subject": {"type": "string"},
                            "level": {"type": "string"},
                            "description": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["canonical_name"],
                    },
                }
            },
            "required": ["nodes"],
            "additionalProperties": False,
        },
        graph_tools.tool_batch_create_nodes,
        ui_label="正在批量创建知识要点…",
        allegro_auto_add=True,
    ),
    _fn(
        "graph.update_node",
        "更新已有节点字段。",
        {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "canonical_name": {"type": "string"},
                "node_kind": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}},
                "subject": {"type": "string"},
                "level": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["node_id"],
            "additionalProperties": False,
        },
        graph_tools.tool_update_node,
        ui_label="正在更新知识要点…",
    ),
    _fn(
        "graph.delete_node",
        "删除节点及其关联边与绑定（高影响，需确认）。",
        {
            "type": "object",
            "properties": {"node_id": {"type": "string"}},
            "required": ["node_id"],
            "additionalProperties": False,
        },
        graph_tools.tool_delete_node,
        risk=ToolRisk.DESTRUCTIVE,
        ui_label="正在删除知识要点…",
        vivace_fast_review=True,
    ),
    _fn(
        "graph.list_relations",
        "列出全部节点关系。",
        {"type": "object", "properties": {}, "additionalProperties": False},
        graph_tools.tool_list_relations,
        risk=ToolRisk.READ,
        ui_label="正在读取要点关联…",
    ),
    _fn(
        "graph.create_relation",
        "在两点之间创建关系（两点须已存在）。",
        {
            "type": "object",
            "properties": {
                "from_node_id": {"type": "string"},
                "to_node_id": {"type": "string"},
                "relation_type": {"type": "string"},
            },
            "required": ["from_node_id", "to_node_id", "relation_type"],
            "additionalProperties": False,
        },
        graph_tools.tool_create_relation,
        ui_label="正在建立要点关联…",
        allegro_auto_add=True,
    ),
    _fn(
        "graph.batch_create_relations",
        "批量创建要点之间的关联（多条边）。",
        {
            "type": "object",
            "properties": {
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from_node_id": {"type": "string"},
                            "to_node_id": {"type": "string"},
                            "relation_type": {"type": "string"},
                        },
                        "required": ["from_node_id", "to_node_id", "relation_type"],
                    },
                }
            },
            "required": ["relations"],
            "additionalProperties": False,
        },
        graph_tools.tool_batch_create_relations,
        ui_label="正在批量建立要点关联…",
        allegro_auto_add=True,
    ),
    _fn(
        "graph.delete_relation",
        "按关系标识删除一条关系。",
        {
            "type": "object",
            "properties": {"relation_id": {"type": "string"}},
            "required": ["relation_id"],
            "additionalProperties": False,
        },
        graph_tools.tool_delete_relation,
        risk=ToolRisk.DESTRUCTIVE,
        ui_label="正在删除要点关联…",
        vivace_fast_review=True,
    ),
    _fn(
        "graph.bind_question",
        "将题目与知识点节点绑定。",
        {
            "type": "object",
            "properties": {
                "question_qualified_id": {"type": "string"},
                "node_id": {"type": "string"},
            },
            "required": ["question_qualified_id", "node_id"],
            "additionalProperties": False,
        },
        graph_tools.tool_bind_question,
        ui_label="正在把题目挂到知识要点…",
    ),
    _fn(
        "graph.batch_bind_questions",
        "批量将多道题目挂到知识点（按节点分组一次写入，效率高于多次调用 graph.bind_question）。",
        {
            "type": "object",
            "properties": {
                "bindings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_qualified_id": {"type": "string"},
                            "node_id": {"type": "string"},
                        },
                        "required": ["question_qualified_id", "node_id"],
                    },
                }
            },
            "required": ["bindings"],
            "additionalProperties": False,
        },
        graph_tools.tool_batch_bind_questions,
        ui_label="正在批量挂接题目…",
    ),
    _fn(
        "graph.attach_resource",
        "为节点挂载 resource 目录下的资料文件（相对路径）。",
        {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "relative_path": {"type": "string"},
            },
            "required": ["node_id", "relative_path"],
            "additionalProperties": False,
        },
        graph_tools.tool_attach_resource,
        ui_label="正在挂载参考资料…",
        allegro_auto_add=True,
    ),
    _fn(
        "memory.read_index",
        "读取跨会话记忆索引（提示性质，引用前建议再读主题文件核对）。",
        {"type": "object", "properties": {}, "additionalProperties": False},
        memory_tools.tool_read_index,
        risk=ToolRisk.READ,
        ui_label="正在读取长期备忘索引…",
    ),
    _fn(
        "memory.read_topic",
        "读取指定主题记忆文件正文（文件名含 .md）。",
        {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
        memory_tools.tool_read_topic,
        risk=ToolRisk.READ,
        ui_label="正在打开备忘主题…",
    ),
    _fn(
        "memory.search",
        "在主题记忆文件中按关键词做简单检索。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_hits": {"type": "integer"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        memory_tools.tool_search,
        risk=ToolRisk.READ,
        ui_label="正在搜索备忘内容…",
    ),
    _fn(
        "agent.set_task_plan",
        "为本轮对话登记多步任务清单，便于跟进进度（仅当前会话有效）。",
        {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "status": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                }
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
        session_tools.tool_set_task_plan,
        risk=ToolRisk.READ,
        ui_label="正在整理任务步骤…",
    ),
    _fn(
        "agent.update_task_step",
        "更新任务清单中某一序号的完成状态（如 pending、doing、done）。",
        {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "从 0 开始的序号"},
                "status": {"type": "string"},
            },
            "required": ["index", "status"],
            "additionalProperties": False,
        },
        session_tools.tool_update_task_step,
        risk=ToolRisk.READ,
        ui_label="正在更新任务进度…",
    ),
    _fn(
        "web.search",
        "联网检索公开网页摘要（用于教学参考；需在环境中配置检索服务密钥）。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "description": "默认 5，最大 10"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        web_tools.tool_web_search,
        risk=ToolRisk.READ,
        ui_label="正在搜索公开资料…",
    ),
    _fn(
        "agent.run_tool_pipeline",
        "按顺序执行多步工具调用（用于减少往返；若某步需教师确认则会中止并提示分步执行）。",
        {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "arguments": {"type": "object"},
                        },
                        "required": ["tool"],
                    },
                }
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
        pipeline_tools.tool_run_tool_pipeline,
        ui_label="正在执行多步操作…",
    ),
    # --- Phase 1: Focus switching ---
    _fn(
        "agent.switch_focus",
        "切换当前聚焦域以获取不同领域的工具能力。可选域：general / bank / graph / analysis / compose / doc_process。",
        {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["general", "bank", "graph", "analysis", "compose", "doc_process"],
                    "description": "目标聚焦域",
                },
            },
            "required": ["domain"],
            "additionalProperties": False,
        },
        session_tools.tool_switch_focus,
        risk=ToolRisk.READ,
        ui_label="正在切换工作域…",
    ),
    # --- Phase 4: Plan Mode ---
    _fn(
        "agent.enter_plan_mode",
        "进入计划模式：只读探索当前状况并生成结构化执行计划，等待教师审批后再执行。适用于复杂任务。",
        {"type": "object", "properties": {}, "additionalProperties": False},
        session_tools.tool_enter_plan_mode,
        risk=ToolRisk.READ,
        ui_label="正在进入计划模式…",
    ),
    _fn(
        "agent.exit_plan_mode",
        "提交计划并退出计划模式，将计划呈现给教师审批。",
        {
            "type": "object",
            "properties": {
                "plan_file_path": {"type": "string", "description": "计划文件的项目内相对路径"},
            },
            "additionalProperties": False,
        },
        session_tools.tool_exit_plan_mode,
        risk=ToolRisk.READ,
        ui_label="正在提交计划…",
    ),
    # --- Phase 6: Skill Activation ---
    _fn(
        "agent.activate_skill",
        "激活一项技能以获取其详细工作流指引。请先阅读系统提示中的技能目录，匹配后再调用。",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "技能标识名"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        session_tools.tool_activate_skill,
        risk=ToolRisk.READ,
        ui_label="正在加载技能指引…",
    ),
    _fn(
        "agent.read_skill_reference",
        "读取技能包内参考文件（如 references/*.md）。path 为相对该技能根目录的路径，例如 references/geometry-2d.md。"
        "内置技能文件不在教师项目目录中，请勿用 file.read 拼仓库源码路径。",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "技能标识名（与 agent.activate_skill 一致）"},
                "path": {"type": "string", "description": "相对技能根目录的路径，如 references/overview.md"},
                "offset": {"type": "integer", "description": "起始行号（0-based），默认 0"},
                "limit": {"type": "integer", "description": "读取行数，默认全部"},
            },
            "required": ["name", "path"],
            "additionalProperties": False,
        },
        session_tools.tool_read_skill_reference,
        risk=ToolRisk.READ,
        ui_label="正在读取技能参考…",
    ),
    # --- Phase 2: File tools ---
    _fn(
        "file.read",
        "读取项目内文本文件。支持 offset/limit 按行范围读取大文件。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "项目内相对路径"},
                "offset": {"type": "integer", "description": "起始行号（0-based），默认 0"},
                "limit": {"type": "integer", "description": "读取行数，默认读取全部"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        file_tools.tool_file_read,
        risk=ToolRisk.READ,
        ui_label="正在读取文件…",
    ),
    _fn(
        "file.write",
        "创建新文件或整体覆写文件内容（写入操作）。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "项目内相对路径"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        file_tools.tool_file_write,
        ui_label="正在写入文件…",
    ),
    _fn(
        "file.edit",
        "精确字符串替换编辑：old_string 须在文件中唯一匹配后替换为 new_string。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "项目内相对路径"},
                "old_string": {"type": "string", "description": "要替换的原文（须在文件中唯一）"},
                "new_string": {"type": "string", "description": "替换后的内容"},
                "replace_all": {"type": "boolean", "description": "是否替换所有匹配项，默认 false"},
            },
            "required": ["path", "old_string", "new_string"],
            "additionalProperties": False,
        },
        file_tools.tool_file_edit,
        ui_label="正在编辑文件…",
    ),
    _fn(
        "file.list",
        "列出目录内容，支持 glob 模式筛选。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "项目内相对路径，默认根目录"},
                "pattern": {"type": "string", "description": "文件名匹配模式（如 *.yaml），默认 *"},
            },
            "additionalProperties": False,
        },
        file_tools.tool_file_list,
        risk=ToolRisk.READ,
        ui_label="正在列出文件…",
    ),
    _fn(
        "file.search",
        "在文件内容中搜索正则模式，返回匹配行。",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则表达式"},
                "path": {"type": "string", "description": "搜索起始路径（文件或目录），默认项目根目录"},
                "ignore_case": {"type": "boolean", "description": "是否忽略大小写"},
                "max_matches": {"type": "integer", "description": "最大匹配数，默认 50"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        file_tools.tool_file_search,
        risk=ToolRisk.READ,
        ui_label="正在搜索文件内容…",
    ),
    # --- Phase 2: Document conversion tools ---
    _fn(
        "doc.convert_to_markdown",
        "将 Word/DOCX 文件转换为 Markdown 格式（需要系统安装 pandoc）。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "DOCX 文件的项目内相对路径"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        doc_tools.tool_doc_convert_to_markdown,
        risk=ToolRisk.READ,
        ui_label="正在转换文档…",
    ),
    _fn(
        "doc.extract_pdf_text",
        "从 PDF 文件中提取文字内容。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "PDF 文件的项目内相对路径"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        doc_tools.tool_doc_extract_pdf_text,
        risk=ToolRisk.READ,
        ui_label="正在提取 PDF 文本…",
    ),
    _fn(
        "doc.ocr_image",
        "对图片进行 OCR 文字识别。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图片文件的项目内相对路径"},
                "lang": {"type": "string", "description": "OCR 语言，默认 chi_sim+eng"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        doc_tools.tool_doc_ocr_image,
        risk=ToolRisk.READ,
        ui_label="正在识别图片文字…",
    ),
]

# 人工确认弹窗用语（与 ui_label「进行中」区分）
_CONFIRM_LABELS: dict[str, str] = {
    "exam.export_paper": "导出试卷文件",
    "exam.validate_paper": "校验选题与卷面结构并写入临时配置",
    "graph.delete_node": "删除知识要点及其关联",
    "graph.delete_relation": "删除要点之间的关联",
    "graph.create_node": "新建知识要点",
    "graph.update_node": "修改知识要点",
    "graph.create_relation": "新建要点关联",
    "graph.batch_create_nodes": "批量新建知识要点",
    "graph.batch_create_relations": "批量新建要点关联",
    "graph.batch_bind_questions": "批量将题目挂接到知识要点",
    "graph.bind_question": "将题目挂接到知识要点",
    "graph.attach_resource": "为要点挂载资料",
    "bank.update_item": "修改题库中的题目内容",
    "bank.create_item": "在题集中新建题目",
    "analysis.save_script": "保存分析脚本",
    "analysis.run_script": "运行分析脚本",
    "analysis.run_builtin": "运行内置学情分析",
    "agent.run_subtask": "分步深入分析子任务",
    "agent.run_tool_pipeline": "按序执行多步工具",
    "file.write": "写入项目文件",
    "file.edit": "编辑项目文件",
}


def _apply_confirm_labels(tools: list[RegisteredTool]) -> list[RegisteredTool]:
    return [replace(t, action_label=t.action_label or _CONFIRM_LABELS.get(t.name)) for t in tools]


TOOLS = _apply_confirm_labels(_RAW_TOOLS)

_TOOL_BY_NAME: dict[str, RegisteredTool] = {t.name: t for t in TOOLS}


def get_registered_tool(tool_name: str) -> RegisteredTool | None:
    if tool_name == SUBTASK_TOOL_NAME:
        return subtask_tool_schema()
    return _TOOL_BY_NAME.get(tool_name)


def tool_name_matches_patterns(name: str, patterns: Iterable[str]) -> bool:
    for pat in patterns:
        if pat.endswith("*"):
            base = pat[:-1]
            if base and name.startswith(base):
                return True
        elif name == pat:
            return True
    return False


# 通用工具：所有聚焦态下始终可见
_ALWAYS_VISIBLE: tuple[str, ...] = (
    "memory.*",
    "agent.*",
    "web.*",
    "file.read",
    "file.list",
    "file.search",
)

# 聚焦态工具预设（替代旧 PAGE_TOOL_PRESETS）
FOCUS_PRESETS: dict[str, tuple[str, ...]] = {
    "general": (
        *_ALWAYS_VISIBLE,
        "analysis.list_datasets",
        "analysis.list_builtins",
        "analysis.run_builtin",
        "analysis.get_job",
        "exam.list_templates",
        "graph.list_nodes",
        "graph.search_nodes",
        "bank.search_items",
        "bank.get_item",
    ),
    "analysis": (*_ALWAYS_VISIBLE, "analysis.*"),
    "bank": (
        *_ALWAYS_VISIBLE,
        "bank.*",
        "graph.bind_question",
        "graph.batch_bind_questions",
        "graph.list_nodes",
        "graph.search_nodes",
    ),
    "graph": (*_ALWAYS_VISIBLE, "graph.*", "bank.*"),
    "compose": (
        *_ALWAYS_VISIBLE,
        "exam.*",
        "bank.*",
        "graph.list_nodes",
        "graph.list_relations",
        "graph.search_nodes",
        "file.write",
        "file.edit",
    ),
    "doc_process": (
        *_ALWAYS_VISIBLE,
        "file.*",
        "doc.*",
    ),
}

# 旧页面名到聚焦态的映射（向后兼容前端 page_context）
_PAGE_TO_FOCUS: dict[str, str] = {
    "analysis": "analysis",
    "bank": "bank",
    "graph": "graph",
    "compose": "compose",
    "template": "compose",
    "help": "general",
    "log": "general",
    "settings": "general",
}


def select_tools_for_turn(
    *,
    current_page: str | None,
    skill_id: str | None,
    include_subtask: bool,
    current_focus: str | None = None,
    project_root: Any = None,
    plan_mode_active: bool = False,
) -> list[RegisteredTool]:
    from solaire.agent_layer import skills as skills_mod

    patterns: tuple[str, ...] | None = None
    if skill_id:
        sk = skills_mod.get_skill(skill_id.strip(), project_root)
        if sk:
            patterns = sk.tool_patterns
    if patterns is None:
        focus = (current_focus or "").strip()
        if not focus:
            page_key = (current_page or "").strip()
            focus = _PAGE_TO_FOCUS.get(page_key, "general")
        patterns = FOCUS_PRESETS.get(focus) or FOCUS_PRESETS["general"]

    picked: list[RegisteredTool] = []
    seen: set[str] = set()
    for t in TOOLS:
        if not tool_name_matches_patterns(t.name, patterns):
            continue
        if t.name in seen:
            continue
        seen.add(t.name)
        picked.append(t)
    if include_subtask:
        st = subtask_tool_schema()
        if tool_name_matches_patterns(st.name, patterns) and st.name not in seen:
            picked.append(st)
    # 计划模式：无论当前聚焦域是否含 file.*，均暴露写入/编辑以便落盘计划文件（路径在 file_tools 中限制在 plans 目录）
    if plan_mode_active:
        for _plan_tool in ("file.write", "file.edit"):
            if _plan_tool not in seen:
                pt = _TOOL_BY_NAME.get(_plan_tool)
                if pt:
                    picked.append(pt)
                    seen.add(_plan_tool)
    return picked


SUBTASK_TOOL_NAME = "agent.run_subtask"


def subtask_tool_schema() -> RegisteredTool:
    return RegisteredTool(
        name=SUBTASK_TOOL_NAME,
        description=(
            "启动子任务深度分析：在隔离上下文中多步调用工具，仅将精简结论返回主对话。"
            "用于复杂诊断、脚本调试或综合报告素材收集。"
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "description": "子任务目标与成功标准"},
                "allowed_tool_prefixes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "允许的工具名前缀，如 analysis.、memory.；留空表示不额外限制",
                },
            },
            "required": ["objective"],
            "additionalProperties": False,
        },
        handler=lambda ctx, args: ToolResult(status="failed", error_message="handled in orchestrator"),
        risk=ToolRisk.WRITE,
        ui_label="正在分步深入分析…",
        action_label=_CONFIRM_LABELS.get(SUBTASK_TOOL_NAME),
    )


def all_registered_tools(include_subtask: bool = True) -> list[RegisteredTool]:
    if include_subtask:
        return [*TOOLS, subtask_tool_schema()]
    return list(TOOLS)


def openai_tools_payload(tools: list[RegisteredTool] | None = None) -> list[dict[str, Any]]:
    tlist = tools or all_registered_tools()
    out: list[dict[str, Any]] = []
    for t in tlist:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters_schema,
                },
            }
        )
    return out


def tool_descriptions_for_prompt(tools: list[RegisteredTool] | None = None) -> str:
    tlist = tools or all_registered_tools()
    lines = []
    for t in tlist:
        lines.append(f"- `{t.name}`: {t.description}")
    return "\n".join(lines)


def invoke_registered_tool(name: str, args: dict[str, Any], ctx: InvocationContext) -> ToolResult:
    if name == SUBTASK_TOOL_NAME:
        return ToolResult(status="failed", error_code="internal", error_message="subtask not invokable here")
    rt = _TOOL_BY_NAME.get(name)
    if rt is None:
        return ToolResult(status="failed", error_code="unknown_tool", error_message=f"未知工具: {name}")
    return rt.handler(ctx, args)
