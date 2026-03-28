const express = require('express');
const cors = require('cors');
const sqlite3 = require('better-sqlite3');
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json());

// Config - environment variables (set in Vercel)
const WHAPI_TOKEN = process.env.WHAPI_TOKEN;
const WHAPI_ENDPOINT = "https://gate.whapi.cloud";
const GROQ_API_KEY = process.env.GROQ_API_KEY;
const GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions";
const ADMIN_NUMBER = process.env.ADMIN_NUMBER || "447490347577";

// Database
const DB_PATH = path.join('/tmp', 'globalline.db');

let db;
function initDb() {
    db = sqlite3(DB_PATH);
    db.exec(`
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL UNIQUE,
            name TEXT,
            last_message TEXT,
            last_message_time TEXT,
            state TEXT DEFAULT 'new',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            message TEXT,
            direction TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS quote_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            origin TEXT,
            destination TEXT,
            weight TEXT,
            service_type TEXT,
            estimated_price TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    `);
}
initDb();

// System prompt
const SYSTEM_PROMPT = `You are GlobalLine Logistics AI assistant on WhatsApp. You help customers with:

SERVICES:
- Air Freight: 1-3 days delivery (NGN 4,000-6,500/kg)
- Ocean Freight: 15-45 days delivery (NGN 380-3,000/kg)  
- Road Freight: 1-7 days delivery
- Warehousing services
- UK customs clearance (pre-clearance available at BHX/LHR)

KEY INFO:
- 25 years experience
- 180+ countries coverage
- 99.2% on-time delivery
- Trusted by 10,000+ businesses

PRICING (Nigeria routes):
- Nigeria → UK (LHR): Air NGN 4,000-6,500/kg, Sea NGN 380-3,000/kg
- Door-to-door: NGN 400/segment

RESPONSE STYLE:
- Keep responses SHORT and conversational (WhatsApp style)
- Use emojis sparingly (max 2-3 per message)
- Be helpful, professional, and friendly
- Always end with a call-to-action`;

// Helper functions
async function sendWhasAppMessage(to, text) {
    const response = await fetch(`${WHAPI_ENDPOINT}/messages/text`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${WHAPI_TOKEN}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ typing: true, to, body: text })
    });
    return response.json();
}

function saveMessage(phone, message, direction) {
    db.prepare('INSERT INTO messages (phone, message, direction) VALUES (?, ?, ?)').run(phone, message, direction);
}

function saveConversation(phone, name, lastMessage) {
    db.prepare(`
        INSERT INTO conversations (phone, name, last_message, last_message_time) 
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(phone) DO UPDATE SET
        last_message = excluded.last_message,
        last_message_time = datetime('now')
    `).run(phone, name, lastMessage);
}

function getConversationContext(phone, limit = 10) {
    const rows = db.prepare(`
        SELECT * FROM messages 
        WHERE phone = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    `).all(phone, limit);
    return rows.reverse();
}

async function generateAIResponse(phone, userMessage) {
    const context = getConversationContext(phone);
    
    const messages = [{ role: "system", content: SYSTEM_PROMPT }];
    
    for (const msg of context) {
        const role = msg.direction === 'incoming' ? 'user' : 'assistant';
        messages.push({ role, content: msg.message });
    }
    
    messages.push({ role: "user", content: userMessage });
    
    try {
        const response = await fetch(GROQ_ENDPOINT, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${GROQ_API_KEY}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                model: "llama-3.1-8b-instant",
                messages,
                max_tokens: 500,
                temperature: 0.7
            })
        });
        
        const result = await response.json();
        return result.choices[0].message.content;
    } catch (error) {
        console.error('Groq Error:', error);
        return "Thanks for your message! Our team will get back to you shortly. For immediate help: info@globalline.io 🚢";
    }
}

// Routes
app.post('/webhook/whapi', async (req, res) => {
    const messages = req.body.messages || [];
    
    for (const message of messages) {
        if (message.from_me) continue;
        
        const phone = message.from;
        const text = message.text?.body || '';
        const name = message.contact?.name || 'Customer';
        
        if (!text) continue;
        
        console.log(`📩 From ${phone}: ${text.substring(0, 100)}`);
        
        saveMessage(phone, text, 'incoming');
        saveConversation(phone, name, text);
        
        const response = await generateAIResponse(phone, text);
        
        saveMessage(phone, response, 'outgoing');
        await sendWhasAppMessage(phone, response);
        
        console.log(`🤖 Response: ${response.substring(0, 100)}...`);
    }
    
    res.json({ status: 'ok' });
});

app.post('/webhook/status', (req, res) => {
    res.json({ status: 'ok' });
});

app.get('/api/health', (req, res) => {
    res.json({ status: 'ok', service: 'GlobalLine WhatsApp AI Bot', ai: 'Groq llama-3.1-8b-instant (FREE)' });
});

app.get('/api/conversations', (req, res) => {
    const rows = db.prepare('SELECT * FROM conversations ORDER BY last_message_time DESC LIMIT 50').all();
    res.json({ conversations: rows });
});

app.get('/api/quote-requests', (req, res) => {
    const rows = db.prepare('SELECT * FROM quote_requests ORDER BY created_at DESC LIMIT 50').all();
    res.json({ quotes: rows });
});

app.post('/api/quote', async (req, res) => {
    const { phone, origin, destination, weight, service = 'air' } = req.body;
    
    const rates = {
        air: { min: 4000, max: 6500 },
        sea: { min: 380, max: 3000 },
        road: { min: 400, max: 2000 }
    };
    
    const rate = rates[service] || rates.air;
    const w = parseFloat(weight) || 0;
    const estimated = {
        min: Math.round(w * rate.min),
        max: Math.round(w * rate.max)
    };
    
    const quoteText = `📦 SHIPPING QUOTE

📍 From: ${origin}
📍 To: ${destination}
⚖️ Weight: ${weight} kg
🚚 Service: ${service.toUpperCase()}

💰 ESTIMATED COST:
NGN ${estimated.min.toLocaleString()} - ${estimated.max.toLocaleString()}

*Final cost based on exact dimensions*

Ready to ship? Reply YES to proceed!

🚢 GlobalLine Logistics`;
    
    if (phone) {
        await sendWhasAppMessage(phone, quoteText);
    }
    
    db.prepare(`
        INSERT INTO quote_requests (phone, origin, destination, weight, service_type, estimated_price, status)
        VALUES (?, ?, ?, ?, ?, ?, 'quoted')
    `).run(phone, origin, destination, weight, service, `NGN ${estimated.min.toLocaleString()} - ${estimated.max.toLocaleString()}`);
    
    res.json({ success: true, estimated });
});

app.post('/api/send', async (req, res) => {
    const { phone, message } = req.body;
    if (!phone || !message) {
        return res.status(400).json({ error: 'phone and message required' });
    }
    const result = await sendWhasAppMessage(phone, message);
    res.json(result);
});

app.post('/api/send-alert', async (req, res) => {
    const { message } = req.body;
    const result = await sendWhasAppMessage(ADMIN_NUMBER, `🔔 ALERT:\n\n${message}`);
    res.json(result);
});

app.get('/api/test-ai', async (req, res) => {
    const response = await generateAIResponse('test', 'Hello! What services do you offer?');
    res.json({ question: 'Hello! What services do you offer?', response });
});

module.exports = app;