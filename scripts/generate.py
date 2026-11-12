#!/usr/bin/env python3
"""
Genera los assets del perfil:
  assets/planet.svg     -> planeta donde cada "pixel" es un día de contribuciones
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
}
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
          nodes { isPrivate languages(first: 25) { edges { size node { name } } } } } } }"""
    langs, after, repos = {}, None, {"public": 0, "private": 0}
    while True:
        page = gql(q, {"after": after})["viewer"]["repositories"]
        for repo in page["nodes"]:
            kind = "private" if repo["isPrivate"] else "public"
            repos[kind] += 1
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
    return "tu-usuario", sum(d["count"] for d in days), days, langs, {"public": 14, "private": 9}


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
  @keyframes hoy{0%{fill:#FFEFF7}50%{fill:#FF4FB3}}
  @media (prefers-reduced-motion:reduce){.tw,.hoy{animation:none}}
</style>""")
    out.append(f'<rect width="{W}" height="{H}" fill="{C["void"]}"/>')

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
                col = "#5A4A86" if rim else OCEAN[min(4, int(b * 4.2 + thr))]
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


def render_languages(langs, repos):
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
    fills = [C["rosa"], C["magenta"], C["lila"], C["fucsia"], C["crema"]]
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
    out.append(f'<text x="140" y="44" font-size="14" fill="{C["lila"]}">en {repos["public"]} repos públicos '
               f'y {repos["private"]} privados</text>')
    out.append(f'<text x="{W - 40}" y="44" font-size="12" text-anchor="end" fill="{C["crema"]}" opacity=".5">'
               f'borde punteado = sobre todo privado</text>')

    for idx, ((name, size, priv), (x, y, r)) in enumerate(zip(items, circles)):
        X, Y, Rr = ox + x * k, oy + y * k, r * k
        fill = fills[idx % len(fills)]
        pct = 100 * size / total
        mostly_private = priv / size > .5
        out.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="{Rr:.1f}" fill="{fill}"/>')
        if mostly_private:
            out.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="{Rr + 4:.1f}" fill="none" stroke="{fill}" '
                       f'stroke-width="1.3" stroke-dasharray="3 4"/>')
        ink = C["void"]
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
    (ASSETS / "planet.svg").write_text(render_planet(login, total, days), encoding="utf-8")
    (ASSETS / "languages.svg").write_text(render_languages(langs, repos), encoding="utf-8")
    inject_readme(render_ascii(days), total)
    print(f"listo: {total} contribuciones, {len(langs)} lenguajes")


if __name__ == "__main__":
    main()
