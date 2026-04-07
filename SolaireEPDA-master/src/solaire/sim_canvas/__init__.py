"""SimCanvas — 物理场可视化的简单仿真引擎。

状态：规划中（尚未实现）。

定位：
    可视化物理场分布（电场、磁场、引力场）的示意图。
    不要求精确仿真——目标是生成直观的教学示意图（定性正确，视觉清晰），
    而非数值仿真软件。

接口契约（未来稳定接口，先行定义以指导设计）：

    render_field(config: FieldConfig) -> str
        根据配置生成物理场分布的 SVG 示意图。

    FieldConfig：
        type: "electric" | "magnetic" | "gravity"
        sources: list[FieldSource]  # 场源（电荷、磁极、质量）
        canvas: CanvasConfig
        display: DisplayConfig      # 场线密度、颜色等

与 PrimeBrush 的关系：
    SimCanvas 生成的 SVG 可嵌入 ExamCompiler 流水线（与 PrimeBrush 相同的代码块展开机制）。
    两者共享相同的 ``canvas`` 和 SVG 工具层（未来从 solaire/common/ 抽取）。

Rust 迁移说明：
    物理场计算（数值积分、向量场插值）是 Rust-candidate。
    建议以 Rust 实现核心计算，编译为 WASM 在浏览器端运行，
    Python 侧保留调用适配器。

启动条件：
    1. 确定目标场类型的优先级（建议：电场/磁场最先，覆盖高考最高频场景）
    2. 确定精度要求（定性示意 vs. 精确数值——强烈建议定性，降低实现复杂度）
    3. PrimeBrush 的 canvas 工具稳定后共享基础设施
    4. 在 exam_compiler 的代码块展开机制中注册 ``sim_canvas`` 围栏语法

不要在此模块之外导入任何内容，直到上述启动条件满足后开始实现。
"""

__status__ = "planned"
__version__ = "0.0.0"


def render_field(config: dict) -> str:
    """Placeholder — not yet implemented."""
    raise NotImplementedError(
        "SimCanvas is not yet implemented. "
        "See solaire/sim_canvas/__init__.py for planned interface and launch conditions."
    )
