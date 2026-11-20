"""CSS parsing on top of tinycss2."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import tinycss2

KNOWN_PROPERTIES = set("""
align-content align-items align-self all animation animation-delay animation-direction
animation-duration animation-fill-mode animation-iteration-count animation-name
animation-play-state animation-timing-function aspect-ratio backdrop-filter backface-visibility
background background-attachment background-blend-mode background-clip background-color
background-image background-origin background-position background-repeat background-size
block-size border border-block border-bottom border-bottom-color border-bottom-left-radius
border-bottom-right-radius border-bottom-style border-bottom-width border-collapse border-color
border-image border-inline border-left border-left-color border-left-style border-left-width
border-radius border-right border-right-color border-right-style border-right-width
border-spacing border-style border-top border-top-color border-top-left-radius
border-top-right-radius border-top-style border-top-width border-width bottom box-shadow
box-sizing break-after break-before break-inside caption-side caret-color clear clip clip-path
color column-count column-gap column-rule column-span column-width columns content
counter-increment counter-reset cursor direction display empty-cells filter flex flex-basis
flex-direction flex-flow flex-grow flex-shrink flex-wrap float font font-family
font-feature-settings font-kerning font-size font-size-adjust font-stretch font-style
font-variant font-weight gap grid grid-area grid-auto-columns grid-auto-flow grid-auto-rows
grid-column grid-column-end grid-column-gap grid-column-start grid-gap grid-row grid-row-end
grid-row-gap grid-row-start grid-template grid-template-areas grid-template-columns
grid-template-rows height hyphens image-rendering inline-size inset isolation justify-content
justify-items justify-self left letter-spacing line-height list-style list-style-image
list-style-position list-style-type margin margin-block margin-bottom margin-inline margin-left
margin-right margin-top mask max-height max-width min-height min-width mix-blend-mode object-fit
object-position opacity order outline outline-color outline-offset outline-style outline-width
overflow overflow-wrap overflow-x overflow-y padding padding-block padding-bottom padding-inline
padding-left padding-right padding-top page-break-after page-break-before page-break-inside
perspective place-content place-items place-self pointer-events position quotes resize right
rotate row-gap scale scroll-behavior scroll-margin scroll-padding scroll-snap-align
scroll-snap-type tab-size table-layout text-align text-align-last text-decoration
text-decoration-color text-decoration-line text-decoration-style text-decoration-thickness
text-indent text-justify text-overflow text-shadow text-transform text-underline-offset top
transform transform-origin transform-style transition transition-delay transition-duration
transition-property transition-timing-function translate unicode-bidi user-select
vertical-align visibility white-space width word-break word-spacing word-wrap writing-mode
z-index zoom accent-color appearance contain content-visibility font-display src
inset-block inset-inline line-clamp orphans widows will-change
""".split())


@dataclass
class CssRule:
    selector: str
    declarations: dict[str, str]
    line: int
    media: str | None = None
    important: list[str] = field(default_factory=list)


@dataclass
class CssIssue:
    line: int
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


def parse_declarations(text: str) -> dict[str, str]:
    """Parse a style="..." attribute or a declaration block body."""
    out = {}
    for d in tinycss2.parse_blocks_contents(text, skip_comments=True, skip_whitespace=True):
        if d.type == "declaration":
            out[d.lower_name] = tinycss2.serialize(d.value).strip()
    return out


class CssDoc:
    def __init__(self, path: str, source: str) -> None:
        self.path = path
        self.source = source
        self.rules: list[CssRule] = []
        self.at_rules: list[str] = []
        self.issues: list[CssIssue] = []
        self.comments: list[str] = re.findall(r"/\*(.*?)\*/", source, re.S)
        self._parse()

    def _parse(self) -> None:
        if self.source.count("{") != self.source.count("}"):
            self.issues.append(CssIssue(0, f"Unbalanced braces: {self.source.count('{')} '{{' vs "
                                           f"{self.source.count('}')} '}}'"))
        if re.search(r"<\s*/?\s*style", self.source, re.I):
            self.issues.append(CssIssue(1, "External CSS must not contain <style> tags"))
        nodes = tinycss2.parse_stylesheet(self.source, skip_comments=True, skip_whitespace=True)
        self._walk(nodes, None)

    def _walk(self, nodes, media):
        for n in nodes:
            if n.type == "error":
                self.issues.append(CssIssue(n.source_line, f"Parse error: {n.message}"))
            elif n.type == "at-rule":
                self.at_rules.append(f"@{n.lower_at_keyword} {tinycss2.serialize(n.prelude).strip()}")
                if n.content is not None and n.lower_at_keyword in ("media", "supports", "layer"):
                    inner = tinycss2.parse_rule_list(n.content, skip_comments=True, skip_whitespace=True)
                    self._walk(inner, tinycss2.serialize(n.prelude).strip())
            elif n.type == "qualified-rule":
                sel = re.sub(r"\s+", " ", tinycss2.serialize(n.prelude)).strip()
                decls, imp = {}, []
                for d in tinycss2.parse_blocks_contents(n.content, skip_comments=True, skip_whitespace=True):
                    if d.type == "declaration":
                        decls[d.lower_name] = tinycss2.serialize(d.value).strip()
                        if d.important:
                            imp.append(d.lower_name)
                        if (d.lower_name not in KNOWN_PROPERTIES and not d.lower_name.startswith("-")
                                and not d.lower_name.startswith("--")):
                            self.issues.append(CssIssue(d.source_line,
                                                        f"Unknown property '{d.lower_name}' in '{sel}'", "warning"))
                        if not tinycss2.serialize(d.value).strip():
                            self.issues.append(CssIssue(d.source_line, f"Empty value for '{d.lower_name}'"))
                    elif d.type == "error":
                        self.issues.append(CssIssue(d.source_line, f"Bad declaration in '{sel}': {d.message}"))
                    elif d.type not in ("whitespace", "comment"):
                        self.issues.append(CssIssue(getattr(d, "source_line", n.source_line),
                                                    f"Unexpected content in '{sel}' (missing ';' or ':'?)"))
                if not sel:
                    self.issues.append(CssIssue(n.source_line, "Rule with an empty selector"))
                self.rules.append(CssRule(sel, decls, n.source_line, media, imp))

    # -- queries ---------------------------------------------------------------
    def errors(self) -> list[CssIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def warnings(self) -> list[CssIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def selectors(self) -> list[str]:
        out = []
        for r in self.rules:
            out.extend(s.strip() for s in r.selector.split(","))
        return out

    def properties(self) -> set[str]:
        return {p for r in self.rules for p in r.declarations}

    def rules_for(self, element: str) -> list[CssRule]:
        """Rules whose selector targets ``element`` as a type selector, e.g.
        ``rules_for('td')`` matches ``td``, ``table td``, ``tr > td:hover``."""
        pat = re.compile(rf"(^|[\s>+~,(]){re.escape(element)}(?=$|[\s.#:\[>+~,)])", re.I)
        return [r for r in self.rules if pat.search(r.selector)]

    def rules_matching(self, pattern: str) -> list[CssRule]:
        """Rules whose selector matches a regex (case-insensitive)."""
        rx = re.compile(pattern, re.I)
        return [r for r in self.rules if rx.search(r.selector)]

    def uses_property(self, prop: str) -> bool:
        return prop.lower() in self.properties()

    @property
    def media_queries(self) -> list[str]:
        return [a for a in self.at_rules if a.startswith("@media")]
