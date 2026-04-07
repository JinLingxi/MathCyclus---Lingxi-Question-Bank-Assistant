"""ProofVerifier — 数学推理与物理计算的形式化验证器。

状态：规划中（尚未实现）。

定位：
    对基础数学推理步骤（代数化简、几何证明）和物理计算（量纲分析、数值校验）
    进行形式化验证，辅助教师检查题目解析的正确性，辅助 Agent 对生成的证明链进行自检。

接口契约（未来稳定接口，先行定义以指导设计）：

    verify_algebraic_steps(steps: list[str]) -> VerificationResult
        检验代数化简步骤链的每一步是否可推导自前一步。

    verify_geometry_proof(proof_text: str) -> VerificationResult
        对基础欧几里得几何证明进行命题推导校验。

    verify_physics_calculation(expr: str, *, units: dict) -> VerificationResult
        量纲分析与数值范围校验。

Rust 迁移说明：
    此模块是 Rust-candidate——形式化符号计算是 Rust 类型系统和性能优势的最佳适用场景。
    建议直接以 Rust 实现，通过子进程（stdio JSON 协议）或 WASM 调用。
    Python 端只保留调用适配器（同 primebrush 模式）。

启动条件：
    1. 确定形式化验证的语义范围（仅检验步骤一致性，还是完整形式证明）
    2. 选型：自研符号引擎 vs. 调用已有工具（如 Lean 4, sympy, z3）
    3. 完成 ExamCompiler 题目解析字段的标准化（proof_steps 字段格式）

不要在此模块之外导入任何内容，直到上述启动条件满足后开始实现。
"""

__status__ = "planned"
__version__ = "0.0.0"

# 此模块当前无可用接口；导入此包不会抛错，但调用任何函数会抛 NotImplementedError。


def verify_algebraic_steps(steps: list[str]) -> dict:
    """Placeholder — not yet implemented."""
    raise NotImplementedError(
        "ProofVerifier is not yet implemented. "
        "See solaire/proof_verifier/__init__.py for planned interface and launch conditions."
    )


def verify_geometry_proof(proof_text: str) -> dict:
    """Placeholder — not yet implemented."""
    raise NotImplementedError(
        "ProofVerifier is not yet implemented. "
        "See solaire/proof_verifier/__init__.py for planned interface and launch conditions."
    )


def verify_physics_calculation(expr: str, *, units: dict) -> dict:
    """Placeholder — not yet implemented."""
    raise NotImplementedError(
        "ProofVerifier is not yet implemented. "
        "See solaire/proof_verifier/__init__.py for planned interface and launch conditions."
    )
