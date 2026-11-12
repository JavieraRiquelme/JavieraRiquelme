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
    """Filas de latitud con celdas ∝ cos(lat): mismo espaciado sobre la esfera."""
    rows = 10
    while True:
        lats = [math.pi / 2 - (i + 0.5) * math.pi / rows for i in range(rows)]
        counts = [max(1, round(rows * math.cos(la))) for la in lats]
        if sum(counts) >= n:
            return lats, counts
        rows += 1


def sphere_cells(n):
    lats, counts = sphere_rows(n)
    cells = []
    for r, (la, k) in enumerate(zip(lats, counts)):
        for j in range(k):
            lo = -math.pi / 2 + (j + 0.5) * math.pi / k
            cells.append({"row": r, "lat": la, "lon": lo,
                          "x": math.cos(la) * math.sin(lo), "y": -math.sin(la)})
    return cells, lats, counts


def assign(days, n_cells):
    """Último día al final; las celdas sobrantes del inicio quedan como 'vacío'."""
    days = days[-n_cells:]
    return [None] * (n_cells - len(days)) + days


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

GLYPHS = f"""
  <g id="g0"><path d="M0-4.6Q0 0 4.6 0Q0 0 0 4.6Q0 0-4.6 0Q0 0 0-4.6Z" fill="{C['dim']}"/></g>
  <g id="g1"><circle r="7.2" fill="none" stroke="{C['lila']}" stroke-width="1.6"/></g>
  <g id="g2"><rect x="-8" y="-8" width="16" height="16" fill="{C['magenta']}" opacity=".72"/>
    <path d="M-4-8V8M0-8V8M4-8V8" stroke="{C['void']}" stroke-width="1.1" opacity=".45"/></g>
  <g id="g3"><rect x="-2.3" y="-8" width="4.6" height="16" fill="{C['rosa']}"/>
    <rect x="-8" y="-2.3" width="16" height="4.6" fill="{C['rosa']}"/></g>
  <g id="g4"><circle r="8.6" fill="{C['fucsia']}"/>
    <path d="M-3.6-3.6L3.6 3.6M3.6-3.6L-3.6 3.6" stroke="{C['crema']}" stroke-width="2" stroke-linecap="round"/></g>
"""


def render_planet(login, total, days):
    W, H = 900, 520
    cx, cy, R = 300, 262, 205
    cells, lats, _ = sphere_cells(len(days))
    data = assign(days, len(cells))
    rnd = random.Random(42)
    s = .84 * R * math.pi / len(lats) / 18  # tamaño del glifo según el espaciado

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
           f'aria-label="Planeta con {total} contribuciones del último año">']
    out.append(f"""<defs>{GLYPHS}
  <radialGradient id="shade" cx="34%" cy="30%" r="78%">
    <stop offset="0" stop-color="#000" stop-opacity="0"/>
    <stop offset=".55" stop-color="#000" stop-opacity=".12"/>
    <stop offset="1" stop-color="#000" stop-opacity=".78"/>
  </radialGradient>
  <radialGradient id="ocean" cx="40%" cy="36%" r="70%">
    <stop offset="0" stop-color="#1E1830"/><stop offset="1" stop-color="{C['void']}"/>
  </radialGradient>
  <filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="14"/></filter>
  <clipPath id="disk"><circle cx="{cx}" cy="{cy}" r="{R + 6}"/></clipPath>
  <style>
    .tw{{animation:tw 4s ease-in-out infinite}}
    @keyframes tw{{0%,100%{{opacity:.15}}50%{{opacity:.9}}}}
    .pulse{{animation:pulse 2.4s ease-out infinite;transform-box:fill-box;transform-origin:center}}
    @keyframes pulse{{0%{{transform:scale(.6);opacity:.95}}100%{{transform:scale(2.2);opacity:0}}}}
    @media (prefers-reduced-motion:reduce){{.tw,.pulse{{animation:none}}}}
  </style>
</defs>""")
    out.append(f'<rect width="{W}" height="{H}" rx="18" fill="{C["void"]}"/>')

    # estrellas de fondo
    for _ in range(70):
        x, y = rnd.uniform(10, W - 10), rnd.uniform(10, H - 10)
        if math.hypot(x - cx, y - cy) < R + 30 or (575 < x < 870 and 60 < y < 470):
            continue
        col = rnd.choice([C["lila"], C["magenta"], C["rosa"], C["crema"]])
        delay = rnd.uniform(0, 4)
        out.append(f'<circle class="tw" style="animation-delay:{delay:.2f}s" cx="{x:.1f}" cy="{y:.1f}" '
                   f'r="{rnd.uniform(.6, 1.6):.2f}" fill="{col}"/>')

    # anillo: mitad trasera
    ring = f'transform="translate({cx} {cy}) rotate(-14)"'
    out.append(f'<g {ring}><path d="M-268 0A268 54 0 0 1 268 0" fill="none" stroke="{C["lila"]}" '
               f'stroke-width="1.6" stroke-linecap="round" stroke-dasharray=".1 7" opacity=".5"/></g>')

    # atmósfera + disco
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{R + 4}" fill="{C["magenta"]}" opacity=".28" filter="url(#glow)"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{R + 6}" fill="url(#ocean)"/>')

    # celdas = días
    today_xy = None
    out.append('<g clip-path="url(#disk)">')
    for cell, day in zip(cells, data):
        x, y = cx + cell["x"] * R, cy + cell["y"] * R
        sx = max(.28, math.cos(cell["lon"]))
        sy = max(.45, math.cos(cell["lat"]) ** .35)
        lvl = 0 if day is None else day["level"]
        op = ' opacity=".35"' if day is None else ""
        title = "" if day is None else f'<title>{day["date"]}: {day["count"]} contribuciones</title>'
        out.append(f'<use href="#g{lvl}" xlink:href="#g{lvl}" '
                   f'transform="translate({x:.1f} {y:.1f}) scale({sx * s:.2f} {sy * s:.2f})"{op}>{title}</use>')
        if day is data[-1]:
            today_xy = (x, y)
    out.append("</g>")

    # luz y borde
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{R + 6}" fill="url(#shade)"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{R + 6}" fill="none" stroke="{C["magenta"]}" stroke-opacity=".35"/>')

    if today_xy:
        tx, ty = today_xy
        out.append(f'<circle class="pulse" cx="{tx:.1f}" cy="{ty:.1f}" r="9" fill="none" '
                   f'stroke="{C["crema"]}" stroke-width="1.5"/>')

    # anillo: mitad delantera
    out.append(f'<g {ring}><path d="M-268 0A268 54 0 0 0 268 0" fill="none" stroke="{C["rosa"]}" '
               f'stroke-width="2.2" stroke-linecap="round" stroke-dasharray=".1 7" opacity=".95"/></g>')

    # panel de texto
    cur, best = streaks(days)
    busiest = max(days, key=lambda d: d["count"])
    active = sum(1 for d in days if d["count"])
    px = 600
    out.append(f'<g font-family="{SANS}" fill="{C["crema"]}">')
    out.append(f'<text x="{px}" y="92" font-size="15" fill="{C["magenta"]}" font-family="{MONO}">@{login}</text>')
    out.append(f'<text x="{px}" y="150" font-size="54" font-weight="700" letter-spacing="-1.5">{total}</text>')
    out.append(f'<text x="{px}" y="178" font-size="15" fill="{C["lila"]}">contribuciones en el último año</text>')
    stats = [(f"{cur} días", "racha actual"), (f"{best} días", "mejor racha"),
             (f"{active}", "días con actividad"), (f"{busiest['count']}", f"récord, el {busiest['date']}")]
    for i, (big, small) in enumerate(stats):
        y = 230 + i * 40
        out.append(f'<text x="{px}" y="{y}" font-size="19" font-weight="600" fill="{C["rosa"]}">{big}</text>')
        out.append(f'<text x="{px + 92}" y="{y}" font-size="14" fill="{C["crema"]}" opacity=".75">{small}</text>')

    # leyenda
    ly = 420
    out.append(f'<text x="{px}" y="{ly}" font-size="12.5" opacity=".6">menos</text>')
    for i in range(5):
        out.append(f'<use href="#g{i}" xlink:href="#g{i}" transform="translate({px + 62 + i * 26} {ly - 4.5}) scale(.8)"/>')
    out.append(f'<text x="{px + 62 + 5 * 26}" y="{ly}" font-size="12.5" opacity=".6">más</text>')
    out.append(f'<text x="{px}" y="{ly + 34}" font-size="12" opacity=".45">cada pixel es un día · el pulso es hoy</text>')
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
        else:
            out.append(f'<text x="{X:.1f}" y="{Y + 4:.1f}" font-size="10" font-weight="700" '
                       f'text-anchor="middle" fill="{ink}"><title>{name} {pct:.1f}%</title>{label}</text>')
    out.append("</g></svg>")
    return "\n".join(out)


# ─────────────────────────── planeta ASCII ───────────────────────────

def render_ascii(days, cols=52, rows=24):
    cells, lats, counts = sphere_cells(len(days))
    data = assign(days, len(cells))
    starts, acc = [], 0
    for c in counts:
        starts.append(acc); acc += c
    chars = "·:oO@"  # ancho fijo en cualquier fuente monoespaciada
    lines = []
    for r in range(rows):
        y = (r + .5) / rows * 2 - 1
        line = ""
        for c in range(cols):
            x = (c + .5) / cols * 2 - 1
            if x * x + y * y > 1:
                line += " "
                continue
            lat = math.asin(-y)
            lon = math.asin(max(-1, min(1, x / max(1e-6, math.cos(lat)))))
            ri = min(len(lats) - 1, int((math.pi / 2 - lat) / (math.pi / len(lats))))
            k = counts[ri]
            j = min(k - 1, int((lon + math.pi / 2) / (math.pi / k)))
            day = data[starts[ri] + j]
            line += " " if day is None else chars[day["level"]]
        lines.append(line.rstrip())
    return "\n".join(lines)


def inject_readme(ascii_art, total):
    if not README.exists():
        return
    text = README.read_text(encoding="utf-8")
    block = (f"<!-- PLANET:START -->\n```text\n{ascii_art}\n\n"
             f"  · nada   : poco   o algo   O harto   @ a full      {total} contribuciones\n```\n"
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
