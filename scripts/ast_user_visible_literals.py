"""AST 扫描：在排除 docstring / 常见日志 / ``re`` 模式参数后，收集「可能展示给用户」的字符串字面量。

供 ``check_no_bare_cjk_strings.py`` 与 ``scan_user_visible_string_candidates.py`` 复用。
"""

from __future__ import annotations

import ast
import re
import tokenize
from io import StringIO
from pathlib import Path
from typing import Sequence

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002a6df]")

LOG_ATTRS = frozenset(
    {"debug", "info", "warning", "warn", "error", "critical", "exception", "log", "fatal"}
)

RE_MODULE_FUNCS = frozenset(
    {
        "compile",
        "search",
        "match",
        "fullmatch",
        "findall",
        "finditer",
        "split",
        "sub",
    }
)


def contains_cjk(s: str) -> bool:
    return bool(CJK_RE.search(s))


def pragma_allow_cjk_lines(source: str) -> set[int]:
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(StringIO(source).readline):
            if tok.type != tokenize.COMMENT:
                continue
            if "adami:allow-cjk" in tok.string:
                lines.add(tok.start[0])
    except tokenize.TokenError:
        pass
    return lines


def docstring_line_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []

    def add_docstring(body: list[ast.stmt]) -> None:
        if not body:
            return
        first = body[0]
        if not isinstance(first, ast.Expr):
            return
        v = first.value
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            lo = int(first.lineno)
            hi = int(getattr(first, "end_lineno", None) or lo)
            ranges.append((lo, hi))

    if isinstance(tree, ast.Module):
        add_docstring(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            add_docstring(node.body)
    return ranges


def in_ranges(lineno: int, ranges: Sequence[tuple[int, int]]) -> bool:
    for lo, hi in ranges:
        if lo <= lineno <= hi:
            return True
    return False


def re_pattern_expr(node: ast.Call) -> ast.expr | None:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if not isinstance(func.value, ast.Name) or func.value.id != "re":
        return None
    if func.attr not in RE_MODULE_FUNCS:
        return None
    if node.args:
        return node.args[0]
    for kw in node.keywords:
        if kw.arg == "pattern":
            return kw.value
    return None


def is_logging_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in LOG_ATTRS:
        return False
    cur: ast.expr = func.value
    if isinstance(cur, ast.Name) and cur.id in ("logging", "logger", "log"):
        return True
    while isinstance(cur, ast.Attribute):
        if cur.attr in ("logger", "getLogger"):
            return True
        cur = cur.value
    if isinstance(cur, ast.Name) and cur.id in ("logging", "logger", "log"):
        return True
    return False


class _LiteralVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        doc_ranges: Sequence[tuple[int, int]],
        pragma_lines: set[int],
        hits: list[tuple[int, int, str]],
        cjk_only: bool,
        min_len: int = 1,
    ) -> None:
        self._doc_ranges = doc_ranges
        self._pragma_lines = pragma_lines
        self._hits = hits
        self._cjk_only = cjk_only
        self._min_len = min_len
        self._log_call_depth = 0
        self._re_pattern_depth = 0

    def visit_Call(self, node: ast.Call) -> None:
        pat = re_pattern_expr(node)
        if is_logging_call(node):
            self._log_call_depth += 1
        if pat is not None:
            self._re_pattern_depth += 1
            self.visit(pat)
            self._re_pattern_depth -= 1
        for arg in node.args:
            if pat is not None and arg is pat:
                continue
            self.visit(arg)
        for kw in node.keywords:
            if pat is not None and kw.value is pat:
                continue
            self.visit(kw.value)
        if is_logging_call(node):
            self._log_call_depth -= 1
        return None

    def _want(self, s: str) -> bool:
        if len(s) < self._min_len:
            return False
        if self._cjk_only:
            return contains_cjk(s)
        return True

    def visit_Constant(self, node: ast.Constant) -> None:
        if self._log_call_depth > 0 or self._re_pattern_depth > 0:
            return
        if not isinstance(node.value, str):
            return
        s = node.value
        if not self._want(s):
            return
        lineno = int(node.lineno)
        if in_ranges(lineno, self._doc_ranges):
            return
        if lineno in self._pragma_lines:
            return
        col = int(node.col_offset or 0)
        snippet = s if len(s) <= 120 else s[:117] + "..."
        self._hits.append((lineno, col, snippet))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        if self._log_call_depth > 0 or self._re_pattern_depth > 0:
            self.generic_visit(node)
            return
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                s = part.value
                if not self._want(s):
                    continue
                lineno = int(part.lineno)
                if in_ranges(lineno, self._doc_ranges):
                    continue
                if lineno in self._pragma_lines:
                    continue
                col = int(part.col_offset or 0)
                snippet = s if len(s) <= 120 else s[:117] + "..."
                self._hits.append((lineno, col, snippet))
            elif isinstance(part, ast.FormattedValue):
                self.visit(part.value)
        return None


def collect_literal_hits(
    path: Path,
    source: str,
    *,
    cjk_only: bool = True,
    min_len: int = 1,
) -> list[tuple[int, int, str]]:
    tree = ast.parse(source, filename=str(path))
    doc_ranges = docstring_line_ranges(tree)
    pragma_lines = pragma_allow_cjk_lines(source)
    hits: list[tuple[int, int, str]] = []
    _LiteralVisitor(
        doc_ranges=doc_ranges,
        pragma_lines=pragma_lines,
        hits=hits,
        cjk_only=cjk_only,
        min_len=min_len,
    ).visit(tree)
    hits.sort(key=lambda x: (x[0], x[1]))
    return hits
