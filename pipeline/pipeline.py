# -*- coding: utf-8 -*-
"""
Nothing to Watch — AV edition. Build pipeline.

Reads the same two IMDb exports that AV Movie Universe uses:

    My_watchlist_imdb.csv   -> titles you have NOT watched yet
    My_rating_imdb.csv      -> titles you HAVE watched, with your 1-10 rating

plus, if present, pipeline/tmdb_cache.json (written by fetch_tmdb.py) which maps
each IMDb id to its TMDB poster/backdrop path — and writes the whole app to

    ../Nothing to Watch AV.html

Run it with:   python3 pipeline.py      (no third-party dependencies)

The data half of this file is deliberately the same logic as
AVMovieUniverse/pipeline/pipeline.py, so both projects classify a title
identically. Only the emitted app differs.
"""
import csv, json, os, re, statistics, unicodedata
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WATCHLIST_CSV = os.path.join(ROOT, 'My_watchlist_imdb.csv')
RATINGS_CSV   = os.path.join(ROOT, 'My_rating_imdb.csv')
TMDB_CACHE    = os.path.join(HERE, 'tmdb_cache.json')
ART_DIR       = os.path.join(HERE, 'artwork')      # filled by fetch_tmdb.py
DEST          = os.path.join(ROOT, 'Nothing to Watch AV.html')

# ---------------------------------------------------------------------------
# 1. LOAD  —  two CSVs -> one de-duplicated record per IMDb const (tt……)
# ---------------------------------------------------------------------------
def read_csv(path):
    if not os.path.exists(path):
        print('!! missing', path)
        return []
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def s(row, key):
    return (row.get(key) or '').strip()

def to_int(v):
    try: return int(float(str(v).strip()))
    except (TypeError, ValueError): return None

def to_float(v):
    try: return float(str(v).strip())
    except (TypeError, ValueError): return None

records = {}

def ingest(rows, watched):
    for row in rows:
        const = s(row, 'Const')
        title = s(row, 'Title') or s(row, 'Original Title')
        if not const or not title:
            continue
        my = to_int(s(row, 'Your Rating'))
        rec = {
            'const'   : const,
            'title'   : title,
            'orig'    : s(row, 'Original Title'),
            'ttype'   : s(row, 'Title Type') or 'Movie',
            'imdb'    : to_float(s(row, 'IMDb Rating')),
            'runtime' : to_int(s(row, 'Runtime (mins)')),
            'year'    : to_int(s(row, 'Year')),
            'genres'  : [g.strip() for g in s(row, 'Genres').split(',') if g.strip()],
            'votes'   : to_int(s(row, 'Num Votes')) or 0,
            'director': s(row, 'Directors'),
            'my'      : my,
            'watched' : bool(watched or my),
        }
        prev = records.get(const)
        if prev is None or (rec['watched'] and not prev['watched']):
            records[const] = rec

ingest(read_csv(WATCHLIST_CSV), watched=False)
ingest(read_csv(RATINGS_CSV),   watched=True)

titles = list(records.values())
print('loaded %d unique titles (%d watched / %d unwatched)'
      % (len(titles), sum(1 for t in titles if t['watched']),
                      sum(1 for t in titles if not t['watched'])))

# TMDB artwork paths, if fetch_tmdb.py has been run
tmdb = {}
if os.path.exists(TMDB_CACHE):
    try:
        with open(TMDB_CACHE, encoding='utf-8') as f:
            tmdb = json.load(f)
    except ValueError:
        print('!! tmdb_cache.json is not valid JSON — ignoring it')

# ---------------------------------------------------------------------------
# 2. TIDY
# ---------------------------------------------------------------------------
def strip_diacritics(s_):
    return ''.join(c for c in unicodedata.normalize('NFKD', s_) if not unicodedata.combining(c))

def norm(s_):
    s_ = strip_diacritics(s_ or '').lower()
    s_ = re.sub(r'[^a-z0-9 ]', ' ', s_)
    return re.sub(r'\s+', ' ', s_).strip()

def first_director(raw):
    if not raw: return ''
    d = raw.split(',')[0].strip()
    return d if len(d) < 60 else ''

for t in titles:
    t['title'] = re.sub(r'\s+', ' ', t['title']).strip()
    t['dir_all'] = t['director']
    t['dir'] = first_director(t['director'])
    if t['orig'] == t['title']:
        t['orig'] = ''

# ---------------------------------------------------------------------------
# 3. GENRE  —  IMDb tags up to 4 genres; the wall needs exactly one.
# ---------------------------------------------------------------------------
GENRE_PRIORITY = [
    'Film-Noir', 'Documentary', 'Animation', 'Horror', 'Sci-Fi', 'Fantasy',
    'Western', 'War', 'Musical', 'Music', 'Sport', 'Biography', 'History',
    'Action', 'Adventure', 'Crime', 'Mystery', 'Thriller', 'Romance', 'Family',
    'Comedy', 'Drama', 'Reality-TV', 'Talk-Show', 'Game-Show', 'News',
    'Short', 'Adult',
]
GRANK = {g: i for i, g in enumerate(GENRE_PRIORITY)}
FALLBACK_GENRE = 'Drama'
MIN_CLUSTER = 8

def pick(gl, allowed=None):
    gl = [g for g in gl if allowed is None or g in allowed]
    if not gl: return None
    return min(gl, key=lambda g: GRANK.get(g, 99))

first_pass = Counter(pick(t['genres']) or FALLBACK_GENRE for t in titles)
ALLOWED = {g for g, n in first_pass.items() if n >= MIN_CLUSTER} or {FALLBACK_GENRE}
ALLOWED.add(FALLBACK_GENRE)
for t in titles:
    t['genre'] = pick(t['genres'], ALLOWED) or FALLBACK_GENRE

# ---------------------------------------------------------------------------
# 4. TYPE + LENGTH
# ---------------------------------------------------------------------------
TYPE_BUCKET = {
    'Movie': 'Movie', 'TV Movie': 'Movie', 'Video': 'Movie', 'Short': 'Movie',
    'TV Short': 'Movie', 'Music Video': 'Movie', 'TV Special': 'Movie',
    'TV Series': 'Series', 'TV Mini Series': 'Series', 'TV Episode': 'Series',
    'Podcast Series': 'Series', 'Podcast Episode': 'Series',
    'Video Game': 'Game',
}
# IMDb reports a per-EPISODE runtime for series; these turn it into an approximate
# total. Same assumption (and same numbers) as AV Movie Universe.
EPISODES = {'TV Series': 20, 'TV Mini Series': 6, 'Podcast Series': 20}
PER_EPISODE_CEILING = 200
MAX_MINUTES = 3000

for t in titles:
    t['bucket'] = TYPE_BUCKET.get(t['ttype'], 'Movie')

_by_type  = defaultdict(list)
_by_genre = defaultdict(list)
for t in titles:
    if t['runtime']:
        _by_type[t['ttype']].append(t['runtime'])
        _by_genre[t['genre']].append(t['runtime'])
MED_TYPE  = {k: int(statistics.median(v)) for k, v in _by_type.items()  if v}
MED_GENRE = {k: int(statistics.median(v)) for k, v in _by_genre.items() if v}
MED_ALL   = int(statistics.median([t['runtime'] for t in titles if t['runtime']] or [100]))

n_est = 0
for t in titles:
    if not t['runtime']:
        t['runtime'] = MED_TYPE.get(t['ttype']) or MED_GENRE.get(t['genre']) or MED_ALL
        t['est'] = True
        n_est += 1
    else:
        t['est'] = False
    eps = EPISODES.get(t['ttype'], 1)
    if eps > 1 and t['runtime'] > PER_EPISODE_CEILING:
        eps = 1
    t['eps'] = eps
    t['mins'] = min(t['runtime'] * eps, MAX_MINUTES)

# ---------------------------------------------------------------------------
# 5. GRID ORDER
# ---------------------------------------------------------------------------
# The wall is a plain sequence, so the sort order *is* the layout. Genre-major
# (then most-voted first) gives each genre a contiguous band. The app can
# re-sort live — this is only the order it opens with.
GENRE_ORDER = [g for g, _ in Counter(t['genre'] for t in titles).most_common()]
GPOS = {g: i for i, g in enumerate(GENRE_ORDER)}
titles.sort(key=lambda t: (GPOS[t['genre']], -t['votes'], norm(t['title'])))
for i, t in enumerate(titles):
    t['id'] = i

# ---------------------------------------------------------------------------
# 6. REPORT
# ---------------------------------------------------------------------------
gc = Counter(t['genre'] for t in titles)
print()
print('=== GENRE DISTRIBUTION ===')
for g, c in gc.most_common():
    print('%5d  %s' % (c, g))
print('genres', len(gc), '/ titles', len(titles))
print('=== TYPE ===', dict(Counter(t['bucket'] for t in titles)))
print('runtimes estimated from library medians:', n_est)

n_art = sum(1 for t in titles if tmdb.get(t['const'], {}).get('p'))
if not n_art:
    print('=== ARTWORK === no TMDB poster paths found — run  python3 fetch_tmdb.py  first.')
else:
    print('=== ARTWORK === %d/%d titles have TMDB poster paths (served from CDN)'
          % (n_art, len(titles)))

# ---------------------------------------------------------------------------
# 7. EMIT
# ---------------------------------------------------------------------------
slim = []
for t in titles:
    art = tmdb.get(t['const']) or {}
    r = {
        'id': t['id'],
        't' : t['title'],
        'd' : t['dir_all'],
        'g' : t['genre'],
        'ty': t['bucket'],
        'tt': t['ttype'],
        'yr': t['year'] or 0,          # NB: not "y" — see README, data model
        'rt': t['runtime'],
        'm' : t['mins'],
        'ep': t['eps'],
        'ir': t['imdb'] or 0,
        'nv': t['votes'],
        'c' : t['const'],
    }
    if t['orig']:  r['ot'] = t['orig']
    if t['est']:   r['e']  = 1
    if art.get('p'): r['p'] = art['p']
    if art.get('o'): r['ov'] = art['o']     # TMDB overview, shown above the title
    slim.append(r)

data_json = json.dumps(slim, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
seed_watched = [t['id'] for t in titles if t['watched']]
seed_ratings = {t['id']: t['my'] for t in titles if t['my']}
seed_watched_json = json.dumps(seed_watched, separators=(',', ':'))
seed_ratings_json = json.dumps(seed_ratings, separators=(',', ':'))

HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Nothing to Watch — AV</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&display=swap" rel="stylesheet">
<style>
/* Palette + spacing taken from the original's dark theme. Dark only. */
:root{
  --background:#0a0a0a;
  --foreground:#fafafa;
  --muted:#a1a1a1;
  --muted2:#6f6f6f;
  --border:#262626;
  --border2:#333333;
  --card:#111111;
  --field:#171717;
  --hover:#1f1f1f;
  --radius:.6rem;
  --pad:36px;                      /* the original's md:p-9 */
  --font:"DM Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;overflow:hidden;background:var(--background);color:var(--foreground);
  font-family:var(--font);-webkit-font-smoothing:antialiased}
#app{position:fixed;inset:0}
canvas{display:block;position:absolute;inset:0;touch-action:none;cursor:crosshair;background:var(--background)}
button{font-family:var(--font);color:inherit}
a{color:inherit}

/* ---------------- floating chrome (top-right, like the original navbar) ---------------- */
#nav{position:absolute;top:var(--pad);right:var(--pad);z-index:30;display:flex;gap:4px;align-items:center}
.ghost{width:34px;height:34px;border-radius:9999px;border:1px solid transparent;background:transparent;
  color:var(--foreground);cursor:pointer;display:flex;align-items:center;justify-content:center;
  flex:none;transition:background .15s,border-color .15s;opacity:.8}
.ghost:hover{background:#ffffff1a;opacity:1}
.ghost.on{border-color:var(--foreground);opacity:1}
#count{position:absolute;top:var(--pad);left:var(--pad);z-index:30;font-size:11.5px;color:var(--muted2);
  letter-spacing:.4px;font-variant-numeric:tabular-nums;pointer-events:none;transition:opacity .3s}
#count.dim{opacity:0}

/* ---------------- selected film overlay ---------------- */
/* The original shows the selected film as an overlay over the wall, not as a
   side panel: tagline, oversized title with a lighter year, white genre pills,
   and a circular percentage gauge. Because it floats over the canvas rather
   than displacing it, the wall never has to move to make room. */
#film{position:absolute;left:var(--pad);top:var(--pad);z-index:20;width:min(660px,52vw);
  pointer-events:none;opacity:0;transform:translateY(-6px);transition:opacity .35s,transform .35s}
#film.on{opacity:1;transform:none}
/* the overlay floats over posters, so it needs its own ground to stay legible */
#filmscrim{position:absolute;left:0;top:0;width:min(1150px,92vw);height:min(620px,86vh);z-index:19;
  pointer-events:none;opacity:0;transition:opacity .35s;
  background:radial-gradient(120% 100% at 0% 0%,#0a0a0aeb 0%,#0a0a0ac4 32%,#0a0a0a70 58%,#0a0a0a00 78%)}
#filmscrim.on{opacity:1}
#film .tag{font-size:15px;line-height:1.45;color:#d4d4d4;margin-bottom:10px;max-width:46ch;
  text-shadow:0 2px 16px #000c,0 0 30px #000a}
#film h1{margin:0;font-size:clamp(30px,4vw,58px);font-weight:800;line-height:1.02;letter-spacing:-2px;
  text-shadow:0 2px 20px #000e,0 0 44px #000b}
#film h1 span{font-weight:400;color:#b5b5b5;letter-spacing:-1px}
#film .pills{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}
#film .pill{background:var(--foreground);color:#0a0a0a;font-size:12px;font-weight:700;
  padding:5px 13px;border-radius:9999px;letter-spacing:-.1px}
#film .pill.ghosty{background:transparent;color:var(--foreground);border:1px solid #ffffff59}
#film .lower{display:flex;align-items:center;gap:18px;margin-top:20px}
#gauge{width:66px;height:66px;flex:none;filter:drop-shadow(0 2px 14px #000c)}
#gauge .trk{fill:none;stroke:#ffffff2e;stroke-width:3}
#gauge .arc{fill:none;stroke:var(--foreground);stroke-width:3;stroke-linecap:round;
  transition:stroke-dasharray .5s ease}
#gauge text{fill:var(--foreground);font-family:var(--font);font-weight:700}
#film .facts{font-size:12.5px;color:#c9c9c9;line-height:1.7;text-shadow:0 2px 14px #000c}
#film .facts b{color:var(--muted2);font-weight:500}
#film .acts{display:flex;flex-wrap:wrap;gap:7px;margin-top:18px;pointer-events:auto}
#film .chip{font-size:11.5px;padding:6px 12px;border-radius:9999px;border:1px solid #ffffff33;cursor:pointer;
  color:#e5e5e5;background:#0a0a0a80;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:230px;
  transition:.12s;backdrop-filter:blur(6px)}
#film .chip:hover{border-color:var(--foreground);background:#0a0a0ab8}
#film .chip.solid{background:var(--foreground);color:#0a0a0a;border-color:var(--foreground);font-weight:700}

/* ---------------- drawer (menu kept from my version) ---------------- */
#scrim{position:absolute;inset:0;z-index:38;background:#000000a6;opacity:0;pointer-events:none;transition:.25s}
#scrim.on{opacity:1;pointer-events:auto}
#drawer{position:absolute;top:0;left:0;bottom:0;z-index:40;width:318px;max-width:86vw;background:var(--background);
  border-right:1px solid var(--border);transform:translateX(-104%);
  transition:transform .3s cubic-bezier(.22,.9,.3,1);display:flex;flex-direction:column;overflow:hidden}
#drawer.on{transform:translateX(0)}
.dwrap{padding:18px 16px 24px;overflow-y:auto;display:flex;flex-direction:column;gap:14px;height:100%}
.dhead{display:flex;align-items:center;justify-content:space-between;margin-bottom:2px}
.dhead .t{font-size:13px;font-weight:700;letter-spacing:.4px;text-transform:uppercase;color:var(--muted2)}
.dstat{font-size:11.5px;color:var(--muted2);font-variant-numeric:tabular-nums;margin-top:-6px}

.searchwrap{position:relative}
#search{width:100%;padding:11px 12px 11px 36px;border-radius:var(--radius);border:1px solid var(--border);
  background:var(--field);color:var(--foreground);font-size:14px;font-family:var(--font);outline:none}
#search::placeholder{color:var(--muted2)}
#search:focus{border-color:var(--muted)}
.searchwrap>svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--muted2)}
#results{margin-top:8px;max-height:250px;overflow:auto;border-radius:var(--radius);border:1px solid var(--border);background:var(--card);display:none}
#results.on{display:block}
.res{padding:9px 12px;cursor:pointer;border-bottom:1px solid var(--border)}
.res:last-child{border-bottom:none}
.res:hover,.res.sel{background:var(--hover)}
.res .rt{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.res .ra{font-size:11px;color:var(--muted2);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

#tonight{width:100%;padding:12px;border:none;border-radius:9999px;cursor:pointer;font-size:14px;font-weight:700;
  color:#0a0a0a;background:var(--foreground);letter-spacing:-.1px;transition:opacity .15s}
#tonight:hover{opacity:.85}
.hintline{font-size:11px;color:var(--muted2);text-align:center;margin-top:-8px}

.seg{display:flex;border:1px solid var(--border);border-radius:9999px;padding:3px;gap:2px}
.seg button{flex:1;padding:7px 6px;border:none;border-radius:9999px;background:transparent;color:var(--muted2);
  font-size:11.5px;font-weight:600;cursor:pointer;transition:.15s}
.seg button:hover{color:var(--foreground)}
.seg button.on{background:var(--hover);color:var(--foreground)}

.row{display:flex;gap:6px}
.mini{flex:1;padding:8px 6px;border:1px solid var(--border);border-radius:9999px;background:transparent;color:var(--muted2);
  font-size:11px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:4px;
  transition:.15s;white-space:nowrap}
.mini:hover{color:var(--foreground);border-color:var(--border2)}
.mini.on{color:var(--foreground);border-color:var(--foreground)}

.lh{display:flex;align-items:center;justify-content:space-between;padding:0 2px;margin-top:2px}
.lh span{font-size:10.5px;font-weight:700;color:var(--muted2);text-transform:uppercase;letter-spacing:.8px}
.lh a{font-size:11px;color:var(--muted);cursor:pointer;text-decoration:underline;text-underline-offset:2px}
.lh a:hover{color:var(--foreground)}
#genres{display:flex;flex-direction:column}
.gitem{display:flex;align-items:center;gap:10px;padding:7px 2px;cursor:pointer;border-bottom:1px solid #1a1a1a;transition:.12s}
.gitem:last-child{border-bottom:none}
.gitem:hover .gname{color:var(--foreground)}
.gitem.off .gname,.gitem.off .gcount{color:#3d3d3d;text-decoration:line-through}
.gitem .gname{flex:1;font-size:12.5px;font-weight:500;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:.12s}
.gitem .gbar{width:44px;height:2px;background:#242424;flex:none;overflow:hidden}
.gitem .gbar i{display:block;height:100%;background:var(--muted)}
.gitem .gcount{font-size:11px;color:var(--muted2);font-variant-numeric:tabular-nums;min-width:52px;text-align:right}

.ticks{display:flex;gap:3px;width:100%}
.ticks i{flex:1;height:14px;border-radius:2px;background:#242424;cursor:pointer;transition:background .12s,transform .12s}
.ticks i:hover{transform:scaleY(1.35)}
.ticks i.on{background:var(--foreground)}
.ratefilter{display:flex;flex-direction:column;gap:8px;border:1px solid var(--border);border-radius:var(--radius);padding:10px 12px}
.rf-top{display:flex;align-items:center;gap:8px}
.rf-label{font-size:10.5px;font-weight:700;color:var(--muted2);text-transform:uppercase;letter-spacing:.8px}
.rf-val{margin-left:auto;font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.rf-clear{border:none;background:transparent;color:var(--muted2);cursor:pointer;font-size:13px;padding:0 2px;visibility:hidden}
.rf-clear.on{visibility:visible}
.rf-clear:hover{color:var(--foreground)}

/* ---------------- hint / toast ---------------- */
#hint{position:absolute;bottom:24px;left:50%;transform:translateX(-50%);z-index:15;font-size:11.5px;color:var(--muted2);
  pointer-events:none;transition:opacity .6s;white-space:nowrap;letter-spacing:.3px}
#hint b{color:var(--muted);font-weight:600}
#toast{position:absolute;bottom:62px;left:50%;transform:translateX(-50%) translateY(14px);z-index:70;
  background:var(--foreground);color:#0a0a0a;border-radius:9999px;padding:10px 20px;font-size:13px;font-weight:700;
  opacity:0;transition:.3s;pointer-events:none;max-width:80vw;text-align:center}
#toast.on{opacity:1;transform:translateX(-50%) translateY(0)}

/* ---------------- intro / about ---------------- */
#intro{position:absolute;inset:0;z-index:80;background:var(--background);display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:22px;cursor:pointer;transition:opacity .7s}
#intro.off{opacity:0;pointer-events:none}
#intro h1{margin:0;font-size:clamp(30px,6.2vw,62px);font-weight:900;font-style:italic;line-height:1;letter-spacing:-1.5px;text-align:center;padding:0 24px}
#intro h1 .dots::after{content:"";animation:ell 1s steps(1,end) infinite}
@keyframes ell{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}100%{content:""}}
#intro .sub{font-size:13px;color:var(--muted2);letter-spacing:.3px;text-align:center;padding:0 24px}
#intro .go{margin-top:8px;font-size:12px;color:var(--muted2);border:1px solid var(--border2);border-radius:9999px;padding:9px 20px;letter-spacing:.4px}
#intro .credit{position:absolute;bottom:20px;left:0;right:0;text-align:center;font-size:10.5px;color:#4a4a4a;line-height:1.6;padding:0 24px}
#intro .credit a{color:#6f6f6f}
#about{position:absolute;inset:0;z-index:64;background:#0a0a0af2;display:none;align-items:center;justify-content:center;padding:24px}
#about.on{display:flex}
#about .box{max-width:520px;width:100%;max-height:82vh;overflow:auto;border:1px solid var(--border);border-radius:14px;background:var(--background);padding:26px}
#about h2{margin:0 0 4px;font-size:19px;font-weight:800;font-style:italic;letter-spacing:-.4px}
#about p{font-size:12.5px;line-height:1.65;color:var(--muted);margin:12px 0 0}
#about a{color:var(--foreground);text-underline-offset:2px}
#about .kbd{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}
#about .kbd span{font-size:11px;color:var(--muted2);border:1px solid var(--border);border-radius:6px;padding:4px 8px}
#about .close{margin-top:20px;width:100%;padding:10px;border-radius:9999px;border:1px solid var(--border2);background:transparent;font-size:13px;font-weight:700;cursor:pointer}
#about .close:hover{background:var(--hover)}

.dwrap::-webkit-scrollbar,#results::-webkit-scrollbar,#about .box::-webkit-scrollbar{width:7px}
.dwrap::-webkit-scrollbar-thumb,#results::-webkit-scrollbar-thumb,#about .box::-webkit-scrollbar-thumb{background:#2a2a2a;border-radius:8px}
@media (max-width:760px){
  :root{--pad:18px}
  #film{width:calc(100% - 36px)}
  #count{display:none}
}
</style>
</head>
<body>
<div id="app">
  <canvas id="cv"></canvas>

  <div id="count"><b id="pcount">0</b> / <span id="tcount">0</span> watched · avg <span id="ravg">–</span></div>

  <div id="nav">
    <button class="ghost" id="burger" aria-label="Menu" title="Menu (m)">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
    </button>
    <button class="ghost" id="searchIcon" aria-label="Search" title="Search (/)">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
    </button>
    <button class="ghost" id="aboutBtn" aria-label="About" title="About">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.6v.4"/></svg>
    </button>
  </div>

  <div id="filmscrim"></div>

  <div id="film">
    <div class="tag" id="ftag"></div>
    <h1><span id="ftitle"></span> <span id="fyear"></span></h1>
    <div class="pills" id="fpills"></div>
    <div class="lower">
      <svg id="gauge" viewBox="0 0 40 40">
        <circle class="trk" cx="20" cy="20" r="17.5"></circle>
        <circle class="arc" id="garc" cx="20" cy="20" r="17.5" transform="rotate(-90 20 20)"
                stroke-dasharray="0 110"></circle>
        <text id="gnum" x="20" y="21.6" text-anchor="middle" font-size="12">–</text>
        <text id="gpct" x="29.4" y="17.4" font-size="5.4" opacity=".75">%</text>
      </svg>
      <div class="facts" id="ffacts"></div>
    </div>
    <div class="acts" id="facts2"></div>
  </div>

  <div id="scrim"></div>
  <aside id="drawer">
    <div class="dwrap">
      <div class="dhead">
        <div class="t">Explore</div>
        <button class="ghost" id="drawerClose" aria-label="Close">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
        </button>
      </div>
      <div class="dstat" id="dstat"></div>
      <div class="searchwrap">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
        <input id="search" placeholder="Search title or director" autocomplete="off" spellcheck="false">
        <div id="results"></div>
      </div>
      <button id="tonight">Watch something tonight</button>
      <div class="hintline">a random unwatched pick · press <b>w</b></div>
      <div class="row">
        <button class="mini" id="randMovie">Random film</button>
        <button class="mini" id="randSeries">Random series</button>
      </div>
      <div class="seg" id="statusSeg">
        <button data-s="all" class="on">All</button>
        <button data-s="unwatched">Unwatched</button>
        <button data-s="rated">Rated</button>
      </div>
      <div class="ratefilter">
        <div class="rf-top">
          <span class="rf-label">My rating</span>
          <span class="rf-val" id="rateVal">any</span>
          <button class="rf-clear" id="rateClear" title="Clear">✕</button>
        </div>
        <div class="ticks" id="ratefilterTicks"></div>
      </div>
      <div class="row">
        <button class="mini on" id="tyAll" data-ty="all">All</button>
        <button class="mini" id="tyMovie" data-ty="Movie">Films</button>
        <button class="mini" id="tySeries" data-ty="Series">Series</button>
        <button class="mini" id="tyGame" data-ty="Game">Games</button>
      </div>
      <div class="lh"><span>Arrange</span></div>
      <div class="row">
        <button class="mini on" id="srtGenre" data-srt="genre">Genre</button>
        <button class="mini" id="srtRating" data-srt="rating">Rating</button>
        <button class="mini" id="srtYear" data-srt="year">Year</button>
        <button class="mini" id="srtShuffle" data-srt="shuffle">Shuffle</button>
      </div>
      <div class="row">
        <button class="mini" id="hideBtn">Hide filtered out</button>
      </div>
      <div class="lh"><span>Genres</span><a id="genAll">reset</a></div>
      <div id="genres"></div>
    </div>
  </aside>

  <div id="hint"><b>arrow keys</b> to move · click for details · <b>m</b> menu</div>
  <div id="toast"></div>

  <div id="about">
    <div class="box">
      <h2>"There's nothing to watch<span>…</span>"</h2>
      <p id="aboutStats"></p>
      <p>A personal remake of
        <a href="https://github.com/gnovotny/nothing-to-watch" target="_blank" rel="noopener noreferrer">gnovotny/nothing-to-watch</a>,
        running on my own IMDb export. All credit for the original concept and design
        goes to its author. This is a non-commercial personal project, not affiliated
        with or endorsed by the original.</p>
      <p id="aboutArt"></p>
      <div class="kbd">
        <span><b>←↑↓→</b> move</span><span><b>/</b> search</span><span><b>w</b> watch tonight</span>
        <span><b>m</b> menu</span><span><b>Esc</b> close</span>
      </div>
      <button class="close" id="aboutClose">Close</button>
    </div>
  </div>

  <div id="intro">
    <h1><i>"There's nothing to watch</i><span class="dots"></span><i>"</i></h1>
    <div class="sub" id="introSub"></div>
    <div class="go">Click anywhere to begin</div>
    <div class="credit">
      After <a href="https://github.com/gnovotny/nothing-to-watch" target="_blank" rel="noopener noreferrer">nothing-to-watch</a> by gnovotny · personal, non-commercial<br>
      <span id="introArt"></span>
    </div>
  </div>
</div>

<script>const TITLES = __TITLES_JSON__;
const SEED_WATCHED = __SEED_WATCHED__;    /* IMDb: ids that are watched */
const SEED_RATINGS = __SEED_RATINGS__;    /* IMDb: {id: 1-10} */</script>
<script>
(function(){
"use strict";

function artUrl(f){ return f.p ? "https://image.tmdb.org/t/p/w185"+f.p : null; }

var LS_KEY="ntwav-watched-v1", RATE_KEY="ntwav-ratings-v1";
var MAXR=10;

var watchedSet=loadWatched();
var ratings=(function(){ try{ return JSON.parse(localStorage.getItem(RATE_KEY)||"{}")||{}; }catch(e){ return {}; } })();
var state={status:"all",type:"all",search:"",hidden:{},minRating:0,sort:"genre",hideFiltered:false,selected:null};

function loadWatched(){ try{var r=JSON.parse(localStorage.getItem(LS_KEY)||"[]");var s={};r.forEach(function(id){s[id]=1;});return s;}catch(e){return {};} }
function saveWatched(){ try{localStorage.setItem(LS_KEY,JSON.stringify(Object.keys(watchedSet).map(Number)));}catch(e){} }
function isWatched(id){ return !!watchedSet[id]; }
function saveRatings(){ try{localStorage.setItem(RATE_KEY,JSON.stringify(ratings));}catch(e){} }
function getRating(id){ return ratings[id]||0; }
function norm(s){ return (s||"").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"").replace(/[^a-z0-9 ]/g," ").replace(/\s+/g," ").trim(); }
function firstDir(d){ return (d||"").split(",")[0].trim(); }
function fmtMins(m){ if(!m) return "—"; var h=Math.floor(m/60), mm=m%60; return h?(h+"h"+(mm?" "+mm+"m":"")):(mm+"m"); }
function esc(s){ return (s||"").replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];}); }
function trunc(s,n){ return s.length>n?s.slice(0,n-1)+"…":s; }
function shuffle(a){ a=a.slice(); for(var i=a.length-1;i>0;i--){var j=Math.floor(Math.random()*(i+1)),t=a[i];a[i]=a[j];a[j]=t;} return a; }

// Fallback tile tone for titles with no artwork: neutral, luminance from the id,
// so the wall stays textured instead of a flat grey field.
function toneOf(str){ var h=2166136261; for(var i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,16777619); } return ((h>>>0)%1000)/1000; }
TITLES.forEach(function(f){
  var t=toneOf(f.c);
  var a=Math.round(32+t*28), b=Math.round(19+t*15);
  f.c1="rgb("+a+","+a+","+(a+2)+")";
  f.c2="rgb("+b+","+b+","+(b+2)+")";
  f.nt=norm(f.t+" "+(f.d||""));
});
var HAVE_ART=TITLES.some(function(f){ return !!f.p; });

// ===========================================================================
// THE LENS
// ===========================================================================
// A grid of 2:3 cells covers the viewport. Every point of the grid's LATTICE is
// displaced away from the pointer by a gain that falls off with distance:
//
//     wp = pt + d · k(t),     k(t) = (D+1) / (D·t + 1)
//
// t is the distance normalised so that t = 1 lands on the viewport edge, using a
// SUPERELLIPSE norm — t = (nx⁴ + ny⁴)^¼ with nx,ny scaled by the distance to the
// edge in each axis. Three things fall out of that:
//
//   * k(1) = 1, so the wall's edge is a fixed point: nothing is pushed off
//     screen no matter how strong the lens. An earlier version normalised by the
//     farthest corner, and at high D that flung most of the wall out of frame —
//     which is why only a few huge cells were visible.
//   * the superellipse is smooth, unlike min(distance-to-each-edge), whose kink
//     along the diagonals is what produced the bowtie and corner streaks.
//   * cell size follows for free: tangential stretch is k, radial stretch is
//     (D+1)/(D·t+1)². At the edge that is ~1 across and ~1/20 deep, so periphery
//     cells become the fine speckled slivers the original shows.
//
// LENS_D is the whole feel: how tight the readable orb is against that field.
var LENS_D=20;
var CELL_ASPECT=2/3;
var CELL_GAP=0.9;
var QUAD_MAX=13;
// The corner of a superellipse sits ~19% past t=1, so it is pulled slightly
// inward. Laying the grid out oversized keeps the viewport covered regardless.
var OVERSCAN=1.22;

var cv=document.getElementById("cv"), ctx=cv.getContext("2d",{alpha:false});
var DPR=Math.min(window.devicePixelRatio||1,2), W=0,H=0;
var cols=1, rows=1, cellW=1, cellH=1, order=[];
var pt={tx:0,ty:0,x:0,y:0,has:false};
var POINTER_EASE=0.16;
var pinned=-1, cursor=-1;

var originX=0, originY=0;
function layout(){
  if(W<=0||H<=0) return;
  var n=order.length||1;
  var GW=W*OVERSCAN, GH=H*OVERSCAN;
  cols=Math.max(1,Math.round(Math.sqrt(n*GW/(CELL_ASPECT*GH))));
  rows=Math.max(1,Math.ceil(n/cols));
  cellW=GW/cols; cellH=GH/rows;
  originX=-(GW-W)/2; originY=-(GH-H)/2;
  // Park the opening focus at a cell CENTRE. Dead centre of the screen is a
  // lattice intersection, and a focus exactly on a lattice line is degenerate —
  // that row maps along one line and renders as a bright streak. This lives in
  // layout(), not resize(), because resize() runs before the first buildOrder()
  // when cols/rows are still 1 and half a "cell" is half the screen.
  if(!pt.has){ pt.tx=pt.x=W/2+cellW*0.5; pt.ty=pt.y=H/2+cellH*0.5; }
}
function resize(){
  W=window.innerWidth; H=window.innerHeight;
  cv.width=Math.floor(W*DPR); cv.height=Math.floor(H*DPR);
  cv.style.width=W+"px"; cv.style.height=H+"px";
  ctx.setTransform(DPR,0,0,DPR,0,0);
  layout();
}
window.addEventListener("resize",resize);


// ===========================================================================
// ordering / filtering
// ===========================================================================
function passFilter(f){
  if(state.hidden[f.g]) return false;
  if(state.type!=="all" && f.ty!==state.type) return false;
  if(state.status==="rated" && !getRating(f.id)) return false;
  if(state.status==="unwatched" && isWatched(f.id)) return false;
  if(state.minRating>0 && getRating(f.id)<state.minRating) return false;
  if(state.search && f.nt.indexOf(state.search)<0) return false;
  return true;
}
function passFilterBase(f){
  if(state.hidden[f.g]) return false;
  if(state.type!=="all" && f.ty!==state.type) return false;
  if(state.search && f.nt.indexOf(state.search)<0) return false;
  return true;
}

var GENRE_RANK={};
function buildOrder(){
  var arr=TITLES.slice();
  if(state.hideFiltered) arr=arr.filter(passFilter);
  if(state.sort==="rating")       arr.sort(function(a,b){ return (getRating(b.id)||b.ir)-(getRating(a.id)||a.ir) || b.nv-a.nv; });
  else if(state.sort==="year")    arr.sort(function(a,b){ return (b.yr||0)-(a.yr||0) || b.nv-a.nv; });
  else if(state.sort==="shuffle") arr=shuffle(arr);
  else                            arr.sort(function(a,b){ return (GENRE_RANK[a.g]-GENRE_RANK[b.g]) || b.nv-a.nv; });
  order=arr; layout();
}

// ===========================================================================
// artwork loading (lazy, bounded, biggest cells first)
// ===========================================================================
var imgCache={}, inflight=0, MAX_INFLIGHT=16, TILE_MIN_W=9;
function tileImage(f){
  var u=artUrl(f); if(!u) return null;
  var e=imgCache[f.c];
  if(e!==undefined) return e;
  if(inflight>=MAX_INFLIGHT) return null;
  inflight++;
  var img=new Image();
  img.decoding="async";
  img.onload =function(){ inflight--; imgCache[f.c]=img; };
  img.onerror=function(){ inflight--; imgCache[f.c]=null; };
  img.src=u;
  return null;
}

function rrect(x,y,w,h,r){
  r=Math.min(r,w/2,h/2);
  ctx.beginPath();
  if(ctx.roundRect){ ctx.roundRect(x,y,w,h,r); return; }
  ctx.moveTo(x+r,y); ctx.arcTo(x+w,y,x+w,y+h,r); ctx.arcTo(x+w,y+h,x,y+h,r);
  ctx.arcTo(x,y+h,x,y,r); ctx.arcTo(x,y,x+w,y,r); ctx.closePath();
}

var FS='"DM Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif';
var hoverIdx=-1;
var gX=null,gY=null,gW=null,gH=null,vis=[];
var wpx=null,wpy=null;
function ensureScratch(n){
  if(!gX||gX.length<n){ gX=new Float32Array(n); gY=new Float32Array(n); gW=new Float32Array(n); gH=new Float32Array(n); }
  var need=(cols+1)*(rows+1);
  if(!wpx||wpx.length<need){ wpx=new Float32Array(need); wpy=new Float32Array(need); }
}

function draw(){
  requestAnimationFrame(draw);
  if(W<=0||H<=0) return;
  pt.x+=(pt.tx-pt.x)*POINTER_EASE; pt.y+=(pt.ty-pt.y)*POINTER_EASE;

  ctx.fillStyle="#0a0a0a"; ctx.fillRect(0,0,W,H);

  if(pinned>=0 && pinned<order.length){
    pt.tx=originX+(pinned%cols+0.5)*cellW; pt.ty=originY+((pinned/cols|0)+0.5)*cellH;
  }

  var n=order.length, bestD=1e18, bestI=-1;
  var mx=pt.tx, my=pt.ty;
  ensureScratch(n); vis.length=0;

  // ---- pass 0: warp the lattice ----
  var stride=cols+1;
  var ax=Math.max(1,Math.max(pt.x,W-pt.x)), by=Math.max(1,Math.max(pt.y,H-pt.y));
  for(var ri0=0;ri0<=rows;ri0++){
    var ly=originY+ri0*cellH, dy0=ly-pt.y, ny=dy0/by, ny4=ny*ny; ny4*=ny4;
    for(var ci0=0;ci0<=cols;ci0++){
      var lx=originX+ci0*cellW, dx0=lx-pt.x, nx=dx0/ax, nx4=nx*nx; nx4*=nx4;
      var t=Math.sqrt(Math.sqrt(nx4+ny4));        // superellipse radius, 1 at the edge
      var k=(LENS_D+1)/(LENS_D*t+1);              // gain: D+1 at the focus, 1 at the edge
      var o=ri0*stride+ci0;
      wpx[o]=pt.x+dx0*k; wpy[o]=pt.y+dy0*k;
    }
  }

  // ---- pass 1: geometry from the four shared corners + hover pick ----
  for(var i=0;i<n;i++){
    var ci=i%cols, ri=(i/cols)|0;
    var k0=ri*stride+ci, k1=k0+1, k3=k0+stride, k2=k3+1;
    var x0=wpx[k0],y0=wpy[k0], x1=wpx[k1],y1=wpy[k1], x2=wpx[k2],y2=wpy[k2], x3=wpx[k3],y3=wpy[k3];
    var sx=(x0+x1+x2+x3)*0.25, sy=(y0+y1+y2+y3)*0.25;
    var w=(Math.hypot(x1-x0,y1-y0)+Math.hypot(x2-x3,y2-y3))*0.5;
    var h=(Math.hypot(x3-x0,y3-y0)+Math.hypot(x2-x1,y2-y1))*0.5;
    if(w<0.6||h<0.6) continue;
    if(sx-w>W||sy-h>H||sx+w<0||sy+h<0) continue;
    var hdx=sx-mx, hdy=sy-my, hd=hdx*hdx+hdy*hdy;
    if(hd<bestD && Math.abs(hdx)<=w/2+2 && Math.abs(hdy)<=h/2+2){ bestD=hd; bestI=i; }
    gX[i]=sx; gY[i]=sy; gW[i]=w; gH[i]=h; vis.push(i);
  }

  // Smallest first, so magnified cells overlap the seams the warp opens.
  vis.sort(function(a,b){ return gW[a]-gW[b]; });

  // Request artwork LARGEST first. Drawing runs smallest-first, so asking inside
  // the draw loop spent the whole in-flight budget on the tiny periphery and the
  // magnified cells — the only place a poster is legible — never loaded.
  for(var vq=vis.length-1, asked=0; vq>=0 && asked<MAX_INFLIGHT*2; vq--){
    if(gW[vis[vq]]<=TILE_MIN_W) break;
    tileImage(order[vis[vq]]); asked++;
  }

  // ---- pass 2: draw ----
  for(var vi=0;vi<vis.length;vi++){
    var i=vis[vi], f=order[i];
    var cx=gX[i], cy=gY[i], w=gW[i], h=gH[i];
    var active=passFilter(f), seen=isWatched(f.id);
    var dim=(!active) ? 0.10 : (seen && state.status!=="rated" ? 0.62 : 1);
    var img=(w>TILE_MIN_W)?imgCache[f.c]:null;

    // LOD 0 — compressed field: fill the exact lattice quad. Adjacent quads
    // share corners, so the periphery reads as one seamless mosaic.
    if(w<QUAD_MAX){
      var q0=((i/cols)|0)*stride+(i%cols), q1=q0+1, q3=q0+stride, q2=q3+1;
      ctx.beginPath();
      ctx.moveTo(wpx[q0],wpy[q0]); ctx.lineTo(wpx[q1],wpy[q1]);
      ctx.lineTo(wpx[q2],wpy[q2]); ctx.lineTo(wpx[q3],wpy[q3]); ctx.closePath();
      ctx.globalAlpha=dim*0.9;
      if(img){ ctx.save(); ctx.clip(); ctx.drawImage(img,cx-w/2,cy-h/2,w,h); ctx.restore(); }
      else { ctx.fillStyle=f.c1; ctx.fill(); }
      ctx.globalAlpha=1;
      if(state.selected===f.id){ ctx.strokeStyle="#fafafa"; ctx.lineWidth=1.5; ctx.stroke(); }
      continue;
    }

    // LOD 1/2 — a rounded poster card.
    w*=CELL_GAP; h*=CELL_GAP;
    var x=cx-w/2, y=cy-h/2, rad=Math.min(w,h)*0.12;
    ctx.save();
    rrect(x,y,w,h,rad); ctx.clip();
    ctx.globalAlpha=dim;
    if(img){
      ctx.drawImage(img,x,y,w,h);
    } else {
      var g=ctx.createLinearGradient(x,y,x,y+h);
      g.addColorStop(0,f.c1); g.addColorStop(1,f.c2);
      ctx.fillStyle=g; ctx.fillRect(x,y,w,h);
      if(w>=46){
        var pad=Math.max(5,w*0.09);
        var fs=Math.max(8,Math.min(14,w*0.098));
        ctx.font="700 "+fs+"px "+FS; ctx.fillStyle="rgba(250,250,250,.92)";
        ctx.textAlign="left"; ctx.textBaseline="alphabetic";
        wrapText(f.t, x+pad, y+h*0.52, w-pad*2, fs*1.2, 3);
        if(f.yr){ ctx.font="500 "+Math.max(7,fs*0.76)+"px "+FS; ctx.fillStyle="rgba(160,160,160,.9)";
                  ctx.fillText(f.yr, x+pad, y+h-pad); }
      }
    }
    if(active && seen && state.status!=="rated"){
      ctx.fillStyle="rgba(10,10,10,.28)"; ctx.fillRect(x,y,w,h);
    }
    ctx.globalAlpha=1;
    ctx.restore();

    if(state.selected===f.id || i===hoverIdx){
      ctx.strokeStyle=state.selected===f.id?"#fafafa":"rgba(250,250,250,.5)";
      ctx.lineWidth=state.selected===f.id?2:1.25;
      rrect(x,y,w,h,rad); ctx.stroke();
    }
  }
  hoverIdx=bestI;
}

function wrapText(text,x,y,maxW,lh,maxLines){
  var words=text.split(" "), line="", lines=[];
  for(var i=0;i<words.length;i++){
    var test=line?line+" "+words[i]:words[i];
    if(ctx.measureText(test).width>maxW && line){ lines.push(line); line=words[i]; }
    else line=test;
  }
  lines.push(line);
  if(lines.length>maxLines){ lines=lines.slice(0,maxLines); lines[maxLines-1]=lines[maxLines-1].replace(/.$/,"…"); }
  for(var j=0;j<lines.length;j++) ctx.fillText(lines[j],x,y+j*lh);
}

// ===========================================================================
// input
// ===========================================================================
var lastCX=null, lastCY=null, UNPIN_PX=6;
cv.addEventListener("pointermove",function(e){
  // Opening a panel reflows the page under a stationary cursor and the browser
  // answers with a synthesised pointermove; unpinning on any move let that
  // phantom event yank the lens off a title picked from search.
  if(lastCX!==null && pinned>=0 &&
     Math.abs(e.clientX-lastCX)<UNPIN_PX && Math.abs(e.clientY-lastCY)<UNPIN_PX) return;
  lastCX=e.clientX; lastCY=e.clientY;
  pt.tx=e.clientX; pt.ty=e.clientY; pt.has=true; pinned=-1; cursor=-1;
});
cv.addEventListener("click",function(){
  if(hoverIdx>=0){ var f=order[hoverIdx]; state.selected=f.id; showFilm(f); }
  else hideFilm();
});
cv.addEventListener("touchmove",function(e){
  if(!e.touches.length) return;
  var t=e.touches[0]; pt.tx=t.clientX; pt.ty=t.clientY; pt.has=true; pinned=-1; cursor=-1;
},{passive:true});

// ---- keyboard navigation: arrows walk the grid cell by cell ----
// The lens has no camera to scroll, so "scrolling" is moving the focus. Arrows
// step one cell, so a held key glides the lens across the wall.
function moveCursor(dx,dy){
  if(!order.length) return;
  if(cursor<0) cursor = (pinned>=0 ? pinned : nearestToPointer());
  var ci=cursor%cols, ri=(cursor/cols)|0;
  ci+=dx; ri+=dy;
  if(ci<0){ ci=cols-1; ri--; }
  if(ci>=cols){ ci=0; ri++; }
  ri=Math.max(0,Math.min(rows-1,ri));
  var idx=Math.max(0,Math.min(order.length-1, ri*cols+ci));
  cursor=idx; pinned=idx; pt.has=true;
  var f=order[idx]; state.selected=f.id; showFilm(f);
}
function nearestToPointer(){
  var ci=Math.max(0,Math.min(cols-1,Math.floor((pt.tx-originX)/cellW)));
  var ri=Math.max(0,Math.min(rows-1,Math.floor((pt.ty-originY)/cellH)));
  return Math.max(0,Math.min(order.length-1, ri*cols+ci));
}

// ===========================================================================
// the selected-film overlay
// ===========================================================================
var film=document.getElementById("film");
function showFilm(f){
  document.getElementById("ftag").textContent = f.ov || "";
  document.getElementById("ftitle").textContent = f.t;
  document.getElementById("fyear").textContent = f.yr ? "("+f.yr+")" : "";

  var pills=document.getElementById("fpills"); pills.innerHTML="";
  var p1=document.createElement("span"); p1.className="pill"; p1.textContent=f.g; pills.appendChild(p1);
  var p2=document.createElement("span"); p2.className="pill"; p2.textContent=f.ty==="Movie"?"Film":f.ty; pills.appendChild(p2);
  var p3=document.createElement("span"); p3.className="pill ghosty";
  p3.textContent=isWatched(f.id)?"Watched":"Not watched"; pills.appendChild(p3);

  // circular gauge — percentage, exactly like the original's rating dial
  var pct=Math.round((f.ir||0)*10), C=2*Math.PI*17.5;
  document.getElementById("garc").setAttribute("stroke-dasharray",(C*pct/100)+" "+C);
  document.getElementById("gnum").textContent = pct? pct : "–";
  document.getElementById("gpct").style.opacity = pct? .75 : 0;

  var my=getRating(f.id);
  document.getElementById("ffacts").innerHTML=
    (f.d?"<b>"+esc(firstDir(f.d))+"</b><br>":"")+
    esc(f.tt)+" · "+esc(f.ep>1 ? fmtMins(f.rt)+"/ep · ≈"+fmtMins(f.m) : fmtMins(f.rt))+
    (my? "<br><b>my rating</b> "+my+"/10" : "");

  var acts=document.getElementById("facts2"); acts.innerHTML="";
  var a=document.createElement("a"); a.className="chip solid"; a.textContent="IMDb ↗";
  a.href="https://www.imdb.com/title/"+f.c+"/"; a.target="_blank"; a.rel="noopener noreferrer";
  acts.appendChild(a);
  acts.appendChild(chip("Only "+f.g,function(){soloGenre(f.g);}));
  var nd=norm(firstDir(f.d));
  if(nd.length>=4){
    var same=TITLES.filter(function(x){return x.id!==f.id&&norm(firstDir(x.d))===nd;}).slice(0,3);
    same.forEach(function(x){ acts.appendChild(chip(trunc(x.t,26),function(){focusTitle(x);})); });
  }
  shuffle(TITLES.filter(function(x){return x.id!==f.id&&x.g===f.g&&!isWatched(x.id);})).slice(0,2)
    .forEach(function(x){ acts.appendChild(chip(trunc(x.t,26),function(){focusTitle(x);})); });

  film.classList.add("on");
  document.getElementById("filmscrim").classList.add("on");
  document.getElementById("count").classList.add("dim");
}
function hideFilm(){ film.classList.remove("on"); state.selected=null;
  document.getElementById("filmscrim").classList.remove("on");
  document.getElementById("count").classList.remove("dim"); }
function chip(text,fn){ var c=document.createElement("div"); c.className="chip"; c.textContent=text; c.title=text; c.onclick=fn; return c; }

function focusTitle(f){
  if(state.hideFiltered && !passFilter(f)){ state.hideFiltered=false; syncHideBtn(); buildOrder(); }
  var idx=order.indexOf(f);
  if(idx<0){ toast("Hidden by a filter — "+trunc(f.t,32)); return; }
  state.selected=f.id; showFilm(f);
  pinned=idx; cursor=idx; pt.has=true;
}

// ===========================================================================
// drawer / menu
// ===========================================================================
var drawer=document.getElementById("drawer"), scrim=document.getElementById("scrim");
function openDrawer(){ drawer.classList.add("on"); scrim.classList.add("on"); }
function closeDrawer(){ drawer.classList.remove("on"); scrim.classList.remove("on"); document.getElementById("results").classList.remove("on"); }
document.getElementById("burger").onclick=function(){ drawer.classList.contains("on")?closeDrawer():openDrawer(); };
document.getElementById("drawerClose").onclick=closeDrawer;
scrim.onclick=closeDrawer;
document.getElementById("searchIcon").onclick=function(){ openDrawer(); setTimeout(function(){document.getElementById("search").focus();},260); };

var about=document.getElementById("about");
document.getElementById("aboutBtn").onclick=function(){ about.classList.toggle("on"); };
document.getElementById("aboutClose").onclick=function(){ about.classList.remove("on"); };
about.onclick=function(e){ if(e.target===about) about.classList.remove("on"); };

function suggest(kind,label){
  var pool=TITLES.filter(function(f){ return passFilterBase(f)&&!isWatched(f.id)&&(kind==="any"||f.ty===kind); });
  if(!pool.length){ toast("Nothing unwatched matches your filters"); return; }
  var p=pool[Math.floor(Math.random()*pool.length)];
  closeDrawer(); focusTitle(p);
  toast(label+" — "+trunc(p.t,38)+(p.yr?" ("+p.yr+")":""));
}
document.getElementById("tonight").onclick   =function(){ suggest("any",   "Tonight"); };
document.getElementById("randMovie").onclick =function(){ suggest("Movie", "Random film"); };
document.getElementById("randSeries").onclick=function(){ suggest("Series","Random series"); };

// ---- search ----
var search=document.getElementById("search"), results=document.getElementById("results"), resSel=-1, resList=[];
search.addEventListener("input",function(){ state.search=norm(search.value); if(state.hideFiltered) buildOrder(); renderResults(); });
search.addEventListener("keydown",function(e){
  if(e.key==="ArrowDown"){ resSel=Math.min(resList.length-1,resSel+1); markRes(); e.preventDefault(); }
  else if(e.key==="ArrowUp"){ resSel=Math.max(0,resSel-1); markRes(); e.preventDefault(); }
  else if(e.key==="Enter"){ var t=resList[resSel]||resList[0]; if(t) gotoResult(t); }
  else if(e.key==="Escape"){ search.value=""; state.search=""; results.classList.remove("on"); if(state.hideFiltered) buildOrder(); }
  e.stopPropagation();
});
// Picking a result means "take me there" — drop the query afterwards, or the
// search filter stays live and washes the whole wall out.
function gotoResult(f){
  search.value=""; state.search=""; results.classList.remove("on"); resList=[];
  if(state.hideFiltered) buildOrder();
  closeDrawer(); focusTitle(f);
}
function renderResults(){
  var q=state.search; if(!q){ results.classList.remove("on"); resList=[]; return; }
  var arr=TITLES.filter(function(f){ return f.nt.indexOf(q)>=0; });
  arr.sort(function(a,b){ var at=norm(a.t).indexOf(q), bt=norm(b.t).indexOf(q); return (at<0?99:at)-(bt<0?99:bt) || b.nv-a.nv; });
  resList=arr.slice(0,8); resSel=-1;
  if(!resList.length){ results.innerHTML='<div class="res"><div class="rt">No matches</div></div>'; results.classList.add("on"); return; }
  results.innerHTML="";
  resList.forEach(function(f,i){
    var d=document.createElement("div"); d.className="res"; var rt=getRating(f.id);
    d.innerHTML='<div class="rt">'+esc(f.t)+(f.yr?' <span style="color:#6f6f6f">'+f.yr+'</span>':'')+'</div>'+
      '<div class="ra">'+esc(f.d||"—")+' · '+esc(f.g)+' · '+(isWatched(f.id)?"watched":"unwatched")+(rt?' · '+rt+'/10':'')+'</div>';
    d.onmouseenter=function(){resSel=i;markRes();};
    d.onclick=function(){ gotoResult(f); };
    results.appendChild(d);
  });
  results.classList.add("on");
}
function markRes(){ [].forEach.call(results.children,function(c,i){ c.classList.toggle("sel",i===resSel); }); }

// ---- filters ----
var statusSeg=document.getElementById("statusSeg");
statusSeg.addEventListener("click",function(e){
  var btn=e.target.closest("button"); if(!btn) return;
  state.status=btn.dataset.s;
  [].forEach.call(statusSeg.children,function(c){c.classList.toggle("on",c===btn);});
  if(state.hideFiltered) buildOrder();
});
var TYPE_BTNS=[["tyAll","all"],["tyMovie","Movie"],["tySeries","Series"],["tyGame","Game"]];
TYPE_BTNS.forEach(function(p){ document.getElementById(p[0]).onclick=function(){
  state.type=p[1]; TYPE_BTNS.forEach(function(q){document.getElementById(q[0]).classList.toggle("on",q[0]===p[0]);});
  if(state.hideFiltered) buildOrder();
};});
var SORT_BTNS=[["srtGenre","genre"],["srtRating","rating"],["srtYear","year"],["srtShuffle","shuffle"]];
SORT_BTNS.forEach(function(p){ document.getElementById(p[0]).onclick=function(){
  state.sort=p[1]; SORT_BTNS.forEach(function(q){document.getElementById(q[0]).classList.toggle("on",q[0]===p[0]);});
  buildOrder(); toast("Arranged by "+p[1]);
};});
var hideBtn=document.getElementById("hideBtn");
function syncHideBtn(){ hideBtn.classList.toggle("on",state.hideFiltered); }
hideBtn.onclick=function(){ state.hideFiltered=!state.hideFiltered; syncHideBtn(); buildOrder();
  toast(state.hideFiltered?"Showing only matches":"Showing everything"); };

// ---- rating filter ----
var rfTicks=document.getElementById("ratefilterTicks"), rfClear=document.getElementById("rateClear"), rfVal=document.getElementById("rateVal");
function buildRateFilter(){
  rfTicks.innerHTML="";
  for(var i=1;i<=MAXR;i++){ (function(i){
    var el=document.createElement("i"); el.title=i+"+ / 10";
    el.onmouseenter=function(){ paintTicks(i); rfVal.textContent=i+"+"; };
    el.onmouseleave=function(){ syncRateFilter(); };
    el.onclick=function(){ state.minRating=(state.minRating===i)?0:i; syncRateFilter(); if(state.hideFiltered) buildOrder(); };
    rfTicks.appendChild(el);
  })(i); }
  syncRateFilter();
}
function paintTicks(n){ var ch=rfTicks.children; for(var i=0;i<ch.length;i++) ch[i].classList.toggle("on", i<n); }
function syncRateFilter(){ paintTicks(state.minRating); rfClear.classList.toggle("on",state.minRating>0);
  rfVal.textContent=state.minRating?(state.minRating+"+ / 10"):"any"; }
rfClear.onclick=function(){ state.minRating=0; syncRateFilter(); if(state.hideFiltered) buildOrder(); };

// ---- genre list ----
var genresEl=document.getElementById("genres"), genreCounts={}, genreList=[], genreMax=1;
function buildGenreList(){
  genresEl.innerHTML="";
  genreList.forEach(function(g){
    var seenN=TITLES.reduce(function(a,f){return a+((f.g===g&&isWatched(f.id))?1:0);},0);
    var it=document.createElement("div"); it.className="gitem"+(state.hidden[g]?" off":"");
    it.innerHTML='<span class="gname">'+esc(g)+'</span>'+
                 '<span class="gbar"><i style="width:'+Math.round(genreCounts[g]/genreMax*100)+'%"></i></span>'+
                 '<span class="gcount">'+seenN+' / '+genreCounts[g]+'</span>';
    it.onclick=function(){ state.hidden[g]=!state.hidden[g]; it.classList.toggle("off",state.hidden[g]);
      if(state.hideFiltered) buildOrder(); };
    genresEl.appendChild(it);
  });
}
document.getElementById("genAll").onclick=function(){ state.hidden={}; buildGenreList(); if(state.hideFiltered) buildOrder(); };
function soloGenre(g){ state.hidden={}; genreList.forEach(function(x){ if(x!==g) state.hidden[x]=true; });
  buildGenreList(); if(state.hideFiltered) buildOrder(); toast("Only "+g); }

// ---- progress / toast ----
function updProgress(){
  var ids=Object.keys(ratings), n=ids.length, sum=0; for(var i=0;i<n;i++) sum+=ratings[ids[i]]||0;
  var avg=n?(sum/n).toFixed(1):"–";
  document.getElementById("pcount").textContent=Object.keys(watchedSet).length;
  document.getElementById("tcount").textContent=TITLES.length;
  document.getElementById("ravg").textContent=avg;
  document.getElementById("dstat").textContent=
    Object.keys(watchedSet).length+" of "+TITLES.length+" watched · avg "+avg;
}
var toastEl=document.getElementById("toast"), toastT=0;
function toast(msg){ toastEl.textContent=msg; toastEl.classList.add("on"); clearTimeout(toastT);
  toastT=setTimeout(function(){toastEl.classList.remove("on");},2600); }

// ---- keyboard ----
window.addEventListener("keydown",function(e){
  if(e.target.tagName==="INPUT"||e.target.tagName==="TEXTAREA") return;
  if(!intro.classList.contains("off")){ dismissIntro(); return; }
  var k=e.key;
  if(k==="ArrowLeft"){ moveCursor(-1,0); e.preventDefault(); }
  else if(k==="ArrowRight"){ moveCursor(1,0); e.preventDefault(); }
  else if(k==="ArrowUp"){ moveCursor(0,-1); e.preventDefault(); }
  else if(k==="ArrowDown"){ moveCursor(0,1); e.preventDefault(); }
  else if(k==="/"){ openDrawer(); setTimeout(function(){search.focus();},260); e.preventDefault(); }
  else if(k==="w"||k==="W"){ document.getElementById("tonight").click(); }
  else if(k==="m"||k==="M"){ drawer.classList.contains("on")?closeDrawer():openDrawer(); }
  else if(k==="Escape"){ about.classList.remove("on"); closeDrawer(); hideFilm(); }
});

// ---- IMDb seed (applied once) ----
var SEED_KEY="ntwav-seed-v1", SEED_VERSION="imdb-1";
(function applySeed(){
  try{ if(localStorage.getItem(SEED_KEY)===SEED_VERSION) return; }catch(e){}
  try{
    if(typeof SEED_WATCHED!=="undefined") SEED_WATCHED.forEach(function(id){ watchedSet[id]=1; });
    if(typeof SEED_RATINGS!=="undefined") Object.keys(SEED_RATINGS).forEach(function(id){ ratings[id]=+SEED_RATINGS[id]; watchedSet[id]=1; });
    saveWatched(); saveRatings(); localStorage.setItem(SEED_KEY,SEED_VERSION);
  }catch(e){}
})();

// ---- intro ----
var intro=document.getElementById("intro");
function dismissIntro(){
  if(intro.classList.contains("off")) return;
  intro.classList.add("off");
  setTimeout(function(){ intro.style.display="none"; },800);
  setTimeout(function(){ var h=document.getElementById("hint"); if(h) h.style.opacity="0"; },8000);
}
intro.addEventListener("click",dismissIntro);

// ---- init ----
(function(){
  TITLES.forEach(function(f){ genreCounts[f.g]=(genreCounts[f.g]||0)+1; });
  genreList=Object.keys(genreCounts).sort(function(a,b){ return genreCounts[b]-genreCounts[a]; });
  genreList.forEach(function(g,i){ GENRE_RANK[g]=i; });
  genreMax=Math.max.apply(null,genreList.map(function(g){return genreCounts[g];}));
})();
resize();
buildOrder();
buildGenreList();
buildRateFilter();
syncHideBtn();
updProgress();

(function(){
  var watched=Object.keys(watchedSet).length;
  var stats=TITLES.length.toLocaleString()+" titles · "+watched.toLocaleString()+" watched · "+genreList.length+" genres";
  document.getElementById("introSub").textContent=stats;
  document.getElementById("aboutStats").textContent="My IMDb library: "+stats+". Watched status and ratings come from the export and are read-only.";
  var art=HAVE_ART
    ? "Film artwork from TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB."
    : "No artwork yet — run pipeline/fetch_tmdb.py to download posters from TMDB.";
  document.getElementById("introArt").textContent=art;
  document.getElementById("aboutArt").textContent=art;
})();

requestAnimationFrame(draw);
})();
</script>
</body>
</html>'''

out = (HTML.replace('__TITLES_JSON__', data_json)
           .replace('__SEED_WATCHED__', seed_watched_json)
           .replace('__SEED_RATINGS__', seed_ratings_json))
with open(DEST, 'w', encoding='utf-8') as f:
    f.write(out)
print()
print('wrote', DEST, len(out), 'bytes; titles:', len(slim),
      '; seeded watched:', len(seed_watched), '; seeded ratings:', len(seed_ratings))
