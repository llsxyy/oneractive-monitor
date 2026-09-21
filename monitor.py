import json, os, requests

BASE = "https://www.oneractive.com"
WATCH_SIZES = ["XS", "S", "M", "L"]   # 只盯這些尺寸，[] 代表全部
KEYWORDS = ["timeless", "everyday", "unified"]              # 例如 ["leggings", "bra"]，[] 代表全部商品
EXCLUDE = ["gift card"]    # 排除的關鍵字
NOTIFY_NEW = True          # 是否通知新品

BOT_TOKEN = os.environ["TG_TOKEN"]
CHAT_ID = os.environ["TG_CHAT"]
STATE = "state.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_all():
    products, page = [], 1
    while True:
        r = requests.get(
            f"{BASE}/products.json",
            params={"limit": 250, "page": page},
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        batch = r.json()["products"]
        if not batch:
            break
        products += batch
        page += 1
    return products

def send(text):
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) > 3500:
            post(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        post(chunk)

def post(msg):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg},
        timeout=15,
    )
    r.raise_for_status()

def size_ok(variant_title):
    if not WATCH_SIZES or variant_title == "Default Title":
        return True
    parts = variant_title.split(" / ")
    return any(s in parts for s in WATCH_SIZES)

def match(p):
    tags = p.get("tags", [])
    if isinstance(tags, list):
        tags = " ".join(tags)
    text = f"{p['title']} {p.get('product_type', '')} {tags}".lower()
    if any(x in text for x in EXCLUDE):
        return False
    return not KEYWORDS or any(k in text for k in KEYWORDS)

def main():
    first_run = not os.path.exists(STATE)
    state = {"seen": [], "stock": {}} if first_run else json.load(open(STATE))
    seen = set(state["seen"])
    prev_stock = state["stock"]

    products = fetch_all()
    new_stock, new_items, restocks = {}, [], {}

    for p in products:
        pid = str(p["id"])
        url = f"{BASE}/products/{p['handle']}"
        if NOTIFY_NEW and not first_run and pid not in seen and match(p):
            new_items.append((p["title"], url))
        seen.add(pid)

        for v in p["variants"]:
            vid = str(v["id"])
            new_stock[vid] = v["available"]
            if first_run or not match(p):
                continue
            if v["available"] and prev_stock.get(vid) is False and size_ok(v["title"]):
                restocks.setdefault((p["title"], url), []).append(v["title"])

    lines = []
    if restocks:
        lines.append(f"補貨了（{len(restocks)} 件）")
        for (title, url), vs in restocks.items():
            lines.append(f"{title}\n{', '.join(vs)}\n{url}\n")
    if new_items:
        lines.append(f"新品（{len(new_items)} 件）")
        for title, url in new_items:
            lines.append(f"{title}\n{url}\n")
    if lines:
        send("\n".join(lines))

    json.dump({"seen": sorted(seen), "stock": new_stock}, open(STATE, "w"))
    print(f"完成。檢查了 {len(products)} 件商品，補貨 {len(restocks)} 件，新品 {len(new_items)} 件。")

main()
