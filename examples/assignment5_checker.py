"""Checker for COMP2057 Assignment #5 — A Small Web Site with CSS / My Biography.

Reference checker written in the same style the agent generates. Also used
by demo mode (no API key) so the app works end-to-end out of the box.
"""
from gradekit import Report, Submission, band_max, is_descriptive_alt, sentences, spelling_candidates

PAGES = ["mybio.html", "education.html", "work.html", "hobbies.html"]
CSS_FILE = "mycss.css"
CONTENT_WORDS = 75          # words of <p> text that count as "content" on a page
LARGE_IMAGE = 500 * 1024    # bytes
HUGE_IMAGE = 1024 * 1024


def level_for(score, levels):
    for label, lo in levels:
        if score >= lo:
            return label
    return levels[-1][0]


def grade(sub: Submission) -> Report:
    report = Report()
    docs = {p: sub.html(p) for p in PAGES}
    present = {p: d for p, d in docs.items() if d is not None}
    all_docs = sub.all_html()
    css_match = sub.expect_file(CSS_FILE)

    # ------------------------------------------------------------------ 1
    with report.criterion("html_elements", "HTML Elements & Properties and Correct Syntax", 20) as c:
        if not all_docs:
            c.note("No HTML files were found in the submission.")
            c.score, c.level = 0, "Beginning"
        else:
            def everywhere(fn):
                return all(fn(d) for d in all_docs)

            def anywhere(fn):
                return any(fn(d) for d in all_docs)

            maps_ok = anywhere(lambda d: any(m["areas"] and m["used_by_img"] for m in d.image_maps()))
            form_ok = anywhere(lambda d: any(len(f["fields"]) >= 2 for f in d.forms()))
            indent = [d.indentation()["score"] for d in all_docs]
            avg_indent = sum(indent) / len(indent)
            commented = sum(1 for d in all_docs if d.comments()) / len(all_docs)
            css_linked = css_match.found and everywhere(
                lambda d: any(sub.resolve(d.path, h).target == css_match.path for h in d.stylesheets()))

            items = [
                ("DOCTYPE on every page", everywhere(lambda d: d.has_doctype)),
                ("<html>", everywhere(lambda d: d.soup.find("html") is not None)),
                ("<head>", everywhere(lambda d: d.soup.find("head") is not None)),
                ("<title> on every page", everywhere(lambda d: bool(d.title))),
                ("<body>", everywhere(lambda d: d.soup.find("body") is not None)),
                ("<p>", anywhere(lambda d: d.has("p"))),
                ("<h1>…<h6>", anywhere(lambda d: bool(d.headings()))),
                ("<hr />", anywhere(lambda d: d.has("hr"))),
                ("<br />", anywhere(lambda d: d.has("br"))),
                ("<b> or <strong>", anywhere(lambda d: d.has("b", "strong"))),
                ("<i> or <em>", anywhere(lambda d: d.has("i", "em"))),
                ("<img />", anywhere(lambda d: d.has("img"))),
                ("<table>", anywhere(lambda d: d.has("table"))),
                ("<a href>", anywhere(lambda d: any(l["href"] for l in d.links()))),
                ("Image map (<map> + <area> used by an <img usemap>)", maps_ok),
                ("Feedback form", form_ok),
                ("Indentation & spacing", avg_indent >= 0.6),
                ("Internal documentation (HTML comments)", commented >= 0.75),
                (f"CSS: {CSS_FILE} linked from every page", css_linked),
            ]
            missing = 0
            for label, ok in items:
                if not c.check(label, ok):
                    missing += 1
            if avg_indent < 0.6:
                c.note(f"Indent nested elements consistently (indentation score {avg_indent:.0%}).")
            if commented < 0.75:
                c.note("Add HTML comments (<!-- ... -->) to document each page.")

            # Page-specific required elements from the assignment brief.
            req_missing = 0
            edu = docs["education.html"]
            if edu is not None:
                if not c.check("education.html uses inline or embedded CSS",
                               edu.inline_styles() or edu.style_blocks()):
                    req_missing += 1
                if not c.check("education.html includes a form", edu.forms()):
                    req_missing += 1
            work = docs["work.html"]
            css = sub.css(css_match.path) if css_match.found else None
            if work is not None:
                styled = bool(css and (css.rules_for("table") or css.rules_for("td") or css.rules_for("th")
                                       or any(cls and css.rules_matching(r"\." + cls[0])
                                              for cls in [t["class"] for t in work.tables()])))
                if not c.check("work.html has a table styled by the external style sheet",
                               work.tables() and styled):
                    req_missing += 1
            hob = docs["hobbies.html"]
            if hob is not None:
                if not c.check("hobbies.html has at least 3 images", len(hob.images()) >= 3,
                               f"found {len(hob.images())}"):
                    req_missing += 1
                if not c.check("hobbies.html has an image map", hob.image_maps()):
                    req_missing += 1

            errors = []
            for d in all_docs:
                # document-level "Missing <...>" issues are already counted as missing items
                errors += [f"{d.path} {e}" for e in d.errors() if not e.message.startswith("Missing")]
            for e in errors[:15]:
                c.note(f"HTML error — {e}")
            if len(errors) > 15:
                c.note(f"…and {len(errors) - 15} more HTML errors.")
            if css and css.errors():
                c.note(f"{CSS_FILE} has {len(css.errors())} syntax problem(s): " +
                       "; ".join(str(e) for e in css.errors()[:3]))

            base = max(0, 20 - missing)
            c.score = max(0, base - len(errors) - req_missing)
            c.note(f"{len(items) - missing}/{len(items)} required items present; "
                   f"-{len(errors)} for HTML errors; -{req_missing} for missing page requirements.")
            c.level = level_for(c.score, [("Exemplary", 20), ("Accomplished", 17), ("Proficient", 14),
                                          ("Developing", 11), ("Beginning", 0)])

    # ------------------------------------------------------------------ 2
    with report.criterion("content", "Webpage Content", 10) as c:
        working = len(present)
        with_content = 0
        for p in PAGES:
            d = docs[p]
            if d is None:
                c.check(f"{p} present", False)
                continue
            n = d.paragraph_word_count()
            if c.check(f"{p} has paragraph content", n >= CONTENT_WORDS, f"{n} words in <p>"):
                with_content += 1
        has_css = c.check(f"{CSS_FILE} present", css_match.found)
        content_score = {4: 10, 3: 9, 2: 7, 1: 5}.get(with_content, 2)
        if working == 4 and has_css:
            cap = 10
        elif working >= 3:
            cap = 7
        elif working >= 2:
            cap = 5
        elif working >= 1:
            cap = 2
        else:
            cap = 0
        c.score = min(content_score, cap)
        if with_content < working:
            c.note(f"Each page needs at least a full paragraph (~{CONTENT_WORDS}+ words) of your own writing.")
        c.level = level_for(c.score, [("Exemplary", 10), ("Accomplished", 8), ("Proficient", 7),
                                      ("Developing", 5), ("Beginning", 0)])

    # ------------------------------------------------------------------ 3
    with report.criterion("navigation", "Navigation", 5) as c:
        if len(present) <= 1:
            c.check("More than one page found", False)
            c.score, c.level = (1 if present else 0), "Beginning"
        else:
            broken = set()
            consistent = True
            image_links_everywhere = True
            for p, d in present.items():
                for lc in sub.link_report(d.path):
                    if lc.problem and lc.kind == "internal":
                        broken.add(lc.problem)
                others = [o for o in PAGES if o != p]
                linked = [o for o in others if docs[o] is not None and sub.links_to(d.path, docs[o].path)]
                if len(linked) < len(others):
                    consistent = False
                if not any(l["has_image"] for l in d.links()):
                    image_links_everywhere = False
            home = docs["mybio.html"]
            home_missing = 3
            if home is not None:
                home_missing = sum(1 for o in PAGES[1:]
                                   if docs[o] is None or not sub.links_to(home.path, docs[o].path))
            c.check("Home page (mybio.html) links to every other page", home_missing == 0,
                    f"{home_missing} missing" if home_missing else "")
            c.check("Every page links to every other page", consistent)
            c.check("No broken internal links", not broken)
            c.check("Navigation uses image/icon links", image_links_everywhere)
            for b in sorted(broken)[:8]:
                c.note(b)
            if consistent and not broken:
                c.score = 5 if image_links_everywhere else 4
                if c.score == 4:
                    c.note("Add icons/images to your menu links for full marks.")
            elif home_missing <= 1 and len(broken) <= 1:
                c.score = 3
            else:
                c.score = 2
            c.level = {5: "Exemplary", 4: "Accomplished", 3: "Proficient", 2: "Developing"}[c.score]

    # ------------------------------------------------------------------ 4
    with report.criterion("images", "Images", 10) as c:
        imgs = [(d, i) for d in all_docs for i in d.images()]
        if not imgs:
            c.check("Site contains images", False)
            c.score, c.level = 0, "Beginning"
        else:
            n = len(imgs)
            desc = sum(1 for _, i in imgs if is_descriptive_alt(i["alt"], i["src"]))
            has_alt = sum(1 for _, i in imgs if i["alt"] and i["alt"].strip())
            sized = sum(1 for _, i in imgs if i["width"] and i["height"])
            large, huge, missing_files = [], [], []
            for d, i in imgs:
                lc = sub.resolve(d.path, i["src"])
                info = sub.image_info(lc.target) if lc.ok and lc.target else None
                if info is None:
                    missing_files.append(f"{d.path}: {i['src']}")
                    continue
                if info["bytes"] > HUGE_IMAGE:
                    huge.append(f"{lc.target} ({info['bytes'] // 1024} KB)")
                elif info["bytes"] > LARGE_IMAGE:
                    large.append(f"{lc.target} ({info['bytes'] // 1024} KB)")
            c.check("Every image has descriptive alt text", desc == n, f"{desc}/{n} descriptive")
            c.check("Every image has width= and height=", sized == n, f"{sized}/{n}")
            c.check("No oversized image files", not (large or huge), ", ".join(sorted(set(huge + large))))
            c.check("All image files exist", not missing_files, "; ".join(missing_files[:5]))
            if desc == n:
                score = 10 if sized == n else (9 if sized >= n / 2 else 8)
            elif desc >= n / 2:
                score = 7
            elif has_alt > 0:
                score = 5
            else:
                score = 2
            if huge:
                score = min(score, 5)
                c.note("Optimise very large images (over 1 MB) — they make the page slow to load.")
            elif large:
                score = min(score, 7)
                c.note("Some images are over 500 KB; resize or compress them.")
            score -= min(3, len(missing_files))
            for _, i in imgs:
                if not is_descriptive_alt(i["alt"], i["src"]):
                    c.note(f"Image '{i['src']}' needs a descriptive alt (currently: {i['alt']!r}).")
            c.score = max(0, score)
            c.level = level_for(c.score, [("Exemplary", 10), ("Accomplished", 8), ("Proficient", 7),
                                          ("Developing", 5), ("Beginning", 0)])

    # ------------------------------------------------------------------ 5
    with report.criterion("spelling", "Proper Spelling, Capitalization, Grammar, and Punctuation", 5) as c:
        texts = [f"=== {d.path} ===\n{d.text}" for d in all_docs]
        content = "\n\n".join(texts)
        if not all_docs:
            c.score, c.level = 0, "Beginning"
        else:
            rough = spelling_candidates(" ".join(d.text for d in all_docs))
            lower_i = content.count(" i ")
            lower_starts = sum(1 for d in all_docs for p in d.paragraphs()
                               for snt in sentences(p) if snt[:1].islower())
            estimate = len(rough) + (1 if lower_i else 0) + lower_starts
            provisional = band_max(estimate, [(0, 5), (1, 4), (2, 3), (3, 2), (4, 1)], default=0)
            c.check("Dictionary spot-check", not rough, ", ".join(rough[:12]))
            c.ai_review(
                instructions=("Count the distinct spelling, grammar, punctuation and capitalization "
                              "mistakes in the visible web page text below. Ignore names of people, "
                              "places and products, HTML/CSS terms and the page labels '=== file ==='. "
                              "A repeated identical mistake counts once. List each mistake."),
                content=content,
                provisional_score=provisional,
                scoring_guide="0 mistakes → 5; 1 → 4; 2 → 3; 3 → 2; 4 → 1; 5 or more → 0.",
            )

    # ------------------------------------------------------------------ deductions
    for name in PAGES + [CSS_FILE]:
        m = sub.expect_file(name, alternatives=[name.replace(".html", ".htm")])
        if m.found and not m.exact:
            report.deduct(f"Improper filename: '{m.path}' should be '{name}'", 1)
    bad_types = [f for f in sub.image_files() if f.lower().endswith((".bmp", ".tif", ".tiff", ".psd", ".heic"))]
    if bad_types:
        report.deduct(f"Incorrect image file types for the web: {', '.join(bad_types[:5])}", 1)
    if not css_match.found and sub.css_files():
        report.note(f"Found {', '.join(sub.css_files())} but the style sheet must be named {CSS_FILE}.")
    report.note("Upload to the Electron server and the Brightspace zip cannot be verified here.")
    return report
