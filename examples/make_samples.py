"""Generate three sample Assignment 5 submissions (strong / partial / weak)
plus a class zip, for testing the checker and for the demo.

    python examples/make_samples.py
"""
from __future__ import annotations

import os
import random
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
OUT = HERE / "submissions"


def img(path: Path, w: int, h: int, color, label: str = "", noise: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if noise:
        rnd = random.Random(7)
        im = Image.frombytes("RGB", (w, h), bytes(rnd.getrandbits(8) for _ in range(w * h * 3)))
    else:
        im = Image.new("RGB", (w, h), color)
        d = ImageDraw.Draw(im)
        d.rectangle([4, 4, w - 5, h - 5], outline=(255, 255, 255), width=3)
        if label:
            d.text((10, h // 2 - 6), label, fill=(255, 255, 255))
    im.save(path, optimize=True)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.lstrip("\n"), encoding="utf-8")


# --------------------------------------------------------------------------
# 1) Strong submission
# --------------------------------------------------------------------------
NAV = """
    <!-- Site navigation: icon + text links on every page -->
    <nav class="menu">
      <a href="mybio.html"><img src="images/home.png" alt="House icon for the About Me page" width="24" height="24" /> About Me</a>
      <a href="education.html"><img src="images/book.png" alt="Book icon for the Education page" width="24" height="24" /> Education</a>
      <a href="work.html"><img src="images/briefcase.png" alt="Briefcase icon for the Work page" width="24" height="24" /> Work</a>
      <a href="hobbies.html"><img src="images/star.png" alt="Star icon for the Hobbies page" width="24" height="24" /> Hobbies</a>
    </nav>
"""


def page(title: str, body: str, extra_head: str = "") -> str:
    return f"""
<!DOCTYPE html>
<!-- Author: Alex Rivera | COMP2057 Assignment 5 | {title} -->
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{title} | Alex Rivera</title>
    <link rel="stylesheet" href="mycss.css" />{extra_head}
  </head>
  <body>
{NAV}
    <hr />
{body}
    <hr />
    <!-- Footer -->
    <footer>
      <p class="small">&copy; 2026 Alex Rivera. Built by hand with a text editor.</p>
    </footer>
  </body>
</html>
"""


def strong(root: Path) -> None:
    for name, color in [("home", (40, 90, 160)), ("book", (160, 90, 40)),
                        ("briefcase", (60, 120, 60)), ("star", (180, 150, 20))]:
        img(root / "images" / f"{name}.png", 24, 24, color)
    img(root / "images" / "portrait.png", 200, 200, (90, 90, 140), "Alex")
    img(root / "images" / "hiking.png", 320, 200, (50, 120, 80), "Hiking")
    img(root / "images" / "guitar.png", 320, 200, (140, 70, 50), "Guitar")
    img(root / "images" / "worldmap.png", 400, 200, (30, 80, 140), "Map")

    write(root / "mybio.html", page("About Me", """
    <!-- Main introduction -->
    <h1>Hi, I am Alex Rivera</h1>
    <img src="images/portrait.png" alt="Portrait of Alex smiling in front of a bookshelf" width="200" height="200" />
    <p>
      I am a second-year computer science student at the University of Windsor who loves
      turning messy problems into <strong>simple, friendly software</strong>. Over the last two
      years I have built small web sites for a local bakery and a student club, and each project
      taught me that clear communication matters as much as clean code. I enjoy working in teams,
      asking good questions and explaining technical ideas in plain language. This portfolio shows
      what I have learned so far, the work I am proud of, and the things that keep me curious
      outside of the classroom.<br />
      Thank you for taking the time to visit, and <em>please explore the pages above</em>.
    </p>
    <h2>What I am looking for</h2>
    <p>
      I am looking for a summer internship where I can help build accessible web applications.
      I learn quickly, I take feedback seriously, and I like to leave every project a little better
      documented than I found it. If you have a team that values careful work and kindness,
      I would be glad to hear from you through the feedback form on my education page.
    </p>
"""))

    write(root / "education.html", page("Education", """
    <!-- Education history -->
    <h1 style="color: #2b4c7e; text-align: center;">Education</h1>
    <p>
      I am currently enrolled in the <b>Bachelor of Computer Science</b> program at the University
      of Windsor. My favourite courses so far have been Introduction to the Internet, where I learned
      how browsers, servers and markup work together, and Data Structures, which changed the way I
      think about organising information. Before university I completed my high school diploma with
      honours, and I spent two summers volunteering as a math tutor at the public library. Teaching
      younger students showed me how important patience and clear examples are when you are
      learning something new for the first time.
    </p>
    <h2 class="highlight">Courses I enjoyed</h2>
    <p>Introduction to the Internet, Data Structures, Discrete Mathematics and Technical Writing.</p>

    <!-- Feedback form -->
    <h2>Send me feedback</h2>
    <form action="mailto:alex@example.com" method="post">
      <label for="name">Name:</label>
      <input type="text" id="name" name="name" /><br />
      <label for="email">Email:</label>
      <input type="email" id="email" name="email" /><br />
      <label for="comments">Comments:</label><br />
      <textarea id="comments" name="comments" rows="4" cols="40"></textarea><br />
      <input type="submit" value="Send" />
    </form>
""", extra_head="""
    <!-- Embedded style sheet for this page only -->
    <style>
      .highlight { color: #8a3b12; font-style: italic; }
      form { background-color: #f3f6fb; padding: 12px; width: 420px; }
    </style>"""))

    write(root / "work.html", page("Work Experience", """
    <!-- Work experience -->
    <h1>Work Experience</h1>
    <p>
      My work experience mixes part-time jobs and class projects. Each one taught me something
      different about responsibility, teamwork and building things that real people use. At the
      campus bookstore I learned to stay calm and friendly during the busy first week of every
      term. In my programming courses I worked with classmates to plan, design and test small
      applications, sharing the work fairly and meeting every deadline. The table below summarises
      the roles I have held and the most important skill I developed in each of them.
    </p>
    <table class="jobs">
      <caption>Roles and projects</caption>
      <tr>
        <th>Year</th>
        <th>Role</th>
        <th>Skill developed</th>
      </tr>
      <tr>
        <td>2025</td>
        <td>Bookstore cashier</td>
        <td>Customer service</td>
      </tr>
      <tr>
        <td>2025</td>
        <td>Club web site (class project)</td>
        <td>HTML and CSS layout</td>
      </tr>
      <tr>
        <td>2026</td>
        <td>Bakery menu site (volunteer)</td>
        <td>Working with a client</td>
      </tr>
    </table>
"""))

    write(root / "hobbies.html", page("Hobbies", """
    <!-- Things I like -->
    <h1>Things I Like</h1>
    <p>
      When I am not studying, I try to spend as much time outside as I can. Hiking along the
      Detroit River and in Point Pelee National Park helps me clear my head after a long week.
      I have also been teaching myself to play the guitar for about three years, mostly folk songs
      and the occasional rock classic. Travel is my other big passion: I keep a list of places I
      would love to visit, and the map below shows a few of them. Click a region on the map to read
      a short note about why I want to go there someday.
    </p>
    <img src="images/hiking.png" alt="Trail through green trees at Point Pelee National Park" width="320" height="200" />
    <img src="images/guitar.png" alt="My acoustic guitar leaning against a wooden chair" width="320" height="200" />
    <h2>Places I want to visit</h2>
    <img src="images/worldmap.png" alt="World map with Japan, Peru and Iceland marked" width="400" height="200" usemap="#travel" />
    <map name="travel">
      <area shape="rect" coords="0,0,130,200" href="https://en.wikipedia.org/wiki/Peru" alt="Peru" />
      <area shape="rect" coords="131,0,260,200" href="https://en.wikipedia.org/wiki/Iceland" alt="Iceland" />
      <area shape="circle" coords="330,100,60" href="https://en.wikipedia.org/wiki/Japan" alt="Japan" />
    </map>
"""))

    write(root / "mycss.css", """
/* mycss.css - shared styles for Alex Rivera's portfolio */
body {
  font-family: Georgia, "Times New Roman", serif;
  margin: 0 auto;
  max-width: 900px;
  color: #222;
  background-color: #fdfcf8;
}

/* Navigation menu */
.menu a {
  display: inline-block;
  padding: 6px 12px;
  color: #2b4c7e;
  text-decoration: none;
}
.menu a:hover {
  background-color: #e3ebf7;
}

/* Work table */
table.jobs {
  border-collapse: collapse;
  width: 100%;
}
table.jobs th,
table.jobs td {
  border: 1px solid #999;
  padding: 8px;
  text-align: left;
}
table.jobs th {
  background-color: #2b4c7e;
  color: white;
}

.small {
  font-size: 0.8em;
}
""")


# --------------------------------------------------------------------------
# 2) Partial submission: misnamed file, no form, missing alts, a broken link,
#    an unclosed tag, a huge image, short pages and a few typos.
# --------------------------------------------------------------------------
def partial(root: Path) -> None:
    img(root / "pic1.png", 300, 200, (120, 60, 60))
    img(root / "pic2.png", 300, 200, (60, 120, 60))
    img(root / "bigphoto.png", 900, 700, (0, 0, 0), noise=True)

    nav = """<p><a href="MyBio.html">Home</a> | <a href="education.html">Education</a> | <a href="work.html">Work</a> | <a href="hobbys.html">Hobbies</a></p>"""
    write(root / "MyBio.html", f"""
<!DOCTYPE html>
<html>
<head>
<title>Jordan's Bio</title>
<link rel="stylesheet" href="mycss.css">
</head>
<body>
{nav}
<h1>About Jordan</h1>
<p>Hi my name is jordan and i am a student at the university of windsor. I like computers and video
games and i want to be a software developer one day. I have been programing since high school when
I took my first computer class and I realy enjoyed it. My goal is to get a job at a big tech company
and work on interesting problems with smart people, and maybe start my own company someday.</p>
<img src="bigphoto.png">
<p>Thanks for visiting <b>my site</b>.
</body>
</html>
""")
    write(root / "education.html", f"""
<!DOCTYPE html>
<html>
<head>
<title>Education</title>
<link rel="stylesheet" href="mycss.css">
<style>
h1 {{ color: green; }}
</style>
</head>
<body>
{nav}
<h1>Education</h1>
<p style="font-size:14px">I go to the University of Windsor for computer science.</p>
<hr>
<div>
<p>I graduated from high school in 2024.</p>
</body>
</html>
""")
    write(root / "work.html", f"""
<!DOCTYPE html>
<html>
<head>
<title>Work</title>
<link rel="stylesheet" href="mycss.css">
</head>
<body>
{nav}
<h1>Work Experience</h1>
<p>I have worked at a grocery store for two years where I stocked shelves and helped customers find
what they needed. It taught me to be on time, to work hard and to be polite even when customers are
in a bad mood. I also did some group projects in my classes where we made small programs together,
which was fun but sometimes difficult because everyone had different schedules and ideas.</p>
<table border="1">
<tr><th>Job</th><th>Years</th></tr>
<tr><td>Grocery clerk</td><td>2</td></tr>
</table>
</body>
</html>
""")
    write(root / "hobbies.html", f"""
<!DOCTYPE html>
<html>
<head>
<title>Hobbies</title>
<link rel="stylesheet" href="mycss.css">
</head>
<body>
{nav}
<h1>Hobbies</h1>
<p>I like gaming, basketball and cooking.</p>
<img src="pic1.png" alt="pic1">
<img src="pic2.png" alt="Me playing basketball at the park">
<i>More coming soon</i>
</body>
</html>
""")
    write(root / "mycss.css", """
body { font-family: Arial; background-color: #eef; }
h1 { color: navy }
td { padding: 4px; }
""")


# --------------------------------------------------------------------------
# 3) Weak submission: one page, no doctype, flush-left, wrong css name.
# --------------------------------------------------------------------------
def weak(root: Path) -> None:
    write(root / "mybio.html", """
<html>
<head>
<title>my page</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<h1>Sam</h1>
<p>this is my website. i like sports.</p>
<a href="education.html">Education</a>
<a href="work.html">Work</a>
</body>
</html>
""")
    write(root / "style.css", "body { color: red; }\n")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    strong(OUT / "alex_rivera")
    partial(OUT / "jordan_lee")
    weak(OUT / "sam_patel")
    # A class zip like an LMS export: one zip per student inside one folder.
    zpath = HERE / "class_submissions.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for student in sorted(OUT.iterdir()):
            for f in sorted(student.rglob("*")):
                if f.is_file():
                    z.write(f, f"Assignment5/{student.name}/{f.relative_to(student).as_posix()}")
    print("wrote", OUT, "and", zpath, f"({os.path.getsize(zpath)//1024} KB)")


if __name__ == "__main__":
    main()
