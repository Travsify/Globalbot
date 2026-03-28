# GlobalLine WhatsApp AI Bot 🤖

AI-powered WhatsApp automation for GlobalLine Logistics. Powered by Groq (FREE, unlimited).

## Deploy to Render

### 1. Deploy Button

[![Deploy to Render](https://render.com/deploy?repo=https://github.com/Travsify/Globalbot)](https://render.com/deploy?repo=https://github.com/Travsify/Globalbot)

### 2. Manual Deploy

1. Go to https://render.com and sign up
2. Click **New → Web Service**
3. Connect your GitHub repo: `Travsify/Globalbot`
4. Set:
   - **Root Directory:** (leave empty)
   - **Build Command:** `npm install`
   - **Start Command:** `npm start`
5. Add Environment Variables:

| Name | Value |
|------|-------|
| `WHAPI_TOKEN` | `ut9iTWoHtpK1tPpPVmtQSytn3HcZtLNO` |
| `GROQ_API_KEY` | `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` |
| `ADMIN_NUMBER` | `447490347577` |

6. Click **Create Web Service**

### 3. Configure WHAPI Webhook

Once deployed, go to **whapi.cloud → Your channel → Settings → Webhooks**:
- URL: `https://your-service.onrender.com/webhook/whapi`

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

## Cost

- **Groq API:** FREE (unlimited)
- **WHAPI.cloud:** ~$15/month
- **Render:** Free tier available

**Total: ~$15/month**