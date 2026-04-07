from __future__ import annotations

import ast
import math
import operator as op

import numpy as np

_ALLOWED_NAMES = {
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "exp": np.exp,
    "sqrt": np.sqrt,
    "log": np.log,
    "abs": np.abs,
    "pi": np.pi,
    "e": np.e,
}

def _eval_node(node: ast.AST, x: np.ndarray) -> np.ndarray:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return np.full_like(x, float(node.value), dtype=np.float64)
        raise ValueError("only numeric constants allowed")
    if isinstance(node, ast.Name):
        if node.id == "x":
            return x
        if node.id in _ALLOWED_NAMES:
            v = _ALLOWED_NAMES[node.id]
            return np.full_like(x, float(v), dtype=np.float64)
        raise ValueError(f"unknown name: {node.id}")
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, x)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, x)
        right = _eval_node(node.right, x)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return np.power(left, right)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only simple calls allowed")
        fn = _ALLOWED_NAMES.get(node.func.id)
        if fn is None or not callable(fn):
            raise ValueError(f"call not allowed: {getattr(node.func, 'id', '?')}")
        if len(node.args) != 1:
            raise ValueError("only single-arg calls")
        arg = _eval_node(node.args[0], x)
        return fn(arg)
    raise ValueError(f"unsupported expression node: {type(node).__name__}")


def _normalize_expr(expr: str) -> str:
    """Allow `^` for exponentiation (common in school math)."""
    return expr.strip().replace("^", "**")


def eval_expr(expr: str, x: np.ndarray) -> np.ndarray:
    """Evaluate expression in variable x (numpy array), safe subset."""
    tree = ast.parse(_normalize_expr(expr), mode="eval")
    if not isinstance(tree, ast.Expression):
        raise ValueError("expected expression")
    return _eval_node(tree.body, x)


def eval_expr_scalar(expr: str, x0: float) -> float:
    y = eval_expr(expr, np.array([x0], dtype=np.float64))
    return float(y[0])
