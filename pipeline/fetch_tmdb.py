# -*- coding: utf-8 -*-
"""
Downloads the film artwork into  pipeline/artwork/<imdb-id>.jpg

Two steps per title, both from TMDB:
  1. resolve the IMDb id to a TMDB record (needs your free API key)
  2. download the poster at IMG_SIZE into pipeline/artwork/

Results are remembered in pipeline/tmdb_cache.json so the run is resumable and
incremental — re-running after adding films to your IMDb list only fetches the
new ones. The cache also keeps each film's overview, which the app shows as the
tagline line above the title.

    export TMDB_API_KEY=xxxxxxxxxxxxxxxx
    python3 fetch_tmdb.py
    python3 pipeline.py

Size: w185 is deliberate. The wall's most magnified cell is ~160 px wide, so
anything larger is wasted, and w185 costs almost nothing over w154 (16.6 KB vs
16.0 KB) while looking noticeably better. ~2,100 posters lands around 33 MB —
small enough to commit and serve from GitHub Pages.

TMDB terms require attribution wherever the artwork is shown; the app carries it
on the intro and About screens.
"""
import csv, json, os, sys, time, urllib.parse, urllib.request

HERE   = os.path.dirname(os.path.abspath(__file__))
ROOT   = os.path.dirname(HERE)
ART    = os.path.join(HERE, 'artwork')
CACHE  = os.path.join(HERE, 'tmdb_cache.json')

API_KEY  = os.environ.get('TMDB_API_KEY', '69f55b71e200fd4fc2d39bcd0216f9a8').strip()
IMG_SIZE = 'w185'       # see note above
SLEEP    = 0.25         # seconds between API calls; TMDB is rate limited
UA       = {'User-Agent': 'nothing-to-watch-av/1.0'}



def imdb_ids():
    seen, out = set(), []
    for name in ('My_watchlist_imdb.csv', 'My_rating_imdb.csv'):
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        with open(path, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                c = (row.get('Const') or '').strip()
                t = (row.get('Title') or '').strip()
                if c and c not in seen:
                    seen.add(c)
                    out.append((c, t))
    return out


def load_cache():
    if os.path.exists(CACHE):
        try:
            with open(CACHE, encoding='utf-8') as f:
                return json.load(f)
        except ValueError:
            print('!! cache was corrupt, starting fresh')
    return {}


def save_cache(cache):
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def lookup(imdb_id):
    """TMDB resolves a title directly from its IMDb id."""
    url = ('https://api.themoviedb.org/3/find/%s?api_key=%s&external_source=imdb_id'
           % (urllib.parse.quote(imdb_id), API_KEY))
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        data = json.load(r)
    for key in ('movie_results', 'tv_results', 'tv_episode_results'):
        for hit in data.get(key) or []:
            if hit.get('poster_path'):
                ov = (hit.get('overview') or '').strip()
                if len(ov) > 300:
                    ov = ov[:297].rsplit(' ', 1)[0] + '…'
                return {'p': hit['poster_path'], 'o': ov}
    return {'p': '', 'o': ''}          # cached as "looked up, has nothing"


def download(poster_path, dest):
    url = 'https://image.tmdb.org/t/p/%s%s' % (IMG_SIZE, poster_path)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        data = r.read()
    if len(data) < 200:
        raise IOError('suspiciously small response')
    tmp = dest + '.part'                       # write-then-rename, so an interrupted
    with open(tmp, 'wb') as f:                 # run never leaves a half-written jpg
        f.write(data)
    os.replace(tmp, dest)
    return len(data)


def main():
    if not API_KEY:
        print("Error: TMDB API key is missing. Set TMDB_API_KEY environment variable or define it in fetch_tmdb.py.")
        sys.exit(1)
    os.makedirs(ART, exist_ok=True)
    cache = load_cache()
    ids = imdb_ids()

    todo = []
    for const, title in ids:
        have_file = os.path.exists(os.path.join(ART, const + '.jpg'))
        known = const in cache
        if known and (have_file or not cache[const].get('p')):
            continue                            # nothing left to do for this one
        todo.append((const, title))

    print('%d titles · %d already done · %d to fetch' % (len(ids), len(ids) - len(todo), len(todo)))
    if not todo:
        print('nothing to do — run  python3 pipeline.py  to rebuild')
        return

    got = missing = failed = 0
    total_bytes = 0
    try:
        for i, (const, title) in enumerate(todo, 1):
            try:
                if const not in cache:
                    cache[const] = lookup(const)
                    time.sleep(SLEEP)
                pp = cache[const].get('p')
                if not pp:
                    missing += 1
                    continue
                dest = os.path.join(ART, const + '.jpg')
                if not os.path.exists(dest):
                    total_bytes += download(pp, dest)
                    got += 1
                if got and got % 25 == 0:
                    print('  [%4d/%d] %d posters · %.1f MB   %s'
                          % (i, len(todo), got, total_bytes / 1048576.0, title[:40]))
                    save_cache(cache)
            except Exception as e:
                failed += 1
                print('  [%4d/%d] FAILED %s (%s): %s' % (i, len(todo), title[:40], const, e))
    except KeyboardInterrupt:
        print('\ninterrupted — saving progress')

    save_cache(cache)
    on_disk = len([n for n in os.listdir(ART) if n.endswith('.jpg')])
    print()
    print('done — %d downloaded (%.1f MB), %d without artwork, %d failed'
          % (got, total_bytes / 1048576.0, missing, failed))
    print('%d posters now in %s' % (on_disk, ART))
    print('re-run to retry failures, then:  python3 pipeline.py')


if __name__ == '__main__':
    main()
