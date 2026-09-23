import json, os, re, time, requests

BASE = "https://gymsharkusa.myshopify.com"
SHOP = "https://www.gymshark.com"
COLLECTION = "last-chance"
MAX_PRICE = 25                    # 只盯低於這個價錢（美元）
SIZES = {"Womens": ["XS", "S", "M"], "Mens": ["S", "M", "L"]}
NOTIFY_NEW = True
NOTIFY_RESTOCK = True
NEW_ONLY_IF_MY_SIZE = True       # True：新品只在有你的尺寸時才通知
MAX_ITEMS = 40
LABEL = "Gymshark 清倉"
GENDER_NAME = {"Womens": "女", "Mens": "男"}

BOT_TOKEN = os.environ.get("TG_TOKEN_2") or os.environ["TG_TOKEN"]
CHAT_ID = os.environ["TG_CHAT"]
STATE = "state_gymshark.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}
ACC_RE = re.compile(
    r"\b(holdall|duffel|duffle|backpack|tote|bottle|shaker|socks?|caps?|beanie|gloves?|straps?|belt|towel|bags?)\b",
    re.I,
)

def get(url, params):
    r = None
    for i in range(3):
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(5 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()

def fetch_all():
    products, page = [], 1
    while page <= 40:
        data = get(f"{BASE}/collections/{COLLECTION}/products.json",
                   {"limit": 250, "page": page})
        batch = data.get("products", [])
        if not batch:
            break
        products += batch
        page += 1
        time.sleep(0.5)
    return products

def tags_of(p):
    t = p.get("tags", [])
    if isinstance(t, str):
        t = [x.strip() for x in t.split(",")]
    return t

def genders(p):
    t = tags_of(p)
    return [g for g in SIZES if g in t]

def is_accessory(p):
    divs = [t for t in tags_of(p) if t.lower().startswith("division:")]
    if divs:
        return not any(d.lower() == "division:apparel" for d in divs)
    return bool(ACC_RE.search(p.get("title", "")))

def best_price(p):
    best = None
    for v in p.get("variants", []):
        try:
            pr = float(v["price"])
        except (TypeError, ValueError, KeyError):
            continue
        if best is None or pr < best[0]:
            best = (pr, v.get("compare_at_price"))
    return best

def info_text(best):
    s = f"USD {best[0]:.2f}"
    try:
        if best[1]:
            s += f"（原價 USD {float(best[1]):.2f}）"
    except (TypeError, ValueError):
        pass
    return s

def wanted_sizes(p):
    s = set()
    for g in genders(p):
        s.update(SIZES[g])
    return s

SIZE_MAP = {
    "XXS": "XXS", "EXTRA EXTRA SMALL": "XXS",
    "XS": "XS", "EXTRA SMALL": "XS",
    "S": "S", "SMALL": "S",
    "M": "M", "MEDIUM": "M",
    "L": "L", "LARGE": "L",
    "XL": "XL", "EXTRA LARGE": "XL",
    "XXL": "XXL", "EXTRA EXTRA LARGE": "XXL",
}

def norm_size(t):
    return SIZE_MAP.get(t.strip().upper())

def size_ok(p, title):
    parts = [x.strip() for x in title.split(" / ")]
    if title in ("Default Title", "One Size") or "One Size" in parts:
        return True
    want = wanted_sizes(p)
    for x in parts:
        n = norm_size(x)
        if n and n in want:
            return True
    return False

def label_of(p):
    return "/".join(GENDER_NAME[g] for g in genders(p))

def post(msg):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": "true"},
        timeout=15,
    )
    r.raise_for_status()

def send(text):
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) > 3500:
            post(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        post(chunk)

def main():
    first_run = not os.path.exists(STATE)
    state = {"seen": [], "stock": {}} if first_run else json.load(open(STATE))
    seen = set(state["seen"])
    prev_stock = state["stock"]
    new_stock = {}

    products = fetch_all()
    if not products:
        raise SystemExit("沒有抓到任何商品，這次略過。")

    new_items, restocks = [], {}
    n_rel = n_cheap = n_acc = 0
    acc_sample = []

    for p in products:
        if not genders(p):
            continue
        if is_accessory(p):
            n_acc += 1
            if len(acc_sample) < 8:
                acc_sample.append(p["title"])
            continue
        n_rel += 1

        pid = str(p["id"])
        url = f"{SHOP}/products/{p['handle']}"
        variants = p.get("variants", [])
        best = best_price(p)
        cheap = best is not None and best[0] < MAX_PRICE
        is_new = cheap and pid not in seen
        info = info_text(best) if best else "?"

        for v in variants:
            vid = str(v["id"])
            avail = bool(v["available"])
            if (cheap and not is_new and NOTIFY_RESTOCK and not first_run
                    and avail and prev_stock.get(vid) is False and size_ok(p, v["title"])):
                restocks.setdefault((label_of(p), p["title"], info, url), []).append(v["title"])
            if cheap:
                new_stock[vid] = avail

        if cheap:
            n_cheap += 1
            if is_new:
                if NOTIFY_NEW and not first_run:
                    avail_sizes = [v["title"] for v in variants if v["available"]]
                    mine = [x for x in avail_sizes if size_ok(p, x)]
                    if not NEW_ONLY_IF_MY_SIZE or mine:
                        new_items.append((label_of(p), p["title"], info,
                                          ", ".join(avail_sizes) or "暫無", url))
                seen.add(pid)

    lines = []
    if restocks:
        lines.append(f"【{LABEL}】補貨 {len(restocks)} 件（低於 ${MAX_PRICE}）\n")
        for i, ((g, title, info, url), sizes) in enumerate(restocks.items()):
            if i >= MAX_ITEMS:
                lines.append(f"…另有 {len(restocks) - MAX_ITEMS} 件")
                break
            lines.append(f"[{g}] {title}\n{info}\n尺寸：{', '.join(sizes)}\n{url}\n")
    if new_items:
        lines.append(f"【{LABEL}】新品 {len(new_items)} 件（低於 ${MAX_PRICE}）\n")
        for i, (g, title, info, sizes, url) in enumerate(new_items):
            if i >= MAX_ITEMS:
                lines.append(f"…另有 {len(new_items) - MAX_ITEMS} 件")
                break
            lines.append(f"[{g}] {title}\n{info}\n有貨尺寸：{sizes}\n{url}\n")
    if lines:
        send("\n".join(lines))

    json.dump({"seen": sorted(seen), "stock": new_stock}, open(STATE, "w"))
    print(f"完成。非配件 {n_rel} 件，低於 ${MAX_PRICE} 的 {n_cheap} 件，排除配件 {n_acc} 件。補貨 {len(restocks)} 件，新品 {len(new_items)} 件。")
    if first_run and acc_sample:
        print("被排除的配件範例：", acc_sample)

main()
