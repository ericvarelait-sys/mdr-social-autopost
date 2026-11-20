import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ARG_TZ = timezone(timedelta(hours=-3))
GRAPH_BASE = "https://graph.facebook.com/v21.0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_PATH = os.path.join(ROOT, "schedule.json")
STATE_PATH = os.path.join(ROOT, "state.json")


def api_request(method, url, data=None):
    encoded = urllib.parse.urlencode(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=encoded, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {err.code} on {url}: {body}") from err


def api_get(path, params):
    url = f"{GRAPH_BASE}/{path}?{urllib.parse.urlencode(params)}"
    return api_request("GET", url)


def api_post(path, params):
    url = f"{GRAPH_BASE}/{path}"
    return api_request("POST", url, data=params)


def verify_url_reachable(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Image URL returned HTTP {resp.status}: {url}")


def wait_ig_container(creation_id, token, timeout_sec=90):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        res = api_get(creation_id, {"fields": "status_code,status", "access_token": token})
        code = res.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise RuntimeError(f"IG container {creation_id} failed: {res}")
        time.sleep(3)
    raise TimeoutError(f"IG container {creation_id} did not finish within {timeout_sec}s")


def publish_instagram(item, image_urls, ig_id, token):
    if item["type"] == "story":
        res = api_post(f"{ig_id}/media", {
            "image_url": image_urls[0],
            "media_type": "STORIES",
            "access_token": token,
        })
        cid = res["id"]
        wait_ig_container(cid, token)
        pub = api_post(f"{ig_id}/media_publish", {"creation_id": cid, "access_token": token})
        return pub["id"]

    caption = item.get("caption", "")
    if len(image_urls) == 1:
        res = api_post(f"{ig_id}/media", {
            "image_url": image_urls[0],
            "caption": caption,
            "access_token": token,
        })
        cid = res["id"]
        wait_ig_container(cid, token)
        pub = api_post(f"{ig_id}/media_publish", {"creation_id": cid, "access_token": token})
        return pub["id"]

    child_ids = []
    for img_url in image_urls[:10]:
        child = api_post(f"{ig_id}/media", {
            "image_url": img_url,
            "is_carousel_item": "true",
            "access_token": token,
        })
        cid = child["id"]
        wait_ig_container(cid, token)
        child_ids.append(cid)

    parent = api_post(f"{ig_id}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": token,
    })
    pid = parent["id"]
    wait_ig_container(pid, token)
    pub = api_post(f"{ig_id}/media_publish", {"creation_id": pid, "access_token": token})
    return pub["id"]


def get_page_token(page_id, system_token):
    res = api_get(page_id, {"fields": "access_token", "access_token": system_token})
    return res.get("access_token") or system_token


def publish_facebook(item, image_urls, page_id, page_token):
    if item["type"] == "story":
        up = api_post(f"{page_id}/photos", {
            "url": image_urls[0],
            "published": "false",
            "access_token": page_token,
        })
        st = api_post(f"{page_id}/photo_stories", {
            "photo_id": up["id"],
            "access_token": page_token,
        })
        return st.get("post_id") or up["id"]

    caption = item.get("caption", "")
    if len(image_urls) == 1:
        res = api_post(f"{page_id}/photos", {
            "url": image_urls[0],
            "message": caption,
            "published": "true",
            "access_token": page_token,
        })
        return res.get("post_id") or res["id"]

    attached = []
    for img_url in image_urls:
        up = api_post(f"{page_id}/photos", {
            "url": img_url,
            "published": "false",
            "access_token": page_token,
        })
        attached.append({"media_fbid": up["id"]})

    feed = api_post(f"{page_id}/feed", {
        "message": caption,
        "attached_media": json.dumps(attached),
        "access_token": page_token,
    })
    return feed["id"]


def find_pending_items(schedule, published_map, now, force_id="", lookahead_min=45):
    due = []
    upcoming = []
    for item in schedule.get("items", []):
        iid = item["id"]
        rec = published_map.get(iid, {})
        if rec.get("ig_id") and rec.get("fb_id"):
            continue

        if force_id:
            if iid == force_id:
                due.append(item)
            continue

        sched_dt = datetime.fromisoformat(item["scheduled_at"])
        delta = now - sched_dt
        if timedelta(0) <= delta <= timedelta(hours=36):
            due.append(item)
        elif timedelta(0) < (sched_dt - now) <= timedelta(minutes=lookahead_min):
            upcoming.append((sched_dt, item))
    return due, upcoming


def main():
    parser = argparse.ArgumentParser(description="Publicador oficial Meta Graph API")
    parser.add_argument("--check", action="store_true", help="Solo mostrar qué toca publicar sin enviar a Meta")
    parser.add_argument("--force-id", default="", help="Publicar manualmente un ID específico (ej. M01 o H01)")
    args = parser.parse_args()

    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        schedule = json.load(f)
    with open(STATE_PATH, encoding="utf-8") as f:
        state = json.load(f)

    published_map = state.setdefault("published", {})
    base_url = os.environ.get("MEDIA_BASE_URL", schedule.get("media_base_url", "")).rstrip("/") + "/"
    now = datetime.now(ARG_TZ)

    due_items, upcoming_items = find_pending_items(schedule, published_map, now, args.force_id)

    if not due_items and upcoming_items and not args.check:
        upcoming_items.sort(key=lambda x: x[0])
        target_dt, target_item = upcoming_items[0]
        wait_sec = max(0, (target_dt - datetime.now(ARG_TZ)).total_seconds()) + 2
        print(f"[{now.isoformat()}] Despertado antes de tiempo. Esperando {int(wait_sec)}s hasta {target_dt.isoformat()} para {target_item['id']}...")
        time.sleep(wait_sec)
        now = datetime.now(ARG_TZ)
        due_items, _ = find_pending_items(schedule, published_map, now, args.force_id)

    if not due_items:
        msg = f"[{now.isoformat()}] Nada pendiente por publicar ahora."
        if args.check and upcoming_items:
            msg += f" Próximo en ventana (<45m): {[(x[1]['id'], x[0].isoformat()) for x in upcoming_items]}"
        print(msg)
        return 0

    print(f"[{now.isoformat()}] Items a procesar: {[x['id'] for x in due_items]}")
    if args.check:
        for item in due_items:
            print(f" - {item['id']} ({item['type']}) programado {item['scheduled_at']} | {len(item['images'])} img")
        return 0

    token = os.environ.get("META_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta la variable de entorno META_TOKEN")

    fb_page_id = os.environ.get("FB_PAGE_ID", schedule.get("fb_page_id", "108748417283325"))
    ig_user_id = os.environ.get("IG_USER_ID", schedule.get("ig_user_id", "17841427135524717"))
    page_token = get_page_token(fb_page_id, token)

    had_error = False
    for item in due_items:
        iid = item["id"]
        rec = published_map.setdefault(iid, {})
        urls = [base_url + rel.lstrip("/") for rel in item["images"]]

        print(f"Verificando URLs para {iid}...")
        for u in urls:
            verify_url_reachable(u)

        if not rec.get("ig_id"):
            try:
                ig_id_res = publish_instagram(item, urls, ig_user_id, token)
                rec["ig_id"] = ig_id_res
                rec["ig_published_at"] = datetime.now(ARG_TZ).isoformat()
                print(f"OK Instagram {iid} -> {ig_id_res}")
            except Exception as exc:
                had_error = True
                rec["ig_error"] = str(exc)
                print(f"ERROR Instagram {iid}: {exc}", file=sys.stderr)

        if not rec.get("fb_id"):
            try:
                fb_id_res = publish_facebook(item, urls, fb_page_id, page_token)
                rec["fb_id"] = fb_id_res
                rec["fb_published_at"] = datetime.now(ARG_TZ).isoformat()
                print(f"OK Facebook {iid} -> {fb_id_res}")
            except Exception as exc:
                had_error = True
                rec["fb_error"] = str(exc)
                print(f"ERROR Facebook {iid}: {exc}", file=sys.stderr)

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
