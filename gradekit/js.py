"""Static analysis of JavaScript (student code is never executed)."""
from __future__ import annotations

import re

try:
    import esprima  # type: ignore
except Exception:  # pragma: no cover
    esprima = None


def _to_dict(node):
    if hasattr(node, "toDict"):
        return node.toDict()
    return node


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _member_name(node) -> str:
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "Identifier":
        return node.get("name", "")
    if t == "ThisExpression":
        return "this"
    if t == "MemberExpression":
        obj = _member_name(node.get("object"))
        prop = node.get("property") or {}
        name = prop.get("name") if not node.get("computed") else (prop.get("value") or "[]")
        return f"{obj}.{name}" if obj else str(name)
    if t == "CallExpression":
        return _member_name(node.get("callee")) + "()"
    return ""


class JsDoc:
    def __init__(self, path: str, source: str) -> None:
        self.path = path
        self.source = source
        self.syntax_error: str | None = None
        self.ast: dict = {}
        self._comments: list[str] = []
        self._parse()

    def _parse(self) -> None:
        if esprima is None:
            self.syntax_error = None
            return
        last = None
        for fn in (esprima.parseScript, esprima.parseModule):
            try:
                tree = fn(self.source, {"loc": True, "comment": True, "tolerant": False})
                self.ast = _to_dict(tree)
                self._comments = [c.get("value", "") for c in self.ast.get("comments", [])]
                self.syntax_error = None
                return
            except Exception as e:  # esprima.Error
                last = e
        msg = str(last)
        # esprima may not know very new syntax; don't fail students for that.
        self.syntax_error = msg

    @property
    def parsed(self) -> bool:
        return bool(self.ast)

    def nodes(self, type_: str | None = None):
        for n in _walk(self.ast.get("body", [])):
            if "type" in n and (type_ is None or n["type"] == type_):
                yield n

    def functions(self) -> list[str]:
        """Names of declared functions, including `const f = () => ...`."""
        names = []
        for n in self.nodes():
            if n["type"] == "FunctionDeclaration" and n.get("id"):
                names.append(n["id"]["name"])
            elif n["type"] == "VariableDeclarator" and isinstance(n.get("init"), dict) and \
                    n["init"].get("type") in ("ArrowFunctionExpression", "FunctionExpression"):
                if n.get("id", {}).get("type") == "Identifier":
                    names.append(n["id"]["name"])
        if not self.parsed:
            names = re.findall(r"function\s+([A-Za-z_$][\w$]*)", self.source)
            names += re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>", self.source)
        return names

    def calls(self) -> list[str]:
        """Dotted callee names, e.g. 'document.getElementById', 'alert'."""
        if not self.parsed:
            return re.findall(r"([A-Za-z_$][\w$.]*)\s*\(", self.source)
        return [_member_name(n.get("callee")) for n in self.nodes("CallExpression")]

    def uses(self, name: str) -> bool:
        """True if code calls/references ``name`` (e.g. 'addEventListener',
        'querySelector', 'localStorage.setItem', 'fetch')."""
        if any(c == name or c.endswith("." + name) for c in self.calls()):
            return True
        return re.search(rf"\b{re.escape(name)}\b", self.source) is not None

    def event_listeners(self) -> list[str]:
        """Event types registered with addEventListener."""
        out = []
        for n in self.nodes("CallExpression"):
            if _member_name(n.get("callee")).endswith("addEventListener"):
                args = n.get("arguments") or []
                if args and args[0].get("type") == "Literal":
                    out.append(str(args[0].get("value")))
        if not self.parsed:
            out = re.findall(r"addEventListener\(\s*['\"](\w+)['\"]", self.source)
        return out

    def assigned_handlers(self) -> list[str]:
        """Handlers assigned like `btn.onclick = ...` -> ['onclick']."""
        return re.findall(r"\.(on[a-z]+)\s*=", self.source)

    def declarations(self) -> dict[str, int]:
        """Counts of var/let/const declarations."""
        out = {"var": 0, "let": 0, "const": 0}
        for n in self.nodes("VariableDeclaration"):
            out[n.get("kind", "var")] = out.get(n.get("kind", "var"), 0) + 1
        if not self.parsed:
            for k in out:
                out[k] = len(re.findall(rf"\b{k}\s+[A-Za-z_$]", self.source))
        return out

    def comments(self) -> list[str]:
        if self._comments:
            return self._comments
        return re.findall(r"//[^\n]*|/\*.*?\*/", self.source, re.S)

    def uses_strict_equality(self) -> bool:
        return "===" in self.source or "!==" in self.source

    def dom_apis(self) -> set[str]:
        apis = ["getElementById", "getElementsByClassName", "getElementsByTagName", "querySelector",
                "querySelectorAll", "createElement", "appendChild", "append", "removeChild", "remove",
                "innerHTML", "textContent", "innerText", "classList", "setAttribute", "style",
                "addEventListener", "value"]
        return {a for a in apis if re.search(rf"\.{a}\b", self.source)}
