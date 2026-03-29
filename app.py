#!/usr/bin/env python3
"""
GlobalLine WhatsApp Automation - AI Powered
Powered by Groq (Free, Unlimited)
"""

import os
import json
import requests
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify
from datetime import datetime
import sqlite3

app = Flask(__name__)

# Config
WHAPI_TOKEN = os.environ.get("WHAPI_TOKEN")
WHAPI_ENDPOINT = "https://gate.whapi.cloud"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
ADMIN_NUMBER = "447490347577"
DB_PATH = os.environ.get("DB_PATH", "/tmp/globalline.db")

# System prompt for GlobalLine AI
SYSTEM_PROMPT = """You are GlobalLine Logistics AI assistant on WhatsApp. You help customers with:

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
- Nigeria → US (JFK): Similar rates
- Nigeria → Canada (YYZ): Similar rates
- Door-to-door: NGN 400/segment

CUSTOMS INFO:
- We handle UK duty/VAT directly (not broker reimbursement model)
- Pre-clearance available at BHX/LHR
- Full customs documentation service

RESPONSE STYLE:
- Keep responses SHORT and conversational (WhatsApp style)
- Use emojis sparingly (max 2-3 per message)
- Be helpful, professional, and friendly
- Always end with a call-to-action or next step
- If you don't know something, say you'll check and get back

TASKS:
1. Answer shipping queries
2. Provide quote estimates  
3. Track shipments (when given tracking number)
4. Explain services
5. Connect to human agent for complex issues"""

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL UNIQUE,
            name TEXT,
            last_message TEXT,
            last_message_time TIMESTAMP,
            state TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            message TEXT,
            direction TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS quote_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            origin TEXT,
            destination TEXT,
            weight TEXT,
            service_type TEXT,
            estimated_price TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_number TEXT UNIQUE,
            phone TEXT,
            status TEXT DEFAULT 'pending',
            origin TEXT,
            destination TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

def save_message(phone, message, direction):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (phone, message, direction) VALUES (?, ?, ?)",
              (phone, message, direction))
    conn.commit()
    conn.close()

def get_conversation_context(phone, limit=10):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM messages 
        WHERE phone = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (phone, limit))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

def save_conversation(phone, name=None, last_message=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO conversations (phone, name, last_message, last_message_time) 
        VALUES (?, ?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
        last_message = excluded.last_message,
        last_message_time = excluded.last_message_time
    """, (phone, name, last_message, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def send_whatsapp_message(to, text):
    url = f"{WHAPI_ENDPOINT}/messages/text"
    headers = {
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"typing": True, "to": to, "body": text}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return {"error": str(e)}

def generate_ai_response(phone, user_message):
    """Generate AI response using Groq (free, unlimited)"""
    
    # Get conversation context
    context = get_conversation_context(phone)
    
    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add recent conversation for continuity
    for msg in context:
        role = "user" if msg["direction"] == "incoming" else "assistant"
        messages.append({"role": role, "content": msg["message"]})
    
    # Add current message
    messages.append({"role": "user", "content": user_message})
    
    try:
        # Call Groq API
        data = json.dumps({
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "max_tokens": 500,
            "temperature": 0.7
        }).encode()
        
        req = urllib.request.Request(
            GROQ_ENDPOINT,
            data=data,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode())
            ai_response = result["choices"][0]["message"]["content"]
            
            # Check if quote request
            if "quote" in user_message.lower():
                save_quote_request(phone, user_message)
            
            return ai_response
        
    except Exception as e:
        print(f"Groq Error: {e}")
        return """Thanks for your message! Our team will get back to you shortly. 
        
For immediate help: info@globalline.io or call us 🚢"""

def save_quote_request(phone, message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO quote_requests (phone, status) VALUES (?, 'new')", (phone,))
    conn.commit()
    conn.close()
    
    send_whatsapp_message(ADMIN_NUMBER, 
        f"🔔 New Quote Request!\n\nFrom: {phone}\n\nMessage: {message[:200]}")

# ==========================================
# WEBHOOKS
# ==========================================

@app.route("/webhook/whapi", methods=["GET", "POST"])
def webhook_whapi():
    # WHAPI sends GET for webhook verification
    if request.method == "GET":
        return jsonify({"status": "ok"})
    
    data = request.json or {}
    
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"status": "ok"})
    
    for message in messages:
        if message.get("from_me"):
            continue
        
        phone = message.get("from")
        text = message.get("text", {}).get("body", "")
        name = message.get("contact", {}).get("name", "Customer")
        
        if not text:
            continue
        
        print(f"\n📩 From {phone}: {text[:100]}")
        
        save_message(phone, text, "incoming")
        save_conversation(phone, name, text)
        
        response = generate_ai_response(phone, text)
        
        save_message(phone, response, "outgoing")
        send_whatsapp_message(phone, response)
        
        print(f"🤖 Response: {response[:100]}...")
    
    return jsonify({"status": "ok"})

@app.route("/webhook/status", methods=["POST"])
def webhook_status():
    return jsonify({"status": "ok"})

# ==========================================
# API ROUTES
# ==========================================

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok", 
        "service": "GlobalLine WhatsApp AI Bot",
        "ai": "Groq llama-3.1-8b-instant (FREE)"
    })

@app.route("/api/conversations", methods=["GET"])
def list_conversations():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM conversations ORDER BY last_message_time DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    return jsonify({"conversations": [dict(r) for r in rows]})

@app.route("/api/conversation/<phone>", methods=["GET"])
def get_conversation_messages(phone):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM messages WHERE phone = ? ORDER BY created_at DESC LIMIT 100
    """, (phone,))
    rows = c.fetchall()
    conn.close()
    return jsonify({"messages": [dict(r) for r in reversed(rows)]})

@app.route("/api/quote-requests", methods=["GET"])
def list_quotes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM quote_requests ORDER BY created_at DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    return jsonify({"quotes": [dict(r) for r in rows]})

@app.route("/api/quote", methods=["POST"])
def create_quote():
    data = request.json
    phone = data.get("phone")
    origin = data.get("origin")
    destination = data.get("destination")
    weight = float(data.get("weight", 0))
    service = data.get("service", "air")
    
    rates = {
        "air": {"min": 4000, "max": 6500},
        "sea": {"min": 380, "max": 3000},
        "road": {"min": 400, "max": 2000}
    }
    
    rate = rates.get(service, rates["air"])
    estimated = {
        "min": int(weight * rate["min"]),
        "max": int(weight * rate["max"])
    }
    
    quote_text = f"""📦 SHIPPING QUOTE

📍 From: {origin}
📍 To: {destination}
⚖️ Weight: {weight} kg
🚚 Service: {service.upper()}

💰 ESTIMATED COST:
NGN {estimated['min']:,} - {estimated['max']:,}

*Final cost based on exact dimensions*

Ready to ship? Reply YES to proceed!

🚢 GlobalLine Logistics"""
    
    if phone:
        send_whatsapp_message(phone, quote_text)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO quote_requests 
        (phone, origin, destination, weight, service_type, estimated_price, status) 
        VALUES (?, ?, ?, ?, ?, ?, 'quoted')
    """, (phone, origin, destination, str(weight), service, f"NGN {estimated['min']:,} - {estimated['max']:,}"))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "estimated": estimated})

@app.route("/api/track", methods=["POST"])
def track_shipment():
    data = request.json
    tracking_number = data.get("tracking_number")
    phone = data.get("phone")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM shipments WHERE tracking_number = ?", (tracking_number,))
    shipment = c.fetchone()
    conn.close()
    
    if shipment:
        status_text = f"""📍 SHIPMENT TRACKING

🔢 Tracking: {tracking_number}
📊 Status: {shipment['status']}
📍 Origin: {shipment['origin']}
📍 Destination: {shipment['destination']}

Questions? Type SUPPORT! 🚢"""
    else:
        status_text = f"""📍 Tracking: {tracking_number}

❌ Not found in our system

Please check the number or contact us directly.

🚢 GlobalLine Logistics"""
    
    if phone:
        send_whatsapp_message(phone, status_text)
    
    return jsonify({"found": shipment is not None, "tracking_number": tracking_number})

@app.route("/api/send", methods=["POST"])
def send_message():
    data = request.json
    phone = data.get("phone")
    message = data.get("message")
    
    if not phone or not message:
        return jsonify({"error": "phone and message required"}), 400
    
    result = send_whatsapp_message(phone, message)
    return jsonify(result)

@app.route("/api/send-alert", methods=["POST"])
def send_alert():
    data = request.json
    message = data.get("message")
    result = send_whatsapp_message(ADMIN_NUMBER, f"🔔 ALERT:\n\n{message}")
    return jsonify(result)

@app.route("/api/test-ai", methods=["GET"])
def test_ai():
    test_message = "Hello! What services do you offer?"
    response = generate_ai_response("test", test_message)
    return jsonify({"question": test_message, "response": response})

# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    print("🚀 GlobalLine WhatsApp AI Bot Starting...")
    init_db()
    print(f"📱 WHAPI: Connected")
    print(f"🤖 AI: Groq llama-3.1-8b-instant (FREE)")
    print(f"👤 Admin: {ADMIN_NUMBER}")
    app.run(host="0.0.0.0", port=5001, debug=True)