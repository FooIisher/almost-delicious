"""Offline mapping: recipes without images -> a similar recipe that has a real photo.

Levels (first hit wins):
  L1  same cleaned name
  L2  same head phrase (last two words of the name before with/in/over/on/topped/served)
  L3  same dish form + same main ingredient, only when name/ingredient similarity is high enough
Within a level the donor with the best 0.6*name_jaccard + 0.4*ingredient_jaccard wins
(ties: more reviews). Name-based only; vector confirmation can be added later.

Usage (run from project/):
  python prototype-1.2/scripts/build_image_fallback.py prepare
  python prototype-1.2/scripts/build_image_fallback.py match 0 120000
  python prototype-1.2/scripts/build_image_fallback.py finalize
"""
import json, os, pickle, random, re, sys, html
from collections import defaultdict

DATA = 'data/recipes.parquet'
OUT_DIR = 'data/derived'
CACHE = os.path.expanduser('~/work/image_fallback_cache')
VERSION = 'image_fallback_v2'
MAX_DONORS = 60          # donors kept per key (most-reviewed first)
L3_MIN_SCORE = 0.35      # L3 only when similarity is convincing
# Head phrases too broad to identify a dish; they skip L2.
GENERIC_HEADS = {'chicken dinner', 'easy dinner', 'main dish', 'side dish', 'one dish', 'dish meal', 'family dinner',
                 'weeknight dinner', 'quick dinner', 'dinner idea', 'party food', 'lunch box', 'kid friendly', 'game day'}

ADJ = set('easy best quick simple simply super ultimate perfect classic basic homemade home made healthy healthier low fat lowfat '
          'light lite delicious yummy tasty amazing awesome favorite favourite my our the a an and of for style old fashioned '
          'fashion fabulous famous special mom moms grandma grandmas nana nanas new great real really good fast minute minutes '
          'crock pot crockpot slow cooker oven baked recipe'.split())
CUT = re.compile(r'\b(with|in|over|on|topped|served|w)\b')
FORMS = [('stirfry', r'\bstir ?fr(y|ied)\b|\bwok\b'), ('soup', r'\b(soup|stew|chowder|chili|bisque|gumbo)\b'),
         ('salad', r'\bsalad\b'), ('pasta', r'\b(pasta|spaghetti|lasagna|penne|noodles?|macaroni|fettuccine|ravioli)\b'),
         ('drink', r'\b(smoothie|shake|juice|punch|lemonade|cocktail|martini|tea|coffee)\b'),
         ('sandwich', r'\b(sandwich|burger|wrap|panini|sliders?)\b'), ('cake', r'\b(cake|cupcakes?|cheesecake)\b'),
         ('cookie', r'\b(cookies?|brownies?|bars?)\b'), ('pie', r'\b(pie|tart|cobbler|crisp)\b'),
         ('bread', r'\b(bread|muffins?|rolls?|biscuits?|scones?|loaf)\b'), ('casserole', r'\b(casserole|bake|gratin)\b'),
         ('rice', r'\b(rice|risotto|pilaf|paella)\b'), ('sauce', r'\b(sauce|dressing|marinade|dip|salsa|gravy)\b'),
         ('breakfast', r'\b(pancakes?|waffles?|omelet+e?|frittata|french toast)\b'), ('curry', r'\bcurry\b'),
         ('pizza', r'\bpizza\b'), ('taco', r'\b(tacos?|burritos?|enchiladas?|quesadillas?|fajitas?)\b')]
MAIN = ('chicken beef pork turkey lamb shrimp salmon tuna fish crab sausage bacon ham tofu bean lentil potato broccoli spinach '
        'mushroom zucchini corn tomato apple banana strawberry blueberry lemon orange pumpkin chocolate peanut cheese egg rice '
        'pasta cabbage carrot cauliflower eggplant pineapple cherry coconut oat').split()

def words(text):
    t = str(text).lower(); t = re.sub(r"\b\w+'s\b", ' ', t); t = re.sub(r'\(.*?\)', ' ', t); t = re.sub(r'&\w+;', ' ', t)
    return [w for w in re.sub(r'[^a-z ]', ' ', t).split() if w not in ADJ and len(w) > 1]

def sing(w):
    return w[:-3] + 'y' if w.endswith('ies') else w[:-2] if w.endswith(('oes', 'ches', 'shes')) else w[:-1] if w.endswith('s') and not w.endswith('ss') else w

def head(name):
    t = str(name).lower(); t = re.sub(r'\(.*?\)', ' ', t)
    m = CUT.search(t)
    w = [sing(x) for x in words(t[:m.start()] if m and m.start() > 0 else t)]
    key = ' '.join(w[-2:]) if len(w) >= 2 else None
    return None if key in GENERIC_HEADS else key

def base_name(name):
    """Name before with/in/over...: the dish itself, not its sauce or topping."""
    t = re.sub(r'\(.*?\)', ' ', str(name).lower()); m = CUT.search(t)
    return t[:m.start()] if m and m.start() > 0 else t

def form(name):
    n = str(name).lower()
    return next((f for f, p in FORMS if re.search(p, n)), None)

def parts(raw):
    return [p.strip().lower() for p in re.findall(r'"([^"]*)"', str(raw))] or ([str(raw).strip().lower()] if raw and str(raw) not in ('character(0)', 'None', 'nan') else [])

def main_ing(ws, ps):
    for w in ws + [x for p in ps for x in p.split()]:
        if sing(w) in MAIN: return sing(w)
    return None

def first_url(raw):
    m = re.search(r'https?://[^"\s]+', str(raw)); return m.group(0) if m else None

def jac(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0

def prepare():
    import pyarrow.parquet as pq
    t = pq.read_table(DATA, columns=['recipeid', 'name', 'images', 'recipeingredientparts', 'reviewcount']).to_pydict()
    rows = []
    for rid, name, img, ing, rc in zip(t['recipeid'], t['name'], t['images'], t['recipeingredientparts'], t['reviewcount']):
        ws = [sing(w) for w in words(name)]; ps = parts(ing); f = form(base_name(name)); m = main_ing([sing(w) for w in words(base_name(name))], ps)
        rows.append(dict(id=rid, name=name, url=first_url(img), ws=frozenset(ws), ing=frozenset(ps), rc=rc or 0,
                         k1=' '.join(ws) or None, k2=head(name), k3=f'{f}|{m}' if f and m else None))
    donors = {k: defaultdict(list) for k in ('k1', 'k2', 'k3')}
    for r in rows:
        if r['url']:
            for k in donors:
                if r[k]: donors[k][r[k]].append(r)
    for k in donors:
        for key, lst in donors[k].items():
            lst.sort(key=lambda r: -r['rc']); del lst[MAX_DONORS:]
    targets = [r for r in rows if not r['url']]
    os.makedirs(CACHE, exist_ok=True)
    for f in os.listdir(CACHE):
        if f.startswith('part_'): os.remove(f'{CACHE}/{f}')  # stale parts from an earlier run
    with open(f'{CACHE}/prep.pkl', 'wb') as fh: pickle.dump(dict(donors={k: dict(v) for k, v in donors.items()}, targets=targets, total=len(rows)), fh)
    print(json.dumps(dict(total=len(rows), targets=len(targets), donor_keys={k: len(v) for k, v in donors.items()})))

def match(start, end):
    with open(f'{CACHE}/prep.pkl', 'rb') as fh: d = pickle.load(fh)
    donors, out = d['donors'], []
    for r in d['targets'][start:end]:
        hit = None
        for level, k in (('L1', 'k1'), ('L2', 'k2'), ('L3', 'k3')):
            cands = donors[k].get(r[k]) if r[k] else None
            if not cands: continue
            best = max(cands, key=lambda c: (0.6 * jac(r['ws'], c['ws']) + 0.4 * jac(r['ing'], c['ing']), c['rc']))
            ns, ig = jac(r['ws'], best['ws']), jac(r['ing'], best['ing'])
            score = round(0.6 * ns + 0.4 * ig, 3)
            if level == 'L3' and score < L3_MIN_SCORE: continue
            hit = dict(recipeid=r['id'], name=r['name'], level=level, key=r[k], image_recipeid=best['id'], image_name=best['name'],
                       image_url=best['url'], score=score, name_sim=round(ns, 3), ingredient_sim=round(ig, 3), version=VERSION)
            break
        out.append(hit or dict(recipeid=r['id'], name=r['name'], level=None, version=VERSION))
    with open(f'{CACHE}/part_{start:07d}.jsonl', 'w') as fh:
        for o in out: fh.write(json.dumps(o, ensure_ascii=False) + '\n')
    print(start, end, len(out))

def finalize():
    files = sorted(f for f in os.listdir(CACHE) if f.startswith('part_'))
    rows = [json.loads(l) for f in files for l in open(f'{CACHE}/{f}')]
    mapped = [r for r in rows if r['level']]
    with open(f'{OUT_DIR}/{VERSION}.jsonl', 'w') as fh:
        for r in mapped: fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    lv = defaultdict(int)
    for r in mapped: lv[r['level']] += 1
    reuse = defaultdict(int)
    for r in mapped: reuse[r['image_recipeid']] += 1
    stats = dict(version=VERSION, targets=len(rows), mapped=len(mapped), mapped_pct=round(100 * len(mapped) / len(rows), 1),
                 by_level=dict(lv), unmapped=len(rows) - len(mapped), distinct_donor_images=len(reuse),
                 max_reuse_of_one_image=max(reuse.values()), l3_min_score=L3_MIN_SCORE, max_donors_per_key=MAX_DONORS)
    json.dump(stats, open(f'{OUT_DIR}/{VERSION}_stats.json', 'w'), indent=1)
    random.seed(25)
    sample = [r for lvl in ('L1', 'L2', 'L3') for r in random.sample([m for m in mapped if m['level'] == lvl], 20)]
    cards = ''.join(f'<figure class="{html.escape(r["level"])}"><img loading="lazy" src="{html.escape(r["image_url"])}" alt="">'
                    f'<figcaption><b>{html.escape(r["name"])}</b><br>→ {html.escape(r["image_name"])}<br>'
                    f'<span>{r["level"]} · score {r["score"]} · name {r["name_sim"]} · ingr {r["ingredient_sim"]}</span>'
                    f'<label><input type="checkbox"> 图不合适</label></figcaption></figure>' for r in sample)
    page = ('<!doctype html><meta charset="utf-8"><title>Image fallback review</title><style>body{font:14px system-ui;margin:24px;background:#f5f2ea}'
            'main{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}figure{margin:0;background:#fff;border:1px solid #ddd;border-radius:8px;overflow:hidden}'
            'img{width:100%;height:160px;object-fit:cover;background:#eee}figcaption{padding:10px;line-height:1.45}span{color:#666;font-size:12px}'
            'label{display:block;margin-top:6px;color:#9a3b1b}h2{margin:28px 0 8px}</style>'
            f'<h1>借图映射抽查（{len(sample)} 条：L1 / L2 / L3 各 20）</h1><p>上面是缺图的菜名，→ 后是借图来源。勾选「图不合适」后数一下各层错误数。</p><main>{cards}</main>')
    open(f'{OUT_DIR}/{VERSION}_review.html', 'w').write(page)
    import sqlite3
    import shutil, tempfile
    db = os.path.join(tempfile.mkdtemp(), f'{VERSION}.sqlite')  # build locally; some synced folders break SQLite locking
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE fallback (recipeid INTEGER PRIMARY KEY, image_url TEXT NOT NULL, level TEXT, score REAL, image_recipeid INTEGER, image_name TEXT)')
    con.executemany('INSERT INTO fallback VALUES (?,?,?,?,?,?)', [(r['recipeid'], r['image_url'], r['level'], r['score'], r['image_recipeid'], r['image_name']) for r in mapped])
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)"); con.execute("INSERT INTO meta VALUES ('version', ?)", (VERSION,))
    con.commit(); con.close()
    shutil.copyfile(db, f'{OUT_DIR}/{VERSION}.sqlite')
    print(json.dumps(stats, ensure_ascii=False))

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'prepare': prepare()
    elif cmd == 'match': match(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == 'finalize': finalize()
