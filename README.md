# GlobalLine WhatsApp AI Bot 🤖

AI-powered WhatsApp automation for GlobalLine Logistics. Powered by Groq (FREE, unlimited).

## Features

- 🤖 **AI Auto-Responder** — Handles any customer query
- 📦 **Quote Generator** — Instant shipping estimates
- 📍 **Shipment Tracker** — Check status by tracking number
- 💬 **Conversational AI** — Natural language understanding
- 🔔 **Team Alerts** — Get notified of new leads

## Tech Stack

- **Runtime:** Node.js / Express
- **AI:** Groq llama-3.1-8b-instant (FREE, unlimited)
- **WhatsApp:** WHAPI.cloud
- **Hosting:** Vercel

## Deploy to Vercel

### 1. Get Your API Keys

- **WHAPI Token:** Get from https://whapi.cloud
- **Groq API Key:** Get from https://console.groq.com

### 2. Deploy

**Option A: One-Click Deploy**

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/YOUR_GITHUB_REPO)

**Option B: Vercel CLI**

```bash
# Install Vercel CLI
npm i -g vercel

# Login
vercel login

# Deploy
cd globalline-whatsapp
vercel

# Set environment variables in Vercel dashboard:
# WHAPI_TOKEN: ut9iTWoHtpK1tPpPVmtQSytn3HcZtLNO
# GROQ_API_KEY: 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
# ADMIN_NUMBER: 447490347577
```

### 3. Configure WHAPI Webhook

In WHAPI dashboard:
1. Go to **Settings → Webhooks**
2. Set URL to: `https://your-project.vercel.app/webhook/whapi`
3. Enable: `messages`, `status`

### 4. Test

Send a message to your WhatsApp number and get an instant AI reply!

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook/whapi` | POST | WHAPI webhook receiver |
| `/api/health` | GET | Health check |
| `/api/conversations` | GET | List all conversations |
| `/api/quote-requests` | GET | List quote requests |
| `/api/quote` | POST | Send a quote |
| `/api/send` | POST | Send manual message |
| `/api/send-alert` | POST | Send alert to admin |
| `/api/test-ai` | GET | Test AI response |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `WHAPI_TOKEN` | WHAPI.cloud token | (your token) |
| `GROQ_API_KEY` | Groq API key | (your key) |
| `ADMIN_NUMBER` | Your WhatsApp number | 447490347577 |

## Files

```
globalline-whatsapp/
├── api/
│   └── index.js        # Main Express app
├── package.json        # Dependencies
├── vercel.json        # Vercel config
├── README.md          # This file
└── worker.py         # Background worker (optional)
```

## Cost

- **Groq API:** FREE (unlimited)
- **WHAPI.cloud:** ~$15/month
- **Vercel:** Free tier

**Total: ~$15/month**

## Support

For questions: info@globalline.io