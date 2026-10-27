# SUKUNA VISIT API SRC
# POWERED BY : @minister_69
# REMADE BY : @itz_me_R_Sukuna
# CHANNEL : @ryomen_sukuna_sg
# tokens are AUTO-GENERATED (JWT API) + SMART-REFRESHED
# instead of being read blindly from token_*.json.
from flask import Flask, jsonify, request
import aiohttp
import asyncio
import json
import os
import time
import threading
import jwt
from datetime import datetime, timezone, timedelta

from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info

app = Flask(__name__)

# ===================== JWT / TOKEN CONFIG =====================
JWT_API = "https://jat-iota.vercel.app/token"

# Account files (uid:password per line) and token cache files (per server group)
ACCOUNT_FILES = {
    "IND": "account_ind.txt",
    "BR":  "account_br.txt",
    "BD":  "account_bd.txt",
    "RU":  "account_ru.txt",
}
TOKEN_FILES = {
    "IND": "token_ind.json",
    "BR":  "token_br.json",
    "BD":  "token_bd.json",
    "RU":  "token_ru.json",
}

# Used only to recognise which region a token's login_url belongs to
REGION_KEYS = {"IND", "BR", "US", "SAC", "NA", "BD", "RU"}

JWT_CONCURRENCY    = 50
JWT_TIMEOUT        = 30
CHECK_INTERVAL_MIN = 30    # background check every 30 min
TOKEN_MIN_VALIDITY = 1800  # refresh if less than 30 min left

TOKEN_CACHE = {}           # uid -> {token, expires_at, login_url, region, fetched_at}
_file_lock = threading.Lock()
_sched_lock = threading.Lock()
_sched_started = False


# ===================== SERVER -> FILE GROUP =====================
def server_group(server_name):
    """Maps any server name to one of the account/token file groups."""
    if server_name == "IND":
        return "IND"
    if server_name in {"BR", "US", "SAC", "NA"}:
        return "BR"
    if server_name == "RU":
        return "RU"
    return "BD"  # BD, ME, PK, TH, VN, ID ...


# ===================== ACCOUNT FILE LOADING =====================
def is_placeholder(u, p):
    bad = {"uid", "password", "user", "pass", "your_uid", "your_password"}
    return u.lower() in bad or p.lower() in bad


def load_file(fn):
    accs, seen = [], set()
    if not os.path.exists(fn):
        return accs
    try:
        with open(fn) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                u, p = line.split(":", 1)
                u, p = u.strip(), p.strip()
                if not u or not p or is_placeholder(u, p):
                    continue
                if u not in seen:
                    seen.add(u)
                    accs.append({"uid": u, "password": p})
    except Exception:
        pass
    return accs


def load_accounts(server_name):
    """Primary account file for the server group, with fallback to the others."""
    grp = server_group(server_name)
    primary = ACCOUNT_FILES[grp]
    accs = load_file(primary)
    if accs:
        return accs
    for fb in ACCOUNT_FILES.values():
        if fb == primary:
            continue
        accs = load_file(fb)
        if accs:
            app.logger.warning(f"⚠️ Fallback: loaded {len(accs)} accounts from {fb} for {server_name}")
            return accs
    return []


def load_accounts_by_file():
    result = {}
    for grp, fn in ACCOUNT_FILES.items():
        a = load_file(fn)
        if a:
            result[grp] = a
    return result


# ===================== TOKEN VALIDITY HELPERS =====================
def token_time_left(uid):
    c = TOKEN_CACHE.get(uid)
    if not c:
        return -1
    try:
        return (c["expires_at"] - datetime.now(timezone.utc)).total_seconds()
    except Exception:
        return -1


def token_is_valid(uid):
    return token_time_left(uid) > TOKEN_MIN_VALIDITY


def _jwt_expiry(token):
    try:
        p = jwt.decode(token, options={"verify_signature": False})
        return datetime.fromtimestamp(p["exp"], tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc) + timedelta(hours=8)


# ===================== TOKEN FILE SAVE / LOAD =====================
def save_tokens_for_group(grp, uids):
    fname = TOKEN_FILES.get(grp)
    if not fname:
        return False
    try:
        tokens = {}
        for uid in uids:
            c = TOKEN_CACHE.get(uid)
            if not c:
                continue
            tokens[uid] = {
                "token": c.get("token"),
                "expires_at": c["expires_at"].isoformat(),
                "login_url": c.get("login_url"),
                "region": c.get("region"),
                "fetched_at": c.get("fetched_at"),
            }
        data = {
            "server": grp,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(tokens),
            "tokens": tokens,
        }
        with _file_lock:
            tmp = fname + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, fname)  # atomic, no half-written file
        print(f"💾 Saved {len(tokens)} tokens → {fname}")
        return True
    except Exception as e:
        print(f"⚠️ Failed to save {fname}: {e}")
        return False


def load_tokens_from_file(grp):
    """
    Loads cached tokens into TOKEN_CACHE, skipping expired ones.
    Understands the new format ({"tokens": {uid: {...}}}) and the old
    list format ([{"token": "..."}]) — expiry is read from the JWT itself.
    """
    fname = TOKEN_FILES.get(grp)
    if not fname or not os.path.exists(fname):
        return 0
    try:
        with open(fname) as f:
            data = json.load(f)
        now = datetime.now(timezone.utc)
        loaded = skipped = 0

        if isinstance(data, dict):
            items = (data.get("tokens") or {}).items()
        else:  # legacy list format, no uid -> key by token tail
            items = ((f"legacy_{grp}_{i}", it) for i, it in enumerate(data) if isinstance(it, dict))

        for uid, c in items:
            try:
                tok = c.get("token")
                if not tok or tok == "N/A":
                    continue
                if c.get("expires_at"):
                    exp = datetime.fromisoformat(c["expires_at"])
                else:
                    exp = _jwt_expiry(tok)
                if (exp - now).total_seconds() > TOKEN_MIN_VALIDITY:
                    TOKEN_CACHE[uid] = {
                        "token": tok,
                        "expires_at": exp,
                        "login_url": c.get("login_url"),
                        "region": c.get("region"),
                        "fetched_at": c.get("fetched_at", time.time()),
                    }
                    loaded += 1
                else:
                    skipped += 1
            except Exception:
                continue
        print(f"📂 Loaded {loaded} tokens from {fname} (skipped {skipped} expired)")
        return loaded
    except Exception as e:
        print(f"⚠️ Failed to load {fname}: {e}")
        return 0


def load_all_tokens_from_files():
    return sum(load_tokens_from_file(g) for g in TOKEN_FILES)


# ===================== AUTO JWT GENERATION =====================
async def fetch_raw(session, uid, pwd):
    try:
        url = f"{JWT_API}?uid={uid}&password={pwd}"
        async with session.get(url, timeout=JWT_TIMEOUT) as r:
            if r.status != 200:
                return None
            d = await r.json()
            if not isinstance(d, dict) or not d.get("Success", True):
                return None
            return d
    except Exception:
        return None


async def get_valid_token(session, uid, pwd, force=False):
    """Cached token if still valid, otherwise generates a fresh JWT."""
    if not force and token_is_valid(uid):
        return TOKEN_CACHE[uid]["token"]

    d = await fetch_raw(session, uid, pwd)
    if not d:
        return None
    t = d.get("Jwt_Token") or d.get("jwt_token") or d.get("token")
    if not t or t == "N/A":
        return None
    TOKEN_CACHE[uid] = {
        "token": t,
        "expires_at": _jwt_expiry(t),
        "login_url": d.get("Login_url"),
        "region": d.get("Region"),
        "fetched_at": time.time(),
    }
    return t


def region_of(login_url, region_field):
    if region_field:
        r = str(region_field).upper()
        if r in REGION_KEYS:
            return r
    if not login_url:
        return None
    l = login_url.lower()
    if "client.ind" in l: return "IND"
    if "client.us" in l:  return "US"
    if "client.ru" in l:  return "RU"
    if "clientbp" in l or "client.bd" in l: return "BD"
    return None


def region_matches(acc_region, target):
    if not acc_region:
        return True
    if target == "IND": return acc_region == "IND"
    if target == "BD":  return acc_region == "BD"
    if target == "RU":  return acc_region == "RU"
    if target in {"BR", "US", "SAC", "NA"}:
        return acc_region in {"BR", "US", "SAC", "NA"}
    return True


async def prewarm_tokens(accs, server=None, force=False):
    """
    Smart prewarm: only generates tokens that are missing / expired /
    about to expire. Returns (valid_accounts, fetched_count).
    """
    need_fetch, already_valid = [], []
    for a in accs:
        if not force and token_is_valid(a["uid"]):
            already_valid.append(a)
        else:
            need_fetch.append(a)

    tag = server or "ALL"
    print(f"🔎 Prewarm[{tag}]: {len(already_valid)} cached valid, {len(need_fetch)} need fetch")

    valid_fetched = []
    if need_fetch:
        sem = asyncio.Semaphore(JWT_CONCURRENCY)
        connector = aiohttp.TCPConnector(limit=JWT_CONCURRENCY * 2, force_close=False)
        timeout = aiohttp.ClientTimeout(total=JWT_TIMEOUT)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async def one(a):
                async with sem:
                    t = await get_valid_token(session, a["uid"], a["password"], force=force)
                    return a if t else None
            results = await asyncio.gather(*[one(a) for a in need_fetch], return_exceptions=True)
        valid_fetched = [r for r in results if isinstance(r, dict)]

    combined = already_valid + valid_fetched

    if server is not None:
        combined = [
            a for a in combined
            if region_matches(
                region_of((TOKEN_CACHE.get(a["uid"]) or {}).get("login_url"),
                          (TOKEN_CACHE.get(a["uid"]) or {}).get("region")),
                server,
            )
        ]

    print(f"✅ Prewarm[{tag}]: {len(combined)}/{len(accs)} valid")
    return combined, len(valid_fetched)


# ===================== SMART TOKEN LOADER (replaces old load_tokens) =====================
def load_tokens(server_name):
    """
    Returns (tokens_list, count) for a server.
      1. Reads account file for the server group
      2. Uses cached tokens that are still valid
      3. Auto-generates JWTs only for missing/expired ones
      4. Saves the updated cache to token_*.json
    """
    try:
        ensure_scheduler()
        accs = load_accounts(server_name)
        if not accs:
            app.logger.error(f"❌ No accounts found for {server_name}")
            return [], 0

        valid, fetched = asyncio.run(prewarm_tokens(accs, server=server_name, force=False))

        if fetched:
            grp = server_group(server_name)
            save_tokens_for_group(grp, [a["uid"] for a in accs if a["uid"] in TOKEN_CACHE])

        tokens = [TOKEN_CACHE[a["uid"]]["token"] for a in valid if a["uid"] in TOKEN_CACHE]
        return tokens, len(tokens)
    except Exception as e:
        app.logger.error(f"❌ Token load error for {server_name}: {e}")
        return [], 0


# ===================== BACKGROUND SMART REFRESH =====================
def refresh_expired_tokens():
    """Re-generates only tokens that are missing or expiring within 30 min."""
    grouped = load_accounts_by_file()
    if not grouped:
        print("⚠️ No account files found")
        return 0

    total = 0
    for grp, accs in grouped.items():
        expired = [a for a in accs if not token_is_valid(a["uid"])]
        if not expired:
            print(f"✅ {grp}: all {len(accs)} tokens valid — skip")
            continue

        dead = [a for a in expired if token_time_left(a["uid"]) <= 0]
        print(f"🔄 {grp}: {len(dead)} expired, {len(expired) - len(dead)} expiring soon — refreshing {len(expired)}")

        t0 = time.time()
        valid, _ = asyncio.run(prewarm_tokens(expired, server=None, force=False))
        print(f"✅ {grp} refreshed — {len(valid)}/{len(expired)} valid in {round(time.time() - t0, 2)}s")

        save_tokens_for_group(grp, [a["uid"] for a in accs if a["uid"] in TOKEN_CACHE])
        total += len(valid)
    return total


def scheduler_loop():
    loaded = load_all_tokens_from_files()
    print(f"📂 Total loaded from files: {loaded}")

    if loaded == 0:
        print("⚠️ No cached tokens — initial fetch needed")
        try:
            refresh_expired_tokens()
        except Exception as e:
            print(f"⚠️ Initial fetch failed: {e}")

    while True:
        time.sleep(CHECK_INTERVAL_MIN * 60)
        try:
            print(f"⏰ {CHECK_INTERVAL_MIN}min check — scanning for expired tokens...")
            refresh_expired_tokens()
        except Exception as e:
            print(f"⚠️ Scheduled check failed: {e}")


def ensure_scheduler():
    """Starts the background refresher once (works under python app.py and gunicorn)."""
    global _sched_started
    if _sched_started:
        return
    with _sched_lock:
        if _sched_started:
            return
        _sched_started = True
        threading.Thread(target=scheduler_loop, daemon=True).start()


# ===================== VISIT LOGIC =====================
def get_url(server_name):
    """Returns the correct GetPlayerPersonalShow URL for the server."""
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        # BD, ME, PK, TH, VN, ID – all use this URL
        return "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"


def parse_protobuf_response(response_data):
    try:
        info = Info()
        info.ParseFromString(response_data)

        return {
            "uid": info.AccountInfo.UID if info.AccountInfo.UID else 0,
            "nickname": info.AccountInfo.PlayerNickname if info.AccountInfo.PlayerNickname else "",
            "likes": info.AccountInfo.Likes if info.AccountInfo.Likes else 0,
            "region": info.AccountInfo.PlayerRegion if info.AccountInfo.PlayerRegion else "",
            "level": info.AccountInfo.Levels if info.AccountInfo.Levels else 0,
        }
    except Exception as e:
        app.logger.error(f"❌ Protobuf parsing error: {e}")
        return None


async def visit(session, url, token, uid, data):
    headers = {
        "ReleaseVersion": "OB55",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0],
    }
    try:
        async with session.post(url, headers=headers, data=data, ssl=False) as resp:
            if resp.status == 200:
                return True, await resp.read()
            return False, None
    except Exception as e:
        app.logger.error(f"❌ Visit error: {e}")
        return False, None


async def send_until_1000_success(tokens, uid, server_name, target_success=1000):
    url = get_url(server_name)
    connector = aiohttp.TCPConnector(limit=0)
    total_success = 0
    total_sent = 0
    first_success_response = None
    player_info = None

    async with aiohttp.ClientSession(connector=connector) as session:
        encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
        data = bytes.fromhex(encrypted)

        while total_success < target_success:
            batch_size = min(target_success - total_success, 300)
            tasks = [
                asyncio.create_task(visit(session, url, tokens[(total_sent + i) % len(tokens)], uid, data))
                for i in range(batch_size)
            ]
            results = await asyncio.gather(*tasks)

            if first_success_response is None:
                for success, response in results:
                    if success and response is not None:
                        first_success_response = response
                        player_info = parse_protobuf_response(response)
                        break

            batch_success = sum(1 for r, _ in results if r)
            total_success += batch_success
            total_sent += batch_size

            print(f"Batch sent: {batch_size}, Success in batch: {batch_success}, Total success so far: {total_success}")

    return total_success, total_sent, player_info


@app.route("/visit", methods=["GET"])
def send_visits_query():
    uid = request.args.get("uid")
    server_name = request.args.get("server_name")
    key = request.args.get("key")

    if not uid or not server_name or not key:
        return jsonify({"error": "Missing parameters: uid, server_name, key"}), 400

    if key != "SUKUNA":
        return jsonify({"error": "Invalid API key"}), 401

    try:
        uid_int = int(uid)
    except ValueError:
        return jsonify({"error": "uid must be an integer"}), 400

    server = server_name.upper()

    # Smart load: auto-generates JWTs only where needed
    tokens, token_count = load_tokens(server)

    if not tokens:
        return jsonify({
            "error": "❌ No valid tokens found for server",
            "available_accounts": 0
        }), 500

    target_success = 1000
    print(f"🚀 Sending visits to UID: {uid_int} using {token_count} tokens")
    print(f"Waiting for total {target_success} successful visits...")

    total_success, total_sent, player_info = asyncio.run(
        send_until_1000_success(tokens, uid_int, server, target_success)
    )

    if player_info:
        response = {
            "nickname": player_info.get("nickname", ""),
            "uid": player_info.get("uid", 0),
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "region": player_info.get("region", ""),
            "available_accounts": token_count,
            "total_success": total_success,
            "total_failed": target_success - total_success,
        }
        return jsonify(response), 200
    else:
        return jsonify({
            "error": "Could not decode player information",
            "available_accounts": token_count
        }), 500


if __name__ == "__main__":
    print(f"Token check: every {CHECK_INTERVAL_MIN} min (only expired tokens refresh)")
    print(f"Token files: {list(TOKEN_FILES.values())}")
    ensure_scheduler()
    app.run(host="0.0.0.0", port=8000)


# SUKUNA VISIT API SRC
# POWERED BY : @minister_69
# REMADE BY : @itz_me_R_Sukuna
# CHANNEL : @ryomen_sukuna_sg