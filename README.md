# Warmwire Backend

Ek chhota Python (FastAPI) backend jo **sach mein Gmail se connect** karta hai — OAuth aur App password dono se — senders ki details database mein store karta hai, aur test email bhej sakta hai.

> ⚠️ **Zaroori:** Ye tool sirf un logon ko emails bhejne ke liye use karein jinhone consent diya ho ya jinke sath aap ka genuine business rishta ho. Har email mein unsubscribe ka option rakhein aur apne mulk ke anti-spam qawaneen (CAN-SPAM / GDPR) follow karein. Gmail ki sending limits (normal ~500/day, Workspace ~2000/day) se upar na jayein warna account block ho sakta hai.

---

## 1) Install

```bash
cd warmwire-backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2) .env banao

```bash
cp .env.example .env
```

Ek encryption key banao aur `.env` ke `FERNET_KEY` mein daal do:

```bash
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

`SENDING_DOMAIN` ko apne domain par set karo (ya khaali chhodo agar koi bhi domain allow karna hai).

---

## 3) Google setup (OAuth ke liye) — step by step

Ye sirf ek dafa karna hota hai.

1. **Google Cloud Console** kholo: <https://console.cloud.google.com/>
2. Upar se ek **naya project** banao (naam kuch bhi, e.g. "Warmwire").
3. Left menu → **APIs & Services → Library** → search **"Gmail API"** → **Enable**.
4. **APIs & Services → OAuth consent screen**:
   - User type: **External** → Create.
   - App name, support email, developer email bhar do → Save.
   - **Scopes** step par **Add or Remove Scopes** → ye do add karo:
     - `.../auth/gmail.send`
     - `.../auth/gmail.readonly`
   - **Test users** step par apne wo Gmail addresses add karo jinhe aap connect karna chahte ho (jab tak app "Testing" mode mein hai, sirf yehi accounts connect ho sakte hain).
5. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**.
   - **Authorized redirect URIs** mein bilkul yehi daalo:
     ```
     http://localhost:8000/auth/google/callback
     ```
     (Ye `.env` ke `OAUTH_REDIRECT_URI` se **exactly** match hona chahiye.)
   - Create → phir **Download JSON**.
6. Us downloaded file ka naam **`credentials.json`** rakho aur is `warmwire-backend` folder mein rakh do (ya path `.env` ke `GOOGLE_CLIENT_SECRETS` mein set kar do).

---

## 4) Server chalao

```bash
uvicorn app.main:app --reload
```

Ab browser mein khulo: **<http://localhost:8000/docs>** — yahan saare API endpoints test kar sakte ho.

---

## 5) Sender kaise add karein

### A) OAuth se (recommended)

1. `GET /auth/google/start` call karo → ye ek `authorization_url` dega.
2. Us URL ko browser mein kholo → Google ka consent screen aayega → **apna mailbox choose karo → Allow**.
3. Google wapas `.../auth/google/callback` par bhejega, aur "✅ Connected {email}" dikhega.
4. Sender ab database mein save ho gaya. `GET /senders` se dekh lo.

> Email khud Google se aata hai (getProfile), isliye ye strict hai — jo mailbox aap allow karoge wohi save hoga.

### B) App password se

1. Google account par **2-Step Verification** on karo.
2. <https://myaccount.google.com/apppasswords> se **Mail** ke liye 16-character code banao.
3. `POST /senders/app-password` call karo:
   ```json
   {
     "email": "you@acme-outreach.com",
     "name": "Alex",
     "app_password": "abcdefghijklmnop",
     "daily_cap": 150,
     "warmup": true
   }
   ```
   Backend pehle SMTP login try karta hai — agar code galat hua to save nahi hoga (strict).

---

## 6) Test email bhejo

```
POST /senders/{id}/send-test
{
  "to": "someone@example.com",
  "subject": "Hello from Warmwire",
  "body_html": "<p>It works ✅</p>"
}
```

Ye us sender ke method (OAuth ya SMTP) ke hisab se sach mein email bhejega aur counters update karega.

---

## Endpoints (summary)

| Method | Path | Kaam |
|---|---|---|
| GET | `/senders` | Saare senders + details |
| GET | `/senders/{id}` | Ek sender ki detail |
| POST | `/senders/app-password` | App-password sender add (SMTP verify) |
| DELETE | `/senders/{id}` | Sender hatao |
| GET | `/auth/google/start` | Google consent URL |
| GET | `/auth/google/callback` | OAuth callback (Google use karta hai) |
| POST | `/senders/{id}/send-test` | Test email bhejo |

---

## Aage kya (next steps)

- **Sending engine**: recipients (Google Sheet/CSV) ko queue karke 15–40s random gap + sender rotation ke sath bhejna.
- **Warmup engine**: senders ke beech scheduled emails + auto-reply.
- **Frontend connect**: ye API ko Warmwire UI se jodna (abhi UI mock data par chalta hai).

Bolein to agla hissa bhi bana dete hain.
