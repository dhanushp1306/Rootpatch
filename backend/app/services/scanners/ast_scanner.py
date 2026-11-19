"""Python AST static analysis scanner.

Inspects parsed AST nodes in memory without executing uploaded code.
Because Python is dynamically typed and supports runtime name binding,
scope checks are conservative to minimize false positives.
"""

import ast
import builtins
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.schemas.scan import FindingRecord, ScannerToolSummary, SkippedScanFile
from app.utils.file_utils import is_within_directory

_BUILTIN_NAMES = frozenset(dir(builtins)) | {
    "__name__",
    "__file__",
    "__doc__",
    "__package__",
    "__spec__",
    "__builtins__",
    "__annotations__",
}

_SENSITIVE_VAR_NAMES = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "secret_key",
        "api_key",
        "apikey",
        "token",
        "auth_token",
        "access_token",
        "private_key",
        "client_secret",
    }
)
_PLACEHOLDER_SECRETS = frozenset(
    {"", "changeme", "placeholder", "example", "test", "dummy", "none", "null", "xxx"}
)

_SUBPROCESS_CALLS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
_PICKLE_FUNCS = frozenset({"load", "loads"})

AST_LIMITATIONS = [
    "Python AST analysis is intra-file only and does not resolve cross-module runtime bindings.",
    "Undefined-name checks conservatively skip scopes using wildcard imports or dynamic exec/globals.",
    "Uploaded Python source files are parsed in memory and never executed.",
]


@dataclass
class _ImportBinding:
    bound_name: str
    full_name: str
    line: int
    col: int


@dataclass
class AstScanOutcome:
    findings: List[FindingRecord] = field(default_factory=list)
    summary: ScannerToolSummary = field(
        default_factory=lambda: ScannerToolSummary(status="completed")
    )
    skipped_files: List[SkippedScanFile] = field(default_factory=list)
    files_scanned: int = 0


def _finding_id(rule_id: str, file_path: str, line: int, col: Optional[int], extra: str = "") -> str:
    digest = hashlib.sha1(
        f"ast:{rule_id}:{file_path}:{line}:{col or 0}:{extra}".encode("utf-8")
    ).hexdigest()[:12]
    return f"fnd-{digest}"


def _get_line(lines: Sequence[str], line_number: int) -> str:
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1].strip()
    return ""


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return ""


def _is_true_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_type_checking_guard(test: ast.AST) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return False


def _has_abstract_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and "abstract" in dec.id.lower():
            return True
        if isinstance(dec, ast.Attribute) and "abstract" in dec.attr.lower():
            return True
    return False


def _is_pass_only(body: Sequence[ast.stmt]) -> bool:
    if not body:
        return False
    meaningful = [
        stmt
        for stmt in body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    return len(meaningful) == 1 and isinstance(meaningful[0], ast.Pass)


def _extract_target_names(target: ast.AST) -> Set[str]:
    names: Set[str] = set()
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            names.update(_extract_target_names(elt))
    elif isinstance(target, ast.Starred):
        names.update(_extract_target_names(target.value))
    return names


def _collect_assigned_names_in_stmts(stmts: Iterable[ast.stmt]) -> Set[str]:
    """Collect names bound in the current lexical block without descending into nested defs/classes."""
    names: Set[str] = set()

    def _visit_node(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            return
        if isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
            return
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
            return
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                names.update(_extract_target_names(tgt))
        elif isinstance(node, ast.AnnAssign):
            names.update(_extract_target_names(node.target))
        elif isinstance(node, ast.AugAssign):
            names.update(_extract_target_names(node.target))
        elif isinstance(node, ast.NamedExpr):
            names.add(node.target.id)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            names.update(_extract_target_names(node.target))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    names.update(_extract_target_names(item.optional_vars))
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                names.add(node.name)
        elif isinstance(node, ast.Global):
            names.update(node.names)
            return
        elif isinstance(node, ast.Nonlocal):
            names.update(node.names)
            return

        # Python 3.10+ pattern matching bindings
        if hasattr(ast, "MatchAs") and isinstance(node, ast.MatchAs) and node.name:
            names.add(node.name)
        if hasattr(ast, "MatchStar") and isinstance(node, ast.MatchStar) and node.name:
            names.add(node.name)
        if hasattr(ast, "MatchMapping") and isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)

        for child in ast.iter_child_nodes(node):
            _visit_node(child)

    for stmt in stmts:
        _visit_node(stmt)
    return names


def _collect_all_exports(tree: ast.Module) -> Set[str]:
    exports: Set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets):
                if isinstance(stmt.value, (ast.List, ast.Tuple, ast.Set)):
                    for elt in stmt.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            exports.add(elt.value)
    return exports


def _module_uses_dynamic_scope(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return True
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in {"exec", "eval", "globals", "locals"}:
                return True
    return False


def _collect_referenced_names(tree: ast.Module) -> Set[str]:
    referenced: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            root = node.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                referenced.add(root.id)
    return referenced


class _ScopeAnalyzer(ast.NodeVisitor):
    """Conservative lexical scope visitor for detecting undefined names."""

    def __init__(self, file_path: str, lines: Sequence[str], module_bindings: Set[str]) -> None:
        self.file_path = file_path
        self.lines = lines
        self.scopes: List[Set[str]] = [_BUILTIN_NAMES | module_bindings]
        self.findings: List[FindingRecord] = []
        self._reported: Set[Tuple[int, str]] = set()

    def _is_bound(self, name: str) -> bool:
        return any(name in scope for scope in reversed(self.scopes))

    def _check_type_params(self, node: ast.AST) -> Set[str]:
        bound: Set[str] = set()
        for param in getattr(node, "type_params", ()):
            name = getattr(param, "name", None)
            if isinstance(name, str):
                bound.add(name)
        return bound

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            if not self._is_bound(node.id):
                key = (node.lineno, node.id)
                if key not in self._reported:
                    self._reported.add(key)
                    self.findings.append(
                        FindingRecord(
                            id=_finding_id("AST401", self.file_path, node.lineno, node.col_offset + 1, node.id),
                            file_path=self.file_path,
                            line_number=node.lineno,
                            column=node.col_offset + 1,
                            tool="ast",
                            rule_id="AST401",
                            category="runtime",
                            severity="HIGH",
                            confidence="MEDIUM",
                            original_severity="error",
                            original_confidence="medium",
                            title=f"Undefined name '{node.id}'",
                            description=(
                                f"Identifier '{node.id}' is referenced before any visible assignment, "
                                "import, parameter, or builtin definition in this lexical scope."
                            ),
                            evidence=_get_line(self.lines, node.lineno),
                            suggested_fix=f"Define or import '{node.id}' before referencing it.",
                        )
                    )

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        for arg in (
            list(node.args.posonlyargs)
            + list(node.args.args)
            + list(node.args.kwonlyargs)
            + ([node.args.vararg] if node.args.vararg else [])
            + ([node.args.kwarg] if node.args.kwarg else [])
        ):
            if arg.annotation is not None:
                self.visit(arg.annotation)
        if node.returns is not None:
            self.visit(node.returns)

        local_scope: Set[str] = set()
        for arg in (
            list(node.args.posonlyargs)
            + list(node.args.args)
            + list(node.args.kwonlyargs)
        ):
            local_scope.add(arg.arg)
        if node.args.vararg:
            local_scope.add(node.args.vararg.arg)
        if node.args.kwarg:
            local_scope.add(node.args.kwarg.arg)
        local_scope.update(self._check_type_params(node))
        local_scope.update(_collect_assigned_names_in_stmts(node.body))

        self.scopes.append(local_scope)
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw.value)

        class_scope = _collect_assigned_names_in_stmts(node.body)
        class_scope.update(self._check_type_params(node))
        self.scopes.append(class_scope)
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        lambda_scope: Set[str] = {
            a.arg for a in list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
        }
        if node.args.vararg:
            lambda_scope.add(node.args.vararg.arg)
        if node.args.kwarg:
            lambda_scope.add(node.args.kwarg.arg)
        self.scopes.append(lambda_scope)
        self.visit(node.body)
        self.scopes.pop()

    def _visit_comprehension(self, generators: List[ast.comprehension], *exprs: ast.AST) -> None:
        comp_scope: Set[str] = set()
        self.scopes.append(comp_scope)
        for gen in generators:
            self.visit(gen.iter)
            comp_scope.update(_extract_target_names(gen.target))
            for cond in gen.ifs:
                self.visit(cond)
        for expr in exprs:
            self.visit(expr)
        self.scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, node.elt)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, node.elt)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, node.elt)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, node.key, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # String annotations are deferred and not evaluated at runtime here.
        if not (isinstance(node.annotation, ast.Constant) and isinstance(node.annotation.value, str)):
            self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)


def _check_unreachable_blocks(
    stmts: Sequence[ast.stmt], file_path: str, lines: Sequence[str], findings: List[FindingRecord]
) -> None:
    terminated = False
    for stmt in stmts:
        if terminated:
            findings.append(
                FindingRecord(
                    id=_finding_id("AST203", file_path, stmt.lineno, stmt.col_offset + 1),
                    file_path=file_path,
                    line_number=stmt.lineno,
                    column=stmt.col_offset + 1,
                    tool="ast",
                    rule_id="AST203",
                    category="runtime",
                    severity="MEDIUM",
                    confidence="HIGH",
                    original_severity="warning",
                    original_confidence="high",
                    title="Unreachable statement after control-flow exit",
                    description="Statement appears after return, raise, break, or continue in the same block.",
                    evidence=_get_line(lines, stmt.lineno),
                    suggested_fix="Remove the unreachable code or adjust the preceding control flow.",
                )
            )
            break
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            terminated = True


def _analyze_ast_tree(tree: ast.Module, file_path: str, source: str) -> List[FindingRecord]:
    lines = source.splitlines()
    findings: List[FindingRecord] = []

    # Collect top-level imports (excluding __future__ and TYPE_CHECKING blocks)
    top_imports: List[_ImportBinding] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                bound = alias.asname or alias.name.split(".")[0]
                top_imports.append(_ImportBinding(bound, alias.name, stmt.lineno, stmt.col_offset + 1))
        elif isinstance(stmt, ast.ImportFrom):
            if stmt.module == "__future__":
                continue
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                top_imports.append(
                    _ImportBinding(bound, f"{stmt.module or ''}.{alias.name}", stmt.lineno, stmt.col_offset + 1)
                )

    all_exports = _collect_all_exports(tree)
    referenced_names = _collect_referenced_names(tree)

    for imp in top_imports:
        if imp.bound_name.startswith("_"):
            continue
        if imp.bound_name in all_exports:
            continue
        if imp.bound_name not in referenced_names:
            findings.append(
                FindingRecord(
                    id=_finding_id("AST301", file_path, imp.line, imp.col, imp.bound_name),
                    file_path=file_path,
                    line_number=imp.line,
                    column=imp.col,
                    tool="ast",
                    rule_id="AST301",
                    category="quality",
                    severity="LOW",
                    confidence="MEDIUM",
                    original_severity="low",
                    original_confidence="medium",
                    title=f"Unused import '{imp.bound_name}'",
                    description=f"Imported symbol '{imp.full_name}' is not referenced in this module.",
                    evidence=_get_line(lines, imp.line),
                    suggested_fix=f"Remove the unused import '{imp.bound_name}' if not required for side effects.",
                )
            )

    # Structural, suspicious call, empty block, and credential checks
    for node in ast.walk(tree):
        # Unreachable statements inside body-bearing nodes
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(node, attr, None)
            if isinstance(block, list) and block and all(isinstance(s, ast.stmt) for s in block):
                _check_unreachable_blocks(block, file_path, lines, findings)

        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in {"eval", "exec", "compile"}:
                findings.append(
                    FindingRecord(
                        id=_finding_id("AST101", file_path, node.lineno, node.col_offset + 1, name),
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        tool="ast",
                        rule_id="AST101",
                        category="security",
                        severity="HIGH",
                        confidence="HIGH",
                        original_severity="HIGH",
                        original_confidence="HIGH",
                        title=f"Dangerous dynamic execution via {name}()",
                        description=f"Calling {name}() can execute arbitrary code if inputs are untrusted.",
                        evidence=_get_line(lines, node.lineno),
                        suggested_fix="Replace dynamic code execution with safe parsing (e.g. ast.literal_eval) or explicit dispatch.",
                    )
                )
            elif name == "__import__":
                findings.append(
                    FindingRecord(
                        id=_finding_id("AST102", file_path, node.lineno, node.col_offset + 1),
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        tool="ast",
                        rule_id="AST102",
                        category="security",
                        severity="MEDIUM",
                        confidence="MEDIUM",
                        original_severity="MEDIUM",
                        original_confidence="MEDIUM",
                        title="Dynamic module import via __import__()",
                        description="Direct __import__() calls obscure dependencies and may import arbitrary modules.",
                        evidence=_get_line(lines, node.lineno),
                        suggested_fix="Use standard static import statements or importlib.import_module with allowlisted names.",
                    )
                )
            elif name in {f"pickle.{f}" for f in _PICKLE_FUNCS} or name in {"marshal.loads", "marshal.load"}:
                findings.append(
                    FindingRecord(
                        id=_finding_id("AST103", file_path, node.lineno, node.col_offset + 1, name),
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        tool="ast",
                        rule_id="AST103",
                        category="security",
                        severity="HIGH",
                        confidence="MEDIUM",
                        original_severity="HIGH",
                        original_confidence="MEDIUM",
                        title=f"Potentially unsafe deserialization via {name}()",
                        description=f"{name}() can execute arbitrary code when loading untrusted data.",
                        evidence=_get_line(lines, node.lineno),
                        suggested_fix="Use a safe data format such as JSON instead of pickle/marshal for untrusted inputs.",
                    )
                )
            elif (
                name.startswith("subprocess.")
                and name.split(".", 1)[1] in _SUBPROCESS_CALLS
                and any(kw.arg == "shell" and _is_true_constant(kw.value) for kw in node.keywords)
            ) or name in {"os.system", "os.popen"}:
                findings.append(
                    FindingRecord(
                        id=_finding_id("AST104", file_path, node.lineno, node.col_offset + 1, name),
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        tool="ast",
                        rule_id="AST104",
                        category="security",
                        severity="HIGH",
                        confidence="HIGH",
                        original_severity="HIGH",
                        original_confidence="HIGH",
                        title=f"Shell command execution via {name}()",
                        description="Invoking subprocess with shell=True or os.system() risks command injection.",
                        evidence=_get_line(lines, node.lineno),
                        suggested_fix="Use subprocess.run([...], shell=False) with an explicit argument list.",
                    )
                )
            elif name == "yaml.load":
                has_safe_loader = any(
                    kw.arg == "Loader"
                    and (
                        (isinstance(kw.value, ast.Name) and kw.value.id in {"SafeLoader", "CSafeLoader"})
                        or (isinstance(kw.value, ast.Attribute) and kw.value.attr in {"SafeLoader", "CSafeLoader"})
                    )
                    for kw in node.keywords
                )
                if not has_safe_loader:
                    findings.append(
                        FindingRecord(
                            id=_finding_id("AST105", file_path, node.lineno, node.col_offset + 1),
                            file_path=file_path,
                            line_number=node.lineno,
                            column=node.col_offset + 1,
                            tool="ast",
                            rule_id="AST105",
                            category="security",
                            severity="MEDIUM",
                            confidence="HIGH",
                            original_severity="MEDIUM",
                            original_confidence="HIGH",
                            title="Potentially unsafe yaml.load() call",
                            description="yaml.load() without SafeLoader can construct arbitrary Python objects.",
                            evidence=_get_line(lines, node.lineno),
                            suggested_fix="Use yaml.safe_load() or pass Loader=yaml.SafeLoader.",
                        )
                    )

        elif isinstance(node, ast.ExceptHandler):
            is_broad = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
            )
            if is_broad and _is_pass_only(node.body):
                findings.append(
                    FindingRecord(
                        id=_finding_id("AST201", file_path, node.lineno, node.col_offset + 1),
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        tool="ast",
                        rule_id="AST201",
                        category="suspicious",
                        severity="MEDIUM",
                        confidence="HIGH",
                        original_severity="MEDIUM",
                        original_confidence="HIGH",
                        title="Silent broad exception handler",
                        description="Catching broad or bare exceptions with pass silently hides failures.",
                        evidence=_get_line(lines, node.lineno),
                        suggested_fix="Catch specific exception types and log or handle failures explicitly.",
                    )
                )

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _has_abstract_decorator(node) and _is_pass_only(node.body):
                findings.append(
                    FindingRecord(
                        id=_finding_id("AST202", file_path, node.lineno, node.col_offset + 1, node.name),
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        tool="ast",
                        rule_id="AST202",
                        category="maintainability",
                        severity="LOW",
                        confidence="MEDIUM",
                        original_severity="LOW",
                        original_confidence="MEDIUM",
                        title=f"Empty function body in '{node.name}'",
                        description=f"Function '{node.name}' contains only 'pass' and no implementation.",
                        evidence=_get_line(lines, node.lineno),
                        suggested_fix="Implement the function body or mark it @abstractmethod if intentional.",
                    )
                )
            for default in list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    findings.append(
                        FindingRecord(
                            id=_finding_id("AST204", file_path, default.lineno, default.col_offset + 1),
                            file_path=file_path,
                            line_number=default.lineno,
                            column=default.col_offset + 1,
                            tool="ast",
                            rule_id="AST204",
                            category="runtime",
                            severity="MEDIUM",
                            confidence="HIGH",
                            original_severity="MEDIUM",
                            original_confidence="HIGH",
                            title=f"Mutable default argument in '{node.name}'",
                            description="Mutable defaults are shared across calls and cause state leakage bugs.",
                            evidence=_get_line(lines, node.lineno),
                            suggested_fix="Use None as the default and initialize a new container inside the function.",
                        )
                    )

        elif isinstance(node, ast.If):
            if not _is_type_checking_guard(node.test) and _is_pass_only(node.body):
                findings.append(
                    FindingRecord(
                        id=_finding_id("AST202", file_path, node.lineno, node.col_offset + 1, "if"),
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        tool="ast",
                        rule_id="AST202",
                        category="suspicious",
                        severity="LOW",
                        confidence="MEDIUM",
                        original_severity="LOW",
                        original_confidence="MEDIUM",
                        title="Empty conditional block",
                        description="Conditional branch contains only 'pass'.",
                        evidence=_get_line(lines, node.lineno),
                        suggested_fix="Implement the branch logic or remove the redundant conditional.",
                    )
                )

        elif isinstance(node, ast.Assert):
            if isinstance(node.test, ast.Tuple) and len(node.test.elts) > 0:
                findings.append(
                    FindingRecord(
                        id=_finding_id("AST205", file_path, node.lineno, node.col_offset + 1),
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        tool="ast",
                        rule_id="AST205",
                        category="runtime",
                        severity="MEDIUM",
                        confidence="HIGH",
                        original_severity="MEDIUM",
                        original_confidence="HIGH",
                        title="Assertion on non-empty tuple always evaluates to True",
                        description="assert (cond, msg) checks truthiness of a 2-tuple rather than calling assert cond, msg.",
                        evidence=_get_line(lines, node.lineno),
                        suggested_fix="Remove parentheses around the assert condition and message.",
                    )
                )

        elif isinstance(node, ast.Dict):
            seen_keys: Set[object] = set()
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, (str, int, float, bool)):
                    key_marker = (type(k.value), k.value)
                    if key_marker in seen_keys:
                        findings.append(
                            FindingRecord(
                                id=_finding_id("AST206", file_path, k.lineno, k.col_offset + 1, str(k.value)),
                                file_path=file_path,
                                line_number=k.lineno,
                                column=k.col_offset + 1,
                                tool="ast",
                                rule_id="AST206",
                                category="runtime",
                                severity="MEDIUM",
                                confidence="HIGH",
                                original_severity="MEDIUM",
                                original_confidence="HIGH",
                                title=f"Duplicate dictionary key {k.value!r}",
                                description="Later duplicate dictionary key silently overwrites the earlier value.",
                                evidence=_get_line(lines, k.lineno),
                                suggested_fix="Remove or rename the duplicate dictionary key.",
                            )
                        )
                    seen_keys.add(key_marker)

        elif isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                val = node.value.value.strip()
                if val and val.lower() not in _PLACEHOLDER_SECRETS:
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id.lower() in _SENSITIVE_VAR_NAMES:
                            findings.append(
                                FindingRecord(
                                    id=_finding_id("AST501", file_path, node.lineno, node.col_offset + 1, tgt.id),
                                    file_path=file_path,
                                    line_number=node.lineno,
                                    column=node.col_offset + 1,
                                    tool="ast",
                                    rule_id="AST501",
                                    category="security",
                                    severity="HIGH",
                                    confidence="MEDIUM",
                                    original_severity="HIGH",
                                    original_confidence="MEDIUM",
                                    title=f"Possible hardcoded credential in '{tgt.id}'",
                                    description=f"A non-empty string literal is assigned directly to sensitive variable '{tgt.id}'.",
                                    evidence=f"{tgt.id} = '***redacted***'",
                                    suggested_fix="Load secrets from environment variables or a secure secret store.",
                                )
                            )

    # Conservative undefined name analysis
    if not _module_uses_dynamic_scope(tree):
        module_bindings = _collect_assigned_names_in_stmts(tree.body)
        analyzer = _ScopeAnalyzer(file_path, lines, module_bindings)
        for stmt in tree.body:
            analyzer.visit(stmt)
        findings.extend(analyzer.findings)

    return findings


def run_ast_scan(
    project_root: Path, rel_files: Sequence[str], max_file_bytes: int
) -> AstScanOutcome:
    """Parse and statically inspect Python files using Python's built-in `ast` module."""
    started = time.monotonic()
    outcome = AstScanOutcome()

    if not rel_files:
        outcome.summary = ScannerToolSummary(
            status="skipped",
            findings_count=0,
            duration_ms=0,
            limitations=list(AST_LIMITATIONS),
        )
        return outcome

    resolved_root = project_root.resolve()
    for rel_path in rel_files:
        candidate = (resolved_root / rel_path).resolve()
        if not is_within_directory(resolved_root, candidate):
            outcome.skipped_files.append(
                SkippedScanFile(file_path=rel_path, reason="Path escapes project workspace.")
            )
            continue

        try:
            st = candidate.stat()
            if st.st_size > max_file_bytes:
                outcome.skipped_files.append(
                    SkippedScanFile(
                        file_path=rel_path,
                        reason=f"File exceeds scan limit of {max_file_bytes} bytes.",
                    )
                )
                continue
            raw_bytes = candidate.read_bytes()
            source = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            outcome.skipped_files.append(
                SkippedScanFile(file_path=rel_path, reason="File is not valid UTF-8 text.")
            )
            continue
        except OSError as exc:
            outcome.skipped_files.append(
                SkippedScanFile(file_path=rel_path, reason=f"Unreadable file: {exc.strerror or type(exc).__name__}")
            )
            continue

        outcome.files_scanned += 1
        lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError as exc:
            ln = exc.lineno or 1
            outcome.findings.append(
                FindingRecord(
                    id=_finding_id("AST001", rel_path, ln, exc.offset),
                    file_path=rel_path,
                    line_number=ln,
                    column=exc.offset,
                    tool="ast",
                    rule_id="AST001",
                    category="syntax",
                    severity="HIGH",
                    confidence="HIGH",
                    original_severity="error",
                    original_confidence="high",
                    title="Python syntax error",
                    description=f"Invalid Python syntax: {exc.msg}",
                    evidence=_get_line(lines, ln) or (exc.text or "").strip(),
                    suggested_fix="Fix the invalid syntax at the reported line and column.",
                )
            )
            continue

        outcome.findings.extend(_analyze_ast_tree(tree, rel_path, source))

    duration_ms = int((time.monotonic() - started) * 1000)
    outcome.summary = ScannerToolSummary(
        status="completed",
        findings_count=len(outcome.findings),
        duration_ms=duration_ms,
        limitations=list(AST_LIMITATIONS),
    )
    return outcome
