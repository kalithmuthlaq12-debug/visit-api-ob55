<div align="center">

# 👁️ Sukuna Visit API

**A fast async Flask API with automatic JWT generation and smart token refresh.**

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-API-000000?style=for-the-badge&logo=flask&logoColor=white)
![AsyncIO](https://img.shields.io/badge/asyncio-aiohttp-2C5BB4?style=for-the-badge)
![JWT](https://img.shields.io/badge/JWT-Auto%20Refresh-D63AFF?style=for-the-badge&logo=jsonwebtokens&logoColor=white)
![Status](https://img.shields.io/badge/Status-Active-2ea44f?style=for-the-badge)

[Features](#-features) • [How it works](#-how-it-works) • [Installation](#-installation) • [Usage](#-usage) • [API Reference](#-api-reference) • [Configuration](#%EF%B8%8F-configuration) • [Disclaimer](#%EF%B8%8F-disclaimer)

</div>

---

## 📖 Overview

**Sukuna Visit API** sends profile visits through a pool of accounts and returns the target player's info (nickname, level, likes, region) along with success stats.

Tokens are no longer pasted into JSON files by hand. You provide `uid:password` account lists, and the API **generates JWTs automatically** and **refreshes only the ones that are about to expire**.

---

## ✨ Features

- 🔐 **Automatic JWT generation** from simple `uid:password` account files
- 🧠 **Smart refresh**: only missing, expired, or soon-to-expire (< 30 min) tokens are regenerated
- ⏰ **Background scheduler**: checks every 30 minutes, no cron job needed
- 💾 **Persistent token cache**: saved to `token_*.json`, restored on restart (expired tokens are skipped)
- 🔄 **Backward compatible**: still reads the old list-style `token_*.json` format
- 🌍 **Multi-server support**: IND, BR / US / SAC / NA, and BD-group servers (ME, PK, TH, VN, ID, ...)
- 🎯 **Region-aware filtering**: only tokens matching the requested server are used
- 🚀 **High concurrency**: batched async requests (300 per batch) until 1000 successful visits
- 🛡️ **Atomic file writes**: token files never end up half-written
- 📋 **Clean JSON response** with player info and success/failure counts

---

## 🧩 How it works

```text
             ┌──────────────────────┐
             │  account_*.txt       │   uid:password per line
             └──────────┬───────────┘
                        │
                        ▼
           ┌────────────────────────────┐
 /visit ──▶│  Smart Token Loader        │
           │  • cached & valid? reuse   │
           │  • missing / expiring?     │──▶ JWT API ──▶ new token
           └──────────┬─────────────────┘
                      │
                      ▼
           ┌────────────────────────────┐
           │  TOKEN_CACHE + token_*.json│
           └──────────┬─────────────────┘
                      │
                      ▼
           ┌────────────────────────────┐
           │  Async visit batches (300) │──▶ until 1000 successes
           └──────────┬─────────────────┘
                      │
                      ▼
                 JSON response

 🕒 Background thread: every 30 min → refresh only expired / expiring tokens
```

---

## 📁 Project structure

```text
.
├── app.py               # Visit API (main file, port 8000)
├── byte.py                # encrypt_api / Encrypt_ID helpers
├── visit_count_pb2.py     # protobuf definition
├── account_ind.txt        # accounts for IND
├── account_br.txt         # accounts for BR / US / SAC / NA
├── account_bd.txt         # accounts for BD and other servers
├── token_*.json           # auto-generated token cache
├── requirements.txt
└── README.md
```

---

## 🔧 Installation

**1. Clone the repository**

```bash
git clone https://github.com/kalithmuthlaq12-debug/visit-api-ob55.git
cd visit-api-ob55
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

<details>
<summary>📦 <code>requirements.txt</code></summary>

```text
flask
aiohttp
pyjwt
protobuf
pycryptodome
```

</details>

**3. Add your accounts**

Create the account file(s) you need, one `uid:password` per line:

```text
# account_ind.txt
1234567890:your_password_here
9876543210:another_password
```

- Lines starting with `#` are ignored
- Duplicates and placeholder values (`uid`, `password`, ...) are skipped automatically

---

## 🚀 Usage

**Run locally**

```bash
python app.py
```

The API starts on `http://0.0.0.0:8000`. On startup, the scheduler loads cached tokens from disk. If none are valid, it generates a fresh set. After that it only refreshes what is needed.

**Production (gunicorn)**

```bash
gunicorn -w 1 -b 0.0.0.0:8000 app_1:app
```

> Use a single worker (`-w 1`) so only one background refresher runs.

---

## 📡 API Reference

### `GET /visit`

| Parameter | Required | Description |
|---|---|---|
| `uid` | ✅ | Target player UID (integer) |
| `server_name` | ✅ | `IND`, `BR`, `US`, `SAC`, `NA`, `BD`, `ME`, `PK`, `TH`, `VN`, `ID`, ... |
| `key` | ✅ | API key |

**Example**

```bash
curl "http://localhost:8000/visit?uid=1234567890&server_name=IND&key=YOUR_KEY"
```

**Success response**

```json
{
  "nickname": "PlayerName",
  "uid": 1234567890,
  "level": 65,
  "likes": 5120,
  "region": "IND",
  "available_accounts": 150,
  "total_success": 1000,
  "total_failed": 0
}
```

| Field | Description |
|---|---|
| `nickname`, `uid`, `level`, `likes`, `region` | Player info decoded from the game response |
| `available_accounts` | Number of valid tokens used for this request |
| `total_success` | Successful visits (target: 1000) |
| `total_failed` | `1000 - total_success` |

**Error responses**

| Code | Reason |
|---|---|
| `400` | Missing parameters, or `uid` is not an integer |
| `401` | Invalid API key |
| `500` | No valid accounts/tokens for the server, or player info could not be decoded |

---

## ⚙️ Configuration

Tweak these constants at the top of `app.py`:

| Setting | Default | Description |
|---|---|---|
| `JWT_API` | `https://jat-iota.vercel.app/token` | JWT generation endpoint |
| `JWT_CONCURRENCY` | `50` | Parallel JWT requests |
| `JWT_TIMEOUT` | `30` | JWT request timeout (seconds) |
| `CHECK_INTERVAL_MIN` | `30` | Background check interval (minutes) |
| `TOKEN_MIN_VALIDITY` | `1800` | Refresh when fewer than this many seconds remain |
| `target_success` | `1000` | Successful visits per request (in the `/visit` route) |

### 🗂️ Server → file mapping

| Server | Account file | Token file |
|---|---|---|
| `IND` | `account_ind.txt` | `token_ind.json` |
| `BR`, `US`, `SAC`, `NA` | `account_br.txt` | `token_br.json` |
| `BD` and others | `account_bd.txt` | `token_bd.json` |

---

## 🔒 Security tips

- Change the default API key in `app.py` before deploying publicly
- **Never commit** `account_*.txt` or `token_*.json`. Add this to `.gitignore`:

```gitignore
account_*.txt
token_*.json
__pycache__/
*.pyc
```

- Put the API behind a reverse proxy (Nginx/Caddy) with HTTPS and rate limiting

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `No valid tokens found for server` | Check that the matching `account_*.txt` exists with valid `uid:password` lines, and that the JWT API is reachable |
| `Could not decode player information` | The UID or server is wrong, or all visit requests failed |
| `ModuleNotFoundError: byte` / `visit_count_pb2` | Make sure both files are in the same folder as `app.py` |
| `ModuleNotFoundError: jwt` | `pip install pyjwt` |
| Tokens refresh on every request | System clock is off, or tokens are expiring within 30 min |

---

## ⚠️ Disclaimer

This project is provided **for educational purposes only**. Automating requests against game services may violate their Terms of Service and can lead to account bans or other consequences. The authors take no responsibility for misuse. **Use at your own risk.**

---

## 🙌 Credits

- **Sukuna Visit API**: built and maintained by Sukuna
- **Repository**: [kalithmuthlaq12-debug/visit-api-ob55](https://github.com/kalithmuthlaq12-debug/visit-api-ob55)

If this project helped you, consider leaving a ⭐ on the repo!

<div align="center">

Made with ❤️ and a lot of async.

</div>
