# gradekit API reference (for checker scripts)

A checker is one Python file that defines:

```python
from gradekit import Submission, Report, is_descriptive_alt, band, band_max, word_count

def grade(sub: Submission) -> Report:
    report = Report()
    with report.criterion("criterion_id", "Criterion name", 10) as c:
        ...            # inspect files, call c.check(...), c.note(...)
        c.score = 7    # REQUIRED unless c.ai_review(...) is used
        c.level = "Proficient"   # optional: rubric level label
    return report
```

Rules:
- One `with report.criterion(id, name, max_marks)` block per rubric criterion, using the
  exact ids and max marks from the rubric JSON. Exceptions inside a block are caught and
  recorded for that criterion only — but write defensive code anyway (files may be missing).
- Scores are clamped to `0..max_marks` and rounded to 0.5.
- Student code is untrusted input. Never execute it. Only read files via `sub`.
- Allowed imports: `gradekit`, `re`, `math`, `statistics`, `collections`, `itertools`,
  `functools`, `string`, `json`, `difflib`, `textwrap`, `unicodedata`, `html`, `typing`,
  `dataclasses`, `urllib.parse`, `bs4`, `tinycss2`. No `open`, `os`, `subprocess`, network, `eval`/`exec`.

## Report / CriterionResult
| call | meaning |
|---|---|
| `report.criterion(id, name, max)` | create a criterion (use as context manager) |
| `c.check(label, passed, detail="") -> bool` | record a visible pass/fail check |
| `c.note(text)` | add a feedback sentence for the student |
| `c.score = x`, `c.level = "label"` | marks awarded and rubric level |
| `c.ai_review(instructions, content, provisional_score=None, scoring_guide="")` | let the AI judge score subjective parts (spelling/grammar, writing quality, design). `content` = the text/code to judge. `provisional_score` = heuristic fallback. If you also set `c.score`, the AI's score replaces it. |
| `report.deduct(reason, marks)` | penalty outside the criteria (wrong filenames, wrong file types…) |
| `report.note(text)` | general comment |

## Submission (`sub`)
| member | returns |
|---|---|
| `sub.name` | student folder name |
| `sub.files(glob="*")` | relative paths matching a basename glob, case-insensitive |
| `sub.html_files()`, `sub.css_files()`, `sub.js_files()`, `sub.image_files()` | relative paths |
| `sub.exists(path)` | exact, case-sensitive check |
| `sub.find(name, case_sensitive=False)` | path of a file with that basename anywhere, or None |
| `sub.expect_file(name, alternatives=[])` | `FileMatch(.found, .path, .exact, .problem)` — `.exact` False means misnamed (e.g. `MyBio.html`, `mybio.htm`) |
| `sub.read_text(path)`, `sub.size(path)` | file contents / bytes |
| `sub.html(name)` → `HtmlDoc` or None | parsed HTML (found case-insensitively) |
| `sub.css(name)` → `CssDoc` or None | parsed CSS |
| `sub.js(name)` → `JsDoc` or None | parsed JS (static analysis only) |
| `sub.all_html()` | list of `HtmlDoc` for every HTML file |
| `sub.image_info(path)` | `{bytes, width, height, format}` or None if file missing |
| `sub.resolve(from_file, href)` | `LinkCheck(.kind, .ok, .target, .case_mismatch, .problem)`; kind ∈ internal/external/anchor/mailto/tel/javascript/empty. Use it for `<a href>`, `<img src>`, `<link href>`, `<script src>`. |
| `sub.link_report(html_name)` | `LinkCheck` for every `<a>` in that page |
| `sub.links_to(html_name, target_name)` | True if page has a *working* link to target |

## HtmlDoc (`doc = sub.html("index.html")`)
| member | returns |
|---|---|
| `doc.path`, `doc.source`, `doc.lines`, `doc.soup` (BeautifulSoup) | raw access |
| `doc.has_doctype`, `doc.doctype`, `doc.title` | |
| `doc.has(*tags)` | any of the tags present, e.g. `doc.has("b", "strong")` |
| `doc.count(tag)`, `doc.find_all(tag, **attrs)`, `doc.tag_counts()` | |
| `doc.text`, `doc.word_count()` | visible text (no script/style/comments) |
| `doc.paragraphs()`, `doc.paragraph_word_count()` | text of each `<p>` / total words in `<p>` |
| `doc.headings()` | `[(level, text)]` |
| `doc.comments()` | HTML comments (internal documentation) |
| `doc.links()` | `[{href, text, has_image, target}]` |
| `doc.images()` | `[{src, alt, width, height, usemap, title, self_closed, in_link, style}]` (alt is None if absent) |
| `doc.image_maps()` | `[{name, areas:[{shape, coords, href, alt}], used_by_img}]` |
| `doc.forms()` | `[{action, method, fields:[{tag, type, name, id}], labels}]` |
| `doc.tables()` | `[{rows, cols, has_th, has_caption, id, class, style, presentational_attrs}]` |
| `doc.stylesheets()` | hrefs of `<link rel="stylesheet">` |
| `doc.style_blocks()` | embedded `<style>` contents |
| `doc.inline_styles()` | `[(tag, style_attr)]` |
| `doc.scripts()` | `[{src, code, type, defer}]` |
| `doc.event_attributes()` | inline handlers `[(tag, "onclick", code)]` |
| `doc.ids()`, `doc.classes()`, `doc.meta()` | |
| `doc.errors()` | syntax/structure errors: unclosed/stray/mismatched tags, unknown tags, duplicate ids/attributes, missing doctype/html/head/body/title, img without src. Each has `.line`, `.message`; `str(e)` gives "line N: message". |
| `doc.warnings()` | softer issues (obsolete tags like `<font>`, `<div />`) |
| `doc.indentation()` | `{score 0..1, checked, mixed_tabs_spaces, flush_left_ratio, blank_line_ratio}` — score is the share of nested tags indented deeper than their parent. ≥0.7 is reasonable, <0.3 is basically unindented. |

## CssDoc (`css = sub.css("style.css")`)
| member | returns |
|---|---|
| `css.rules` | `[CssRule(selector, declarations: dict, line, media, important)]` |
| `css.selectors()`, `css.properties()`, `css.uses_property(p)` | |
| `css.rules_for("td")` | rules whose selector targets that element type |
| `css.rules_matching(regex)` | rules whose selector matches regex |
| `css.media_queries`, `css.at_rules`, `css.comments` | |
| `css.errors()`, `css.warnings()` | parse errors, unbalanced braces, `<style>` in .css / unknown properties |
| `parse_declarations("color:red; margin:0")` | dict, for inline styles or `<style>` text |
| `CssDoc("embedded", doc.style_blocks()[0])` | parse an embedded `<style>` block |

## JsDoc (`js = sub.js("script.js")`) — static analysis, never executed
| member | returns |
|---|---|
| `js.syntax_error` | None or error message |
| `js.functions()` | declared function names (incl. arrow functions assigned to variables) |
| `js.calls()` | dotted callee names (`document.getElementById`, `alert`, …) |
| `js.uses(name)` | name called or referenced (`"addEventListener"`, `"localStorage"`) |
| `js.event_listeners()` | event types passed to addEventListener |
| `js.assigned_handlers()` | e.g. `["onclick"]` from `btn.onclick = …` |
| `js.declarations()` | `{"var": n, "let": n, "const": n}` |
| `js.comments()`, `js.uses_strict_equality()`, `js.dom_apis()` | |
| `js.ast` | esprima AST as dicts (for anything else) |
Inline scripts: `JsDoc("inline", doc.scripts()[0]["code"])`.

## Text helpers
- `word_count(text)`, `words(text)`, `sentences(text)`
- `is_descriptive_alt(alt, src=None, min_words=2)` — rejects missing/empty, filenames, "image", single words
- `spelling_candidates(text, ignore=set())` — words not in an English dictionary (rough; good as a `provisional_score` input, use `ai_review` for the real decision)
- `band(value, [(threshold, marks), ...])` — higher-is-better lookup
- `band_max(value, [(threshold, marks), ...])` — lower-is-better lookup (e.g. number of mistakes)
