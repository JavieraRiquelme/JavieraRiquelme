#!/usr/bin/env python3
"""
Genera los assets del perfil:
  (cada imagen sale en dos versiones: -dark.svg y -light.svg)
  assets/planet.svg     -> planeta donde cada "pixel" es un día de contribuciones
  assets/neurons.svg    -> dos neuronas: repos públicos y privados como dendritas
  assets/languages.svg  -> burbujas con los lenguajes de tus repos (públicos + privados)
  README.md             -> reemplaza el bloque ASCII entre <!-- PLANET:START/END -->

Uso:
  GH_TOKEN=ghp_xxx python scripts/generate.py      # datos reales
  python scripts/generate.py --demo                # datos falsos para previsualizar

Variables opcionales:
  EXCLUDE_LANGS="HTML,Jupyter Notebook"   lenguajes que no quieres mostrar
  MAX_LANGS=10                            cuántas burbujas (el resto va a "otros")
"""
import datetime as dt
import json
import math
import os
import random
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
README = ROOT / "README.md"
API = "https://api.github.com/graphql"

# Paleta: rosa, lila y fucsia
C = {
    "void": "#0A0810",
    "space": "#110E19",
    "dim": "#3E3558",
    "lila": "#B0B1F9",      # very soft blue / lila
    "magenta": "#D8A0DF",   # very soft magenta
    "rosa": "#FE94C1",      # soft pink
    "fucsia": "#FF4FB3",
    "crema": "#FFEFF7",
    "naranja": "#FF8A3D",
    "ambar": "#FFB870",
    "violeta": "#8B4DFF",
    "indigo": "#170C2C",
}
THEMES = {
    "dark": {
        "C": {"void": "#0A0810", "space": "#110E19", "dim": "#3E3558", "lila": "#B0B1F9",
              "magenta": "#D8A0DF", "rosa": "#FE94C1", "fucsia": "#FF4FB3", "crema": "#FFEFF7",
              "naranja": "#FF8A3D", "ambar": "#FFB870", "violeta": "#8B4DFF", "indigo": "#170C2C",
              "rim": "#5A4A86", "hoy": "#FFEFF7", "outline": ""},
        "OCEAN": ["#181128", "#1F1733", "#291E42", "#352852", "#463564"],
        "LEVEL": ["", "#8F8BEA", "#D8A0DF", "#FE94C1", "#FF4FB3"],
        "LEVEL_DARK": ["", "#4B4787", "#7A5583", "#93526F", "#9A2C6A"],
    },
    "light": {
        "C": {"void": "#FBF6FA", "space": "#F3EAF3", "dim": "#D9CDE6", "lila": "#6E6CE0",
              "magenta": "#B35DBF", "rosa": "#E8559A", "fucsia": "#D6157F", "crema": "#2A1838",
              "naranja": "#E8661A", "ambar": "#D98A2B", "violeta": "#6B2FE0", "indigo": "#170C2C",
              "rim": "#FFFFFF", "hoy": "#2A1838", "outline": "#CFC2E3"},
        "OCEAN": ["#A596CB", "#B6A9D8", "#C8BDE5", "#D9D0EF", "#E9E3F7"],
        "LEVEL": ["", "#6E6CE0", "#B35DBF", "#E8559A", "#D6157F"],
        "LEVEL_DARK": ["", "#4B4787", "#7A3D85", "#A33A6C", "#8E0F55"],
    },
}


def apply_theme(name):
    """Cambia la paleta en su lugar; todas las funciones la leen al dibujar."""
    t = THEMES[name]
    C.clear(); C.update(t["C"])
    OCEAN[:] = t["OCEAN"]; LEVEL[:] = t["LEVEL"]; LEVEL_DARK[:] = t["LEVEL_DARK"]


MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"
SANS = "'Avenir Next', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"


# ───────────────────────────── datos ─────────────────────────────

def gql(query, variables=None):
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("Falta GH_TOKEN (o usa --demo).")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "planet-readme",
    })
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    if "errors" in data:
        sys.exit(json.dumps(data["errors"], indent=2))
    return data["data"]


LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}


def fetch_days():
    # viewer = el dueño del token, así se incluyen las contribuciones privadas
    q = """query { viewer { login contributionsCollection { contributionCalendar {
          totalContributions weeks { contributionDays { date contributionCount contributionLevel } } } } } }"""
    v = gql(q)["viewer"]
    cal = v["contributionsCollection"]["contributionCalendar"]
    days = [{"date": d["date"], "count": d["contributionCount"], "level": LEVELS[d["contributionLevel"]]}
            for w in cal["weeks"] for d in w["contributionDays"]]
    return v["login"], cal["totalContributions"], days


def fetch_languages():
    q = """query($after: String) { viewer { repositories(first: 100, after: $after,
          ownerAffiliations: OWNER, isFork: false) {
          pageInfo { hasNextPage endCursor }
          nodes { isPrivate primaryLanguage { name }
            defaultBranchRef { target { ... on Commit { history { totalCount } } } }
            languages(first: 25) { edges { size node { name } } } } } } }"""
    langs, after, repos = {}, None, {"public": 0, "private": 0, "list": []}
    while True:
        page = gql(q, {"after": after})["viewer"]["repositories"]
        for repo in page["nodes"]:
            kind = "private" if repo["isPrivate"] else "public"
            repos[kind] += 1
            ref = repo["defaultBranchRef"] or {}
            commits = ((ref.get("target") or {}).get("history") or {}).get("totalCount", 0)
            repos["list"].append({"private": repo["isPrivate"], "commits": commits,
                                  "lang": (repo["primaryLanguage"] or {}).get("name")})
            for e in repo["languages"]["edges"]:
                slot = langs.setdefault(e["node"]["name"], {"public": 0, "private": 0})
                slot[kind] += e["size"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return langs, repos


def demo_data():
    rnd = random.Random(7)
    today = dt.date.today()
    days, heat = [], 0.0
    for i in range(371):
        date = today - dt.timedelta(days=370 - i)
        heat = max(0.0, min(1.0, heat + rnd.uniform(-0.28, 0.3) + (0.05 if i > 300 else -0.01)))
        count = int(heat * rnd.uniform(0, 14)) if rnd.random() < 0.25 + heat * 0.6 else 0
        days.append({"date": date.isoformat(), "count": count})
    mx = max(d["count"] for d in days) or 1
    for d in days:
        d["level"] = 0 if d["count"] == 0 else min(4, 1 + int(4 * d["count"] / (mx + 1)))
    langs = {
        "TypeScript": {"public": 410_000, "private": 690_000},
        "Python": {"public": 300_000, "private": 380_000},
        "JavaScript": {"public": 210_000, "private": 120_000},
        "CSS": {"public": 90_000, "private": 140_000},
        "Swift": {"public": 0, "private": 160_000},
        "Go": {"public": 70_000, "private": 20_000},
        "Shell": {"public": 25_000, "private": 30_000},
        "Rust": {"public": 30_000, "private": 0},
        "SQL": {"public": 5_000, "private": 22_000},
    }
    names = list(langs)
    rlist = [{"private": i % 3 == 0, "commits": int(rnd.paretovariate(1.1) * 12),
              "lang": names[min(len(names) - 1, int(rnd.expovariate(.7)))]} for i in range(23)]
    return "tu-usuario", sum(d["count"] for d in days), days, langs, {"public": 15, "private": 8, "list": rlist}


# ──────────────────────────── geometría ────────────────────────────

def sphere_rows(n):
    """Filas de latitud con celdas ∝ cos(lat): cada día ocupa más o menos la misma área."""
    rows = 10
    while True:
        lats = [math.pi / 2 - (i + 0.5) * math.pi / rows for i in range(rows)]
        counts = [max(1, round(rows * math.cos(la))) for la in lats]
        if sum(counts) >= n:
            return lats, counts
        rows += 1


class Globe:
    """Un día = un bloque del disco. Hoy queda al centro y el año se enrolla en espiral hacia el borde."""

    def __init__(self, days, G=22):
        self.G = G
        cells = []
        for gy in range(G):
            for gx in range(G):
                u, v = (gx + .5) / G * 2 - 1, (gy + .5) / G * 2 - 1
                if u * u + v * v <= 1:
                    ring = round(math.hypot(gx + .5 - G / 2, gy + .5 - G / 2))
                    ang = (math.atan2(u, -v)) % (2 * math.pi)  # empieza arriba, sentido horario
                    cells.append(((ring, ang), (gx, gy)))
        cells.sort()
        recent_first = list(reversed(days[-len(cells):]))
        self.grid = {}
        for rank, (_, pos) in enumerate(cells):
            self.grid[pos] = recent_first[rank] if rank < len(recent_first) else None
        self.today = days[-1]

    def day_at(self, u, v):
        """u, v en [-1, 1] -> día del bloque (o None si es océano)."""
        gx = min(self.G - 1, max(0, int((u + 1) / 2 * self.G)))
        gy = min(self.G - 1, max(0, int((v + 1) / 2 * self.G)))
        return self.grid.get((gx, gy))


def streaks(days):
    cur = best = run = 0
    for d in days:
        run = run + 1 if d["count"] > 0 else 0
        best = max(best, run)
    for d in reversed(days):
        if d["count"] > 0:
            cur += 1
        elif d is days[-1]:
            continue  # hoy aún sin commits no corta la racha
        else:
            break
    return cur, best


# ───────────────────────────── planeta ─────────────────────────────

BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
OCEAN = ["#181128", "#1F1733", "#291E42", "#352852", "#463564"]        # de sombra a luz
LEVEL = ["", "#8F8BEA", "#D8A0DF", "#FE94C1", "#FF4FB3"]               # lila → fucsia
LEVEL_DARK = ["", "#4B4787", "#7A5583", "#93526F", "#9A2C6A"]
LIGHT = (-0.52, -0.58, 0.62)


def lighting(u, v):
    z = math.sqrt(max(0, 1 - u * u - v * v))
    n = math.sqrt(sum(c * c for c in LIGHT))
    return max(0.0, (u * LIGHT[0] + v * LIGHT[1] + z * LIGHT[2]) / n)


def render_planet(login, total, days, N=44, P=10):
    W, H = 900, 520
    cx, cy = 290, 260
    x0, y0 = cx - N * P / 2, cy - N * P / 2
    globe = Globe(days, G=N // 2)
    rnd = random.Random(42)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'shape-rendering="crispEdges" role="img" '
           f'aria-label="Planeta pixel con {total} contribuciones del último año">']
    out.append("""<style>
  .tw{animation:tw 3.2s steps(2) infinite}
  @keyframes tw{0%,100%{opacity:.25}50%{opacity:1}}
  .hoy{animation:hoy 1s steps(1) infinite}
  @keyframes hoy{0%{fill:HOY}50%{fill:FUCSIA}}
  @media (prefers-reduced-motion:reduce){.tw,.hoy{animation:none}}
</style>""".replace("HOY", C["hoy"]).replace("FUCSIA", C["fucsia"]))
    out.append(f'<rect width="{W}" height="{H}" rx="18" fill="{C["void"]}"/>')

    # estrellas pixel
    for _ in range(46):
        x = rnd.randrange(8, W - 8) // 4 * 4
        y = rnd.randrange(8, H - 8) // 4 * 4
        if math.hypot(x - cx, y - cy) < N * P / 2 + 50 or (560 < x < 880 and 50 < y < 480):
            continue
        col = rnd.choice([C["lila"], C["magenta"], C["rosa"], C["crema"]])
        d = f' style="animation-delay:{rnd.uniform(0, 3.2):.1f}s"'
        if rnd.random() < .22:   # destello en cruz
            out.append(f'<g class="tw"{d} fill="{col}"><rect x="{x}" y="{y - 4}" width="4" height="12"/>'
                       f'<rect x="{x - 4}" y="{y}" width="12" height="4"/></g>')
        else:
            out.append(f'<rect class="tw"{d} x="{x}" y="{y}" width="4" height="4" fill="{col}"/>')

    # anillo pixel (puntos sobre una elipse inclinada)
    ring_back, ring_front = [], []
    rx, ry, tilt = N * P * .66, N * P * .13, math.radians(-13)
    for i in range(110):
        t = 2 * math.pi * i / 110
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        x = cx + ex * math.cos(tilt) - ey * math.sin(tilt)
        y = cy + ex * math.sin(tilt) + ey * math.cos(tilt)
        gx, gy = round((x - x0) / P * 2) / 2, round((y - y0) / P * 2) / 2
        sq = (x0 + gx * P, y0 + gy * P)
        (ring_front if math.sin(t) > 0 else ring_back).append(sq)

    def ring(points, col, op):
        return "".join(f'<rect x="{x:.0f}" y="{y:.0f}" width="5" height="5" fill="{col}" opacity="{op}"/>'
                       for x, y in points)

    out.append(ring(ring_back, C["lila"], .45))

    # contorno (solo en el tema claro, para que el borde iluminado no se pierda)
    if C.get("outline"):
        for gy in range(-1, N + 1):
            for gx in range(-1, N + 1):
                u, v = (gx + .5) / (N / 2) - 1, (gy + .5) / (N / 2) - 1
                if 1 < math.hypot(u, v) <= 1 + 1.1 / (N / 2):
                    out.append(f'<rect x="{x0 + gx * P:.0f}" y="{y0 + gy * P:.0f}" width="{P}" height="{P}" '
                               f'fill="{C["outline"]}"/>')

    # el planeta, pixel por pixel
    today_px = []
    for gy in range(N):
        for gx in range(N):
            u, v = (gx + .5) / (N / 2) - 1, (gy + .5) / (N / 2) - 1
            if u * u + v * v > 1:
                continue
            day = globe.day_at(u, v)
            b = lighting(u, v)
            thr = (BAYER[gy % 4][gx % 4] + .5) / 16
            x, y = x0 + gx * P, y0 + gy * P
            if day is not None and day is globe.today:
                today_px.append((x, y))
                continue
            lvl = 0 if day is None else day["level"]
            rim = math.hypot(u, v) > 1 - 1.6 / (N / 2) and b > .42
            if lvl == 0:
                col = C["rim"] if rim else OCEAN[min(4, int(b * 4.2 + thr))]
            else:
                col = LEVEL[lvl] if b + (thr - .5) * .3 > .22 else LEVEL_DARK[lvl]
            tip = "" if day is None else f'<title>{day["date"]}: {day["count"]} contribuciones</title>'
            out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{P}" height="{P}" fill="{col}">{tip}</rect>')
    for x, y in today_px:
        out.append(f'<rect class="hoy" x="{x:.0f}" y="{y:.0f}" width="{P}" height="{P}" fill="{C["crema"]}">'
                   f'<title>hoy: {globe.today["count"]} contribuciones</title></rect>')

    out.append(ring(ring_front, C["rosa"], .9))

    # panel
    cur, best = streaks(days)
    busiest = max(days, key=lambda d: d["count"])
    active = sum(1 for d in days if d["count"])
    px = 590
    out.append(f'<g font-family="{MONO}" fill="{C["crema"]}">')
    out.append(f'<text x="{px}" y="92" font-size="15" fill="{C["magenta"]}">@{login}</text>')
    out.append(f'<text x="{px}" y="150" font-size="56" font-weight="700" letter-spacing="-2">{total}</text>')
    out.append(f'<text x="{px}" y="178" font-size="14" fill="{C["lila"]}">contribuciones este año</text>')
    stats = [(f"{cur}d", "racha actual"), (f"{best}d", "mejor racha"),
             (f"{active}", "días activos"), (f"{busiest['count']}", f"récord {busiest['date']}")]
    for i, (big, small) in enumerate(stats):
        y = 228 + i * 38
        out.append(f'<text x="{px}" y="{y}" font-size="18" font-weight="700" fill="{C["rosa"]}">{big}</text>')
        out.append(f'<text x="{px + 70}" y="{y}" font-size="13" opacity=".75">{small}</text>')
    ly = 418
    out.append(f'<text x="{px}" y="{ly}" font-size="12" opacity=".6">menos</text>')
    sw = [OCEAN[3]] + LEVEL[1:]
    for i, col in enumerate(sw):
        out.append(f'<rect x="{px + 52 + i * 18}" y="{ly - 11}" width="12" height="12" fill="{col}"/>')
    out.append(f'<text x="{px + 52 + 5 * 18 + 4}" y="{ly}" font-size="12" opacity=".6">más</text>')
    out.append(f'<text x="{px}" y="{ly + 32}" font-size="11.5" opacity=".45">cada bloque es un día.</text>')
    out.append(f'<text x="{px}" y="{ly + 50}" font-size="11.5" opacity=".45">hoy parpadea al centro.</text>')
    out.append("</g></svg>")
    return "\n".join(out)


# ───────────────────────────── burbujas ─────────────────────────────

def pack(radii, gap=7):
    placed = []
    for r in radii:
        if not placed:
            placed.append([0.0, 0.0, r])
            continue
        best = None
        for (x, y, R) in placed:
            for k in range(96):
                a = 2 * math.pi * k / 96
                px, py = x + (R + r + gap) * math.cos(a), y + (R + r + gap) * math.sin(a)
                if all(math.hypot(px - qx, py - qy) >= qr + r + gap - .01 for qx, qy, qr in placed):
                    score = px * px * .32 + py * py * 1.7
                    if best is None or score < best[0]:
                        best = (score, px, py)
        placed.append([best[1], best[2], r])
    return placed


FILL_KEYS = ["rosa", "naranja", "lila", "fucsia", "violeta", "ambar", "magenta", "crema"]


def ink_for(hexcol):
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return "#170C1F" if (.299 * r + .587 * g + .114 * b) > 140 else "#FFF7FB"


def language_colors(langs):
    ranked = sorted(langs, key=lambda k: -(langs[k]["public"] + langs[k]["private"]))
    return {name: C[FILL_KEYS[i % len(FILL_KEYS)]] for i, name in enumerate(ranked)}


def render_languages(langs, repos):
    colors = language_colors(langs)
    exclude = {s.strip().lower() for s in os.environ.get("EXCLUDE_LANGS", "").split(",") if s.strip()}
    max_n = int(os.environ.get("MAX_LANGS", "10"))
    items = [(k, v["public"] + v["private"], v["private"]) for k, v in langs.items() if k.lower() not in exclude]
    items = [i for i in items if i[1] > 0]
    items.sort(key=lambda i: -i[1])
    if len(items) > max_n:
        rest = items[max_n - 1:]
        items = items[:max_n - 1] + [("otros", sum(i[1] for i in rest), sum(i[2] for i in rest))]
    total = sum(i[1] for i in items) or 1

    W, H = 900, 400
    circles = pack([math.sqrt(i[1] / total) * 100 for i in items])

    # escalar al lienzo
    minx = min(x - r for x, y, r in circles); maxx = max(x + r for x, y, r in circles)
    miny = min(y - r for x, y, r in circles); maxy = max(y + r for x, y, r in circles)
    area_w, area_h, top = W - 80, H - 110, 70
    k = min(area_w / (maxx - minx), area_h / (maxy - miny))
    ox = 40 + (area_w - (maxx - minx) * k) / 2 - minx * k
    oy = top + (area_h - (maxy - miny) * k) / 2 - miny * k

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'role="img" aria-label="Lenguajes más usados">']
    out.append(f'<rect width="{W}" height="{H}" rx="18" fill="{C["void"]}"/>')
    out.append(f'<g font-family="{SANS}">')
    out.append(f'<text x="40" y="44" font-size="20" font-weight="700" fill="{C["crema"]}">lenguajes</text>')
    out.append(f'<text x="140" y="44" font-size="14" fill="{C["lila"]}">en {plural(repos["public"], "repo público", "repos públicos")} '
               f'y {plural(repos["private"], "privado", "privados")}</text>')
    out.append(f'<text x="{W - 40}" y="44" font-size="12" text-anchor="end" fill="{C["crema"]}" opacity=".5">'
               f'borde punteado = sobre todo privado</text>')

    for idx, ((name, size, priv), (x, y, r)) in enumerate(zip(items, circles)):
        X, Y, Rr = ox + x * k, oy + y * k, r * k
        fill = colors.get(name, C["lila"])
        pct = 100 * size / total
        mostly_private = priv / size > .5
        out.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="{Rr:.1f}" fill="{fill}"/>')
        if mostly_private:
            out.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="{Rr + 4:.1f}" fill="none" stroke="{fill}" '
                       f'stroke-width="1.3" stroke-dasharray="3 4"/>')
        ink = ink_for(fill)
        fs = max(10, min(24, Rr / 3.6))
        label = name if Rr > len(name) * fs * .32 else name[:3]
        if Rr > 26:
            out.append(f'<text x="{X:.1f}" y="{Y + fs * .1:.1f}" font-size="{fs:.1f}" font-weight="700" '
                       f'text-anchor="middle" fill="{ink}">{label}</text>')
            out.append(f'<text x="{X:.1f}" y="{Y + fs * 1.15:.1f}" font-size="{max(9.5, fs * .62):.1f}" '
                       f'text-anchor="middle" fill="{ink}" opacity=".7">{pct:.1f}%</text>')
        elif Rr > 16:
            out.append(f'<text x="{X:.1f}" y="{Y + 4:.1f}" font-size="10" font-weight="700" '
                       f'text-anchor="middle" fill="{ink}"><title>{name} {pct:.1f}%</title>{label}</text>')
    out.append("</g></svg>")
    return "\n".join(out)


# ───────────────────────────── neuronas ─────────────────────────────

def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def render_neurons(langs, repos):
    """Dos neuronas: repos públicos a la izquierda, privados a la derecha.
    Cada dendrita es un repo, su color es el lenguaje principal y cada punta son ~commits."""
    W, H = 900, 470
    colors = language_colors(langs)
    rnd = random.Random(11)
    lst = repos.get("list", [])
    total_commits = sum(max(1, r["commits"]) for r in lst) or 1
    scale = min(1.0, 520 / total_commits)

    paths, dots = [], []
    group_key = [False]

    def grow(x, y, ang, length, leaves, depth, col, width):
        bend = rnd.uniform(-.45, .45)
        ex, ey = x + length * math.cos(ang), y + length * math.sin(ang)
        qx = x + length * .5 * math.cos(ang + bend)
        qy = y + length * .5 * math.sin(ang + bend)
        paths.append((group_key[0], (x, y, qx, qy, ex, ey), col, width, depth))
        if leaves <= 1 or depth > 9:
            dots.append((group_key[0], ex, ey, col, rnd.uniform(1.6, 3.2)))
            return
        k = 2 if leaves < 6 or rnd.random() < .6 else 3
        cuts = sorted(rnd.sample(range(1, leaves), min(k - 1, leaves - 1)))
        parts = [b - a for a, b in zip([0] + cuts, cuts + [leaves])]
        spread = rnd.uniform(.35, .75)
        for i, n in enumerate(parts):
            off = (i - (len(parts) - 1) / 2) * spread / max(1, len(parts) - 1) * 2
            grow(ex, ey, ang + off + rnd.uniform(-.12, .12), length * rnd.uniform(.68, .86),
                 n, depth + 1, col, max(.5, width * .72))

    somas = {False: (250, 240), True: (660, 240)}
    for private in (False, True):
        group = [r for r in lst if r["private"] == private]
        if not group:
            continue
        sx, sy = somas[private]
        group_key[0] = private
        weights = [math.sqrt(max(1, r["commits"])) for r in group]
        tw = sum(weights)
        # los públicos se abren hacia la izquierda, los privados hacia la derecha
        base = math.pi if not private else 0.0
        arc = math.radians(300)
        a = base - arc / 2
        splits = max(1, math.ceil(8 / len(group)))  # con pocos repos, cada uno se abre en varias ramas
        for r, wgt in sorted(zip(group, weights), key=lambda t: rnd.random()):
            leaves = min(70, max(2, round(max(1, r["commits"]) * scale)))
            col = colors.get(r["lang"], C["lila"])
            for part in range(splits):
                share = arc * wgt / tw / splits
                ang = a + share / 2
                a += share
                n = max(2, leaves // splits)
                grow(sx + 10 * math.cos(ang), sy + 10 * math.sin(ang), ang,
                     rnd.uniform(34, 52) + math.log1p(n) * 6, n, 0, col, 2.4)

    fit = {}
    for private, (sx, sy) in somas.items():
        pts = [(p[1][4], p[1][5]) for p in paths if p[0] == private] + \
              [(p[1][2], p[1][3]) for p in paths if p[0] == private]
        if pts:
            mdx = max(abs(x - sx) for x, _ in pts) or 1
            mdy = max(abs(y - sy) for _, y in pts) or 1
            fit[private] = min(1.6, 195 / mdx, 165 / mdy)

    def T(private, x, y):
        sx, sy = somas[private]
        k = fit[private]
        return sx + (x - sx) * k, sy + (y - sy) * k

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'role="img" aria-label="Neuronas de repos públicos y privados">']
    out.append("""<style>
  .d{stroke-dasharray:1;stroke-dashoffset:1;animation:grow 2.6s cubic-bezier(.2,.7,.2,1) forwards}
  .p{opacity:0;animation:pop .6s ease-out forwards}
  @keyframes grow{to{stroke-dashoffset:0}}
  @keyframes pop{to{opacity:1}}
  @media (prefers-reduced-motion:reduce){.d{animation:none;stroke-dashoffset:0}.p{animation:none;opacity:1}}
</style>""")
    out.append(f"""<defs>
  <radialGradient id="soma" cx="38%" cy="35%" r="70%">
    <stop offset="0" stop-color="#3A1C6E"/><stop offset=".7" stop-color="{C['indigo']}"/>
    <stop offset="1" stop-color="#0B0616"/></radialGradient>
  <filter id="halo" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="9"/></filter>
</defs>""")
    out.append(f'<rect width="{W}" height="{H}" rx="18" fill="{C["void"]}"/>')
    # axón entre las dos neuronas
    if any(not r["private"] for r in lst) and any(r["private"] for r in lst):
        for i in range(7):
            o = (i - 3) * 2.2
            col = [C["violeta"], C["naranja"], C["rosa"]][i % 3]
            out.append(f'<path class="d" pathLength="1" d="M250 {240 + o}C390 {195 + o * 3} 520 {285 - o * 3} 660 {240 - o}" '
                       f'fill="none" stroke="{col}" stroke-width=".9" opacity=".55"/>')
    out.append('<g fill="none" stroke-linecap="round">')
    for private, (x, y, qx, qy, ex, ey), col, wdt, depth in paths:
        x, y = T(private, x, y); qx, qy = T(private, qx, qy); ex, ey = T(private, ex, ey)
        d = f"M{x:.1f} {y:.1f}Q{qx:.1f} {qy:.1f} {ex:.1f} {ey:.1f}"
        delay = depth * .16
        out.append(f'<path class="d" pathLength="1" style="animation-delay:{delay:.2f}s" d="{d}" '
                   f'stroke="{col}" stroke-width="{wdt:.2f}" opacity="{max(.35, .85 - depth * .05):.2f}"/>')
    out.append("</g>")
    for private, x, y, col, r in dots:
        x, y = T(private, x, y)
        out.append(f'<circle class="p" style="animation-delay:{1.6 + rnd.uniform(0, .9):.2f}s" '
                   f'cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{col}"/>')
    for private, (sx, sy) in somas.items():
        if any(r["private"] == private for r in lst):
            out.append(f'<circle cx="{sx}" cy="{sy}" r="24" fill="{C["violeta"]}" opacity=".55" filter="url(#halo)"/>'
                       f'<circle cx="{sx}" cy="{sy}" r="17" fill="url(#soma)" stroke="{C["violeta"]}" stroke-width="2"/>'
                       f'<circle cx="{sx - 5}" cy="{sy - 6}" r="3" fill="{C["ambar"]}" opacity=".9"/>')

    pub = [r for r in lst if not r["private"]]
    prv = [r for r in lst if r["private"]]
    out.append(f'<g font-family="{SANS}" fill="{C["crema"]}">')
    out.append(f'<text x="40" y="44" font-size="20" font-weight="700">repos</text>')
    out.append(f'<text x="40" y="{H - 30}" font-size="13" fill="{C["lila"]}">públicos: {plural(len(pub), "repo", "repos")}, '
               f'{plural(sum(r["commits"] for r in pub), "commit", "commits")}</text>')
    out.append(f'<text x="{W - 40}" y="{H - 30}" font-size="13" text-anchor="end" fill="{C["rosa"]}">'
               f'privados: {plural(len(prv), "repo", "repos")}, '
               f'{plural(sum(r["commits"] for r in prv), "commit", "commits")}</text>')
    out.append(f'<text x="{W - 40}" y="44" font-size="12" text-anchor="end" opacity=".5">'
               f'cada rama es un repo, el color es su lenguaje</text>')
    out.append("</g></svg>")
    return "\n".join(out)


# ─────────────────────────── planeta ASCII ───────────────────────────

def render_ascii(days, cols=52, rows=24):
    globe = Globe(days)
    shade = ".:"           # océano: sombra / luz
    chars = " +oO@"        # niveles de actividad
    lines = []
    for r in range(rows):
        v = (r + .5) / rows * 2 - 1
        line = ""
        for c in range(cols):
            u = (c + .5) / cols * 2 - 1
            if u * u + v * v > 1:
                line += " "
                continue
            day = globe.day_at(u, v)
            if day is globe.today:
                line += "*"
            elif day is None or day["level"] == 0:
                line += shade[min(1, int(lighting(u, v) * 2.4))]
            else:
                line += chars[day["level"]]
        lines.append(line.rstrip())
    return "\n".join(lines)


def inject_readme(ascii_art, total):
    if not README.exists():
        return
    text = README.read_text(encoding="utf-8")
    block = (f"<!-- PLANET:START -->\n```text\n{ascii_art}\n\n"
             f"  .: nada   + poco   o algo   O harto   @ a full   * hoy      {total} contribuciones\n```\n"
             f"<!-- PLANET:END -->")
    new = re.sub(r"<!-- PLANET:START -->.*?<!-- PLANET:END -->", block, text, flags=re.S)
    README.write_text(new, encoding="utf-8")


# ─────────────────────────────── main ───────────────────────────────

def main():
    if "--demo" in sys.argv:
        login, total, days, langs, repos = demo_data()
    else:
        login, total, days = fetch_days()
        langs, repos = fetch_languages()
    ASSETS.mkdir(exist_ok=True)
    for theme in THEMES:   # planet-dark.svg, planet-light.svg, etc.
        apply_theme(theme)
        (ASSETS / f"planet-{theme}.svg").write_text(render_planet(login, total, days), encoding="utf-8")
        (ASSETS / f"neurons-{theme}.svg").write_text(render_neurons(langs, repos), encoding="utf-8")
        (ASSETS / f"languages-{theme}.svg").write_text(render_languages(langs, repos), encoding="utf-8")
    inject_readme(render_ascii(days), total)
    print(f"listo: {total} contribuciones, {len(langs)} lenguajes")


if __name__ == "__main__":
    main()
