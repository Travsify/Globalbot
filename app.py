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
            quote_state TEXT DEFAULT 'none',
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
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS processed_messages (
            msg_id TEXT PRIMARY KEY,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

def is_message_processed(msg_id):
    """Check if message was already processed (deduplication)"""
    if not msg_id:
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM processed_messages WHERE msg_id = ?", (msg_id,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def mark_message_processed(msg_id):
    """Mark a message as processed"""
    if not msg_id:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO processed_messages (msg_id) VALUES (?)", (msg_id,))
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
    # Use raw SQL to preserve quote_state on update
    c.execute("""
        INSERT INTO conversations (phone, name, last_message, last_message_time) 
        VALUES (?, ?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            name = COALESCE(excluded.name, name),
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

MAIN_MENU = """🏢 GlobalLine Logistics

Welcome! How can we help you today?

1️⃣ 📦 Book a Shipment
2️⃣ 💰 Get a Quote
3️⃣ 📍 Track Shipment
4️⃣ 📋 List Services
5️⃣ 💬 Talk to Support

Just reply with a number (1-5) or your question! 🚢"""

def get_main_menu_response(text_lower, phone):
    """Handle main menu navigation"""
    if text_lower in ["1", "book", "book shipment", "shipping", "send"]:
        return ("📦 Let's book a shipment!\n\n"
                "Where are we shipping from and to?\n"
                "E.g. 'Lagos to London' or 'I want to send a package'\n\n"
                "Or type CANCEL to go back.")
    
    if text_lower in ["2", "quote", "price", "cost", "rate"]:
        return start_quote_flow_from_menu(phone)
    
    if text_lower in ["3", "track", "tracking", "track shipment"]:
        return ("📍 Send me your tracking number!\n\n"
                "E.g. GL12345678 or TRK987654\n\n"
                "Or type CANCEL to go back.")
    
    if text_lower in ["4", "services", "list services", "what services", "what do you offer"]:
        return ("📋 Our Services:\n\n"
                "✈️ Air Freight: 1-3 days\n"
                "🚢 Ocean Freight: 15-45 days\n"
                "🚛 Road Freight: 1-7 days\n"
                "📦 Warehousing\n"
                "🏠 UK Customs Clearance\n\n"
                "Type 'quote' to get pricing! 💰")
    
    if text_lower in ["5", "support", "help", "talk to someone", "agent"]:
        return ("💬 Our support team is here!\n\n"
                "📧 Email: info@globalline.io\n"
                "📱 WhatsApp: +44 7490 347577\n"
                "🌐 globalline.io\n\n"
                "Or describe your issue and I'll help! 😊")
    
    if text_lower in ["menu", "main menu", "start", "hello", "hi", "hey"]:
        return MAIN_MENU
    
    return None

def start_quote_flow_from_menu(phone):
    # This sets the state AND returns the first question
    return start_quote_flow(phone)

def generate_ai_response(phone, user_message):
    """Generate AI response - checks automation first, then falls back to Groq"""
    
    text = user_message.strip()
    text_lower = text.lower()
    
    print(f"\n--- GENERATE RESPONSE ---")
    print(f"  phone: {phone}")
    print(f"  text: {text}")
    
    # Cancel commands
    if text_lower in ["cancel", "stop", "exit", "nevermind", "forget it"]:
        print(f"  >>> PATH: cancel")
        result = cancel_quote_flow(phone)
        if result:
            return result
    
    # Check main menu / navigation first
    menu_response = get_main_menu_response(text_lower, phone)
    if menu_response:
        print(f"  >>> PATH: main_menu")
        return menu_response
    
    # Check if in quote flow
    quote_response = handle_quote_flow(phone, text)
    if quote_response:
        print(f"  >>> PATH: quote_flow")
        return quote_response
    
    # Check for tracking intent
    tracking_response = auto_track_shipment(phone, text)
    if tracking_response:
        print(f"  >>> PATH: tracking")
        return tracking_response
    
    # Check for new quote request keywords
    quote_keywords = ["quote", "price", "cost", "rate", "how much", "shipping cost", "get a quote"]
    if any(kw in text_lower for kw in quote_keywords):
        return start_quote_flow(phone)
    
    # Check for booking
    if text_lower == "book" or "confirm booking" in text_lower:
        return ("🙏 Booking request received!\n\n"
                "Our team will contact you shortly to finalize your shipment.\n"
                "📧 Or email us: info@globalline.io\n"
                "📱 Call us: +44 7490 347577")
    
    # Fall back to AI chat
    context = get_conversation_context(phone, limit=10)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in context:
        role = "user" if msg["direction"] == "incoming" else "assistant"
        messages.append({"role": role, "content": msg["message"]})
    messages.append({"role": "user", "content": text})
    
    try:
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
            return result["choices"][0]["message"]["content"]
        
    except Exception as e:
        print(f"Groq Error: {e}")
        return """🏢 GlobalLine Logistics

I'm here to help! Here's what I can do:

1️⃣ 📦 Book a Shipment
2️⃣ 💰 Get a Quote
3️⃣ 📍 Track Shipment
4️⃣ 📋 List Services
5️⃣ 💬 Talk to Support

Just reply with a number or your question! 🚢"""

def save_quote_request(phone, message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO quote_requests (phone, status) VALUES (?, 'new')", (phone,))
    conn.commit()
    conn.close()
    
    send_whatsapp_message(ADMIN_NUMBER, 
        f"🔔 New Quote Request!\n\nFrom: {phone}\n\nMessage: {message[:200]}")

# ==========================================
# AUTOMATION: TRACKING
# ==========================================

def auto_track_shipment(phone, text):
    """Extract tracking number and return status"""
    import re
    # Common patterns: GL123456, TRK123456, 10+ alphanumeric
    patterns = [
        r'\b(GL|TRK|GLB)[A-Z0-9]{6,12}\b',
        r'\b[A-Z]{2,3}[0-9]{6,10}\b',
        r'\b(\d{10,15})\b',
    ]
    
    tracking_number = None
    for pattern in patterns:
        match = re.search(pattern, text.upper())
        if match:
            tracking_number = match.group(0).upper()
            break
    
    if not tracking_number:
        return None  # No tracking number found
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM shipments WHERE tracking_number = ?", (tracking_number,))
    shipment = c.fetchone()
    conn.close()
    
    if shipment:
        return (f"📦 Shipment Found!\n\n"
                f"🔢 Tracking: {shipment['tracking_number']}\n"
                f"📊 Status: {shipment['status']}\n"
                f"📍 Origin: {shipment['origin']}\n"
                f"📍 Destination: {shipment['destination']}\n"
                f"📅 Created: {shipment['created_at'][:10]}")
    else:
        return (f"🔍 {tracking_number} not found in our system.\n\n"
                f"Please double-check your tracking number or contact us at info@globalline.io for assistance.")

# ==========================================
# AUTOMATION: QUOTE FLOW
# ==========================================

QUOTE_QUESTIONS = {
    "awaiting_origin": "🌍 I can help with that! Where are we shipping from?\n\nPlease enter the origin city or country:",
    "awaiting_destination": "📍 Got it! Where are we shipping to?\n\nPlease enter the destination city or country:",
    "awaiting_weight": "⚖️ Perfect! What is the approximate weight?\n\nPlease enter in kg (e.g. 5kg, 10kg):",
    "awaiting_service": """📋 What service do you prefer?

1️⃣ Air Freight (1-3 days) - NGN 4,000-6,500/kg
2️⃣ Ocean Freight (15-45 days) - NGN 380-3,000/kg
3️⃣ Road Freight (1-7 days)

Just reply with 1, 2 or 3:""",
}

SERVICE_MAP = {
    "1": ("Air Freight", "NGN 4,000-6,500/kg"),
    "2": ("Ocean Freight", "NGN 380-3,000/kg"),
    "3": ("Road Freight", "Contact for rate"),
}

def start_quote_flow(phone):
    # Ensure conversation row exists first
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO conversations (phone, quote_state) VALUES (?, 'awaiting_origin')
        ON CONFLICT(phone) DO UPDATE SET quote_state = 'awaiting_origin'
    """, (phone,))
    conn.commit()
    conn.close()
    return QUOTE_QUESTIONS["awaiting_origin"]

def handle_quote_flow(phone, text):
    """Process each step of the quote flow"""
    print(f"\n--- QUOTE FLOW ---")
    print(f"  phone: {phone}, text: {text}")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Ensure row exists
    c.execute("""
        INSERT INTO conversations (phone, quote_state) VALUES (?, 'none')
        ON CONFLICT(phone) DO NOTHING
    """, (phone,))
    conn.commit()
    conn.row_factory = sqlite3.Row
    c.execute("SELECT quote_state FROM conversations WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        print(f"  state: NO ROW")
        return None
    
    state = row["quote_state"]
    print(f"  state: {state}")
    
    if state == "none":
        print(f"  >>> returning None (not in quote flow)")
        return None
    
    if state == "awaiting_origin":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET origin = ? WHERE phone = ? AND status = 'pending'", (text.strip(), phone))
        if c.rowcount == 0:
            c.execute("INSERT INTO quote_requests (phone, origin, status) VALUES (?, ?, 'pending')", (phone, text.strip()))
        c.execute("UPDATE conversations SET quote_state = 'awaiting_destination' WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()
        response = QUOTE_QUESTIONS["awaiting_destination"]
    
    elif state == "awaiting_destination":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET destination = ? WHERE phone = ? AND status = 'pending'", (text.strip(), phone))
        c.execute("UPDATE conversations SET quote_state = 'awaiting_weight' WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()
        response = QUOTE_QUESTIONS["awaiting_weight"]
    
    elif state == "awaiting_weight":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET weight = ? WHERE phone = ? AND status = 'pending'", (text.strip(), phone))
        c.execute("UPDATE conversations SET quote_state = 'awaiting_service' WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()
        response = QUOTE_QUESTIONS["awaiting_service"]
    
    elif state == "awaiting_service":
        service_key = text.strip().lower()
        service_name, price_range = SERVICE_MAP.get(service_key, ("Unknown", "Contact us"))
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET service_type = ?, status = 'quoted' WHERE phone = ? AND status = 'pending'", (service_name, phone))
        c.execute("UPDATE conversations SET quote_state = 'none' WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()
        
        # Get full quote details
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM quote_requests WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,))
        quote = c.fetchone()
        conn.close()
        
        if quote:
            response = (f"📦 Quote Ready!\n\n"
                       f"📍 From: {quote['origin']}\n"
                       f"📍 To: {quote['destination']}\n"
                       f"⚖️ Weight: {quote['weight']}\n"
                       f"🚢 Service: {service_name}\n"
                       f"💰 Est. Rate: {price_range}\n\n"
                       f"To proceed, contact us:\n"
                       f"📧 info@globalline.io\n"
                       f"📱 WhatsApp: Reply 'BOOK' to confirm booking")
            
            # Alert admin
            send_whatsapp_message(ADMIN_NUMBER,
                f"🔔 Quote Generated!\n\nFrom: {phone}\n{quote['origin']} → {quote['destination']}\n{quote['weight']}\n{service_name}")
    
    return response

def cancel_quote_flow(phone):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE conversations SET quote_state = 'none' WHERE phone = ?", (phone,))
    c.execute("DELETE FROM quote_requests WHERE phone = ? AND status = 'pending'", (phone,))
    conn.commit()
    conn.close()
    return "Got it! Quote request cancelled. Message me anytime to start a new request. 😊"

# ==========================================
# WEBHOOKS
# ==========================================

@app.route("/webhook/whapi", methods=["GET", "POST"])
def webhook_whapi():
    # WHAPI sends GET for webhook verification
    if request.method == "GET":
        return jsonify({"status": "ok"})
    
    data = request.json or {}
    
    print(f"\n=== WEBHOOK RECEIVED ===")
    print(f"Full payload: {json.dumps(data, indent=2)[:500]}")
    
    messages = data.get("messages", [])
    if not messages:
        print("No messages in payload")
        return jsonify({"status": "ok"})
    
    print(f"Message count: {len(messages)}")
    
    for message in messages:
        msg_id = message.get("id")
        from_me = message.get("from_me")
        phone = message.get("from")
        text = message.get("text", {}).get("body", "")
        name = message.get("contact", {}).get("name", "Customer")
        
        print(f"\n--- MESSAGE ---")
        print(f"  msg_id: {msg_id}")
        print(f"  from_me: {from_me}")
        print(f"  phone: {phone}")
        print(f"  text: {text[:100] if text else '(empty)'}")
        
        # Skip outgoing messages (from us)
        if from_me:
            print(f"  >>> SKIP: from_me=True (our own message)")
            continue
        
        # Deduplication
        if is_message_processed(msg_id):
            print(f"  >>> SKIP: already processed (msg_id={msg_id})")
            continue
        mark_message_processed(msg_id)
        
        if not text:
            print(f"  >>> SKIP: empty text")
            continue
        
        print(f"  >>> PROCESSING...")
        
        save_message(phone, text, "incoming")
        save_conversation(phone, name, text)
        
        response = generate_ai_response(phone, text)
        
        print(f"  >>> RESPONSE: {response[:100] if response else '(none)'}...")
        
        save_message(phone, response, "outgoing")
        send_whatsapp_message(phone, response)
        
        print(f"  >>> SENT OK")
    
    print(f"=== WEBHOOK DONE ===\n")
    return jsonify({"status": "ok"})

@app.route("/webhook/status", methods=["POST"])
def webhook_status():
    return jsonify({"status": "ok"})

# ==========================================
# API ROUTES
# ==========================================

@app.route("/api/reset-db", methods=["GET"])
def reset_db():
    """Reset database - for fixing schema issues"""
    import os
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    return jsonify({"status": "ok", "message": "Database reset"})

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

@app.route("/api/add-shipment", methods=["POST"])
def add_shipment():
    """Add a new shipment (creates tracking number)"""
    data = request.json
    phone = data.get("phone")
    origin = data.get("origin", "Unknown")
    destination = data.get("destination", "Unknown")
    status = data.get("status", "Order Received")
    
    import uuid
    tracking_number = "GL" + str(uuid.uuid4().int)[:10]
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO shipments (tracking_number, phone, origin, destination, status)
        VALUES (?, ?, ?, ?, ?)
    """, (tracking_number, phone, origin, destination, status))
    conn.commit()
    conn.close()
    
    confirmation = (f"📦 Shipment Created!\n\n"
                   f"🔢 Tracking: {tracking_number}\n"
                   f"📍 {origin} → {destination}\n"
                   f"📊 Status: {status}")
    
    if phone:
        send_whatsapp_message(phone, confirmation)
    
    return jsonify({
        "status": "ok",
        "tracking_number": tracking_number,
        "origin": origin,
        "destination": destination,
        "status": status
    })

@app.route("/api/shipments", methods=["GET"])
def list_shipments():
    """List all shipments"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM shipments ORDER BY created_at DESC LIMIT 100")
    rows = c.fetchall()
    conn.close()
    return jsonify({"shipments": [dict(r) for r in rows]})

@app.route("/api/update-shipment", methods=["POST"])
def update_shipment():
    """Update shipment status"""
    data = request.json
    tracking_number = data.get("tracking_number")
    status = data.get("status")
    phone = data.get("phone")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE shipments SET status = ? WHERE tracking_number = ?", (status, tracking_number))
    conn.commit()
    
    if c.rowcount > 0 and phone:
        update_msg = (f"📦 Shipment Update!\n\n"
                     f"🔢 {tracking_number}\n"
                     f"📊 Status: {status}")
        send_whatsapp_message(phone, update_msg)
    
    conn.close()
    return jsonify({"ok": c.rowcount > 0})

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