"""Conservative structural comparison of common school-math expressions.

This is a syntax comparator, never an algebraic-equivalence prover. Unsupported
or malformed TeX is reported to callers for a token-based fallback.
"""
from collections import Counter
from functools import lru_cache
import hashlib
import re
import unicodedata


_MATH = re.compile(r"(?<!\\)\$\$(.*?)(?<!\\)\$\$|(?<!\\)\$(.*?)(?<!\\)\$|\\\((.*?)\\\)|\\\[(.*?)\\\]", re.S)
_TOKEN = re.compile(r"\\[A-Za-z]+|\\.|<=|>=|!=|[0-9]+(?:\.[0-9]+)?|[A-Za-z]|[^\s]")
_FUNCTIONS = {"sin", "cos", "tan", "cot", "sec", "csc", "ln", "log", "lg", "exp"}
_WRAPPERS = {"mathbb", "mathrm", "mathbf", "mathcal", "vec", "overrightarrow", "overline", "widehat"}
_ALIASES = {"dfrac": "frac", "tfrac": "frac", "cdot": "*", "times": "*", "div": "/",
            "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
            "infty": "∞", "pi": "π", "alpha": "α", "beta": "β", "theta": "θ",
            "lambda": "λ", "mu": "μ", "phi": "φ", "varphi": "ϕ", "omega": "ω",
            "cup": "∪", "cap": "∩", "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆",
            "circ": "°"}
_RELATIONS = {"=", "<", ">", "≤", "≥", "≠", "∈", "∉", "⊂", "⊆"}
_SET_OPS = {"∪", "∩"}
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
_GREEK = set("αβθλμφϕω")


class UnsupportedFormula(ValueError):
    pass


def _tokens(text):
    text = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+",
                  lambda match: "^{" + match[0].translate(_SUPERSCRIPT) + "}", text)
    text = unicodedata.normalize("NFKC", text).replace("−", "-").replace("×", "*").replace("÷", "/")
    text = re.sub(r"\\(?:left|right|displaystyle|textstyle)(?![A-Za-z])", "", text)
    text = re.sub(r"\\[,;:! ]", "", text)
    tokens = []
    for token in _TOKEN.findall(text):
        if token.startswith("\\"):
            command = token[1:]
            token = _ALIASES.get(command, command if command in _FUNCTIONS | _WRAPPERS | {"frac", "sqrt"} else token)
        tokens.append(token)
    tokens = [{"<=": "≤", ">=": "≥", "!=": "≠"}.get(token, token) for token in tokens]
    if len(tokens) > 512:
        raise UnsupportedFormula("expression_too_large")
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens, self.position, self.depth = tokens, 0, 0

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else ""

    def take(self):
        value = self.peek()
        if not value:
            raise UnsupportedFormula("unexpected_end")
        self.position += 1
        return value

    def atom(self):
        self.depth += 1
        if self.depth > 48:
            raise UnsupportedFormula("nesting_too_deep")
        try:
            token = self.take()
            if token in {"{", "(", "["}:
                node = self.expression()
                if self.peek() == "," and token != "{":
                    parts = [node]
                    while self.peek() == ",":
                        self.take()
                        parts.append(self.expression())
                    end = self.take()
                    if end not in {")", "]"}:
                        raise UnsupportedFormula("unbalanced_interval")
                    return ("interval_or_tuple", token, end, *parts)
                if self.take() != ("}" if token == "{" else ")" if token == "(" else "]"):
                    raise UnsupportedFormula("unbalanced_group")
                return ("group" if token == "(" else "bracket", node) if token != "{" else node
            if token in {"+", "-"}:
                return ("neg", self.expression(25)) if token == "-" else self.expression(25)
            if token == "frac":
                return ("div", self.atom(), self.atom())
            if token == "sqrt":
                if self.peek() == "[":
                    raise UnsupportedFormula("indexed_root")
                return ("sqrt", self.atom())
            if token in _FUNCTIONS:
                if self.peek() in {"^", "_"}:
                    modifier = self.take()
                    argument = self.atom()
                    value = ("function", token, self.expression(25))
                    return ("pow", value, argument) if modifier == "^" else ("function_base", token, argument, value[2])
                return ("function", token, self.expression(25))
            if token in _WRAPPERS:
                return ("annotation", token, self.atom())
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", token):
                return ("number", token)
            if re.fullmatch(r"[A-Za-z]", token) or token in _GREEK:
                return ("variable", token)
            if token in {"π", "∞", "°"}:
                return ("constant", token)
            raise UnsupportedFormula("unsupported_token")
        finally:
            self.depth -= 1

    def expression(self, minimum=0):
        left = self.atom()
        while self.peek() and self.peek() not in {"}", ")", "]", ","}:
            token = self.peek()
            power = 3 if token in _RELATIONS else (8 if token in _SET_OPS else (
                10 if token in {"+", "-"} else 20 if token in {"*", "/"} else 30 if token in {"^", "_"} else 20))
            if power < minimum:
                break
            if token in _RELATIONS | _SET_OPS | {"+", "-", "*", "/", "^", "_"}:
                self.take()
                operation = {"/": "div", "*": "mul", "^": "pow", "_": "subscript"}.get(token, token)
                if token in {"^", "_"}:
                    # A TeX script consumes one atom or a braced expression.
                    # x_i^2 is (x_i)^2, not x_(i^2).
                    if left[0] == operation or self.peek() in {"+", "-"}:
                        raise UnsupportedFormula("ambiguous_script")
                    right = self.atom()
                else:
                    right = self.expression(power + 1)
            else:
                right = self.expression(21)
                operation = "juxtapose"
            left = (operation, left, right)
        return left


@lru_cache(maxsize=4096)
def _parse(text):
    try:
        parser = _Parser(_tokens(text))
        node = parser.expression()
        if parser.position != len(parser.tokens):
            raise UnsupportedFormula("remaining_tokens")
        return node
    except (UnsupportedFormula, RecursionError):
        return None


@lru_cache(maxsize=4096)
def _expressions(text):
    text = re.sub(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", "", text, flags=re.S)
    text = re.sub(r"\\(?:includegraphics|questionasset)\s*(?:\[[^\]]*\])?\{[^}]*\}", "", text)
    matches = list(_MATH.finditer(text))
    if matches:
        expressions = [next(part for part in match.groups() if part is not None) for match in matches[:64]]
        truncated = len(matches) > 64
    else:
        runs = re.findall(r"[A-Za-z0-9\\{}()[\]^_+\-*/=<>≤≥≠π∞αβθλμφϕω. ]+", text)
        expressions = [run.strip() for run in runs if re.search(r"[=+\-*/^<>≤≥≠]|\\(?:frac|sqrt)", run)][:64]
        truncated = False
    nodes = [_parse(expression) if len(expression) <= 4096 else None for expression in expressions]
    return tuple(nodes), truncated


def _shape(node, variables=None, preserve_number=False):
    variables = {} if variables is None else variables
    operation = node[0]
    if operation == "variable":
        return ("variable", variables.setdefault(node[1], len(variables)))
    if operation == "number":
        return node if preserve_number else ("number", "N")
    return tuple([operation] + [
        _shape(child, variables, preserve_number or (operation in {"pow", "subscript"} and index == 2))
        if isinstance(child, tuple) else child for index, child in enumerate(node[1:], 1)])


def _shape_nodes(nodes):
    variables = {}
    return tuple(_shape(node, variables) for node in nodes)


def formula_structure_key(text):
    """Candidate generation only; a shared key does not prove equivalence."""
    nodes, truncated = _expressions(str(text or ""))
    if not nodes or truncated or None in nodes:
        return None
    return hashlib.sha256(repr(_shape_nodes(nodes)).encode("utf-8")).hexdigest()


@lru_cache(maxsize=1024)
def _features(nodes):
    features = Counter()
    def walk(node, path):
        features[(path[-5:], node[0])] += 1
        if node[0] in {"number", "variable", "constant"}:
            features[(path[-5:], node)] += 1
        for index, child in enumerate(node[1:], 1):
            if isinstance(child, tuple):
                walk(child, (*path, (node[0], index)))
            else:
                features[(path[-5:], node[0], index, child)] += 1
    for node in nodes:
        walk(node, ())
    return features


def _jaccard(left, right):
    union = sum((left | right).values())
    return sum((left & right).values()) / union if union else None


def _critical(nodes, operation):
    result = Counter()
    def walk(node):
        if node[0] == operation:
            result[node[2] if operation in {"pow", "div", "subscript"} else node] += 1
        for child in node[1:]:
            if isinstance(child, tuple):
                walk(child)
    for node in nodes:
        walk(node)
    return result


def _operators(nodes, operations):
    result = Counter()
    def walk(node):
        if node[0] in operations:
            result[node[0]] += 1
        for child in node[1:]:
            if isinstance(child, tuple):
                walk(child)
    for node in nodes:
        walk(node)
    return result


def compare_formula_texts(left, right):
    """Return syntax evidence, never a proof of mathematical equivalence."""
    left_nodes, left_truncated = _expressions(str(left or ""))
    right_nodes, right_truncated = _expressions(str(right or ""))
    complete = bool(left_nodes and right_nodes) and not (
        left_truncated or right_truncated or None in left_nodes or None in right_nodes)
    result = {"complete": complete, "method": "syntax_tree" if complete else "token_fallback",
              "left_count": len(left_nodes), "right_count": len(right_nodes),
              "left_parsed": sum(node is not None for node in left_nodes),
              "right_parsed": sum(node is not None for node in right_nodes),
              "exact": False, "literal_score": None, "structure_score": None, "differences": []}
    if not complete:
        return result
    literal = _jaccard(_features(left_nodes), _features(right_nodes))
    structure = _jaccard(_features(_shape_nodes(left_nodes)),
                         _features(_shape_nodes(right_nodes)))
    result.update(exact=Counter(left_nodes) == Counter(right_nodes),
                  literal_score=literal, structure_score=structure,
                  recommendation_score=0.3 * literal + 0.7 * structure,
                  verification_score=0.75 * literal + 0.25 * structure)
    for operation, label in (("pow", "指数表达式不同"), ("div", "分母表达式不同"),
                             ("subscript", "下标表达式不同")):
        if _critical(left_nodes, operation) != _critical(right_nodes, operation):
            result["differences"].append(label)
    if _critical(left_nodes, "interval_or_tuple") != _critical(right_nodes, "interval_or_tuple"):
        result["differences"].append("区间或有序组的端点、边界不同")
    if _operators(left_nodes, _RELATIONS) != _operators(right_nodes, _RELATIONS):
        result["differences"].append("公式关系符号不同")
    if _operators(left_nodes, _SET_OPS) != _operators(right_nodes, _SET_OPS):
        result["differences"].append("集合运算符不同")
    return result
