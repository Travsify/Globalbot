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
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY")
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
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            receiver_name TEXT,
            receiver_phone TEXT,
            receiver_address TEXT,
            cargo_description TEXT,
            weight TEXT,
            service_type TEXT,
            origin TEXT,
            destination TEXT,
            estimated_price TEXT,
            paystack_ref TEXT,
            payment_status TEXT DEFAULT 'pending',
            status TEXT DEFAULT 'pending',
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
    """Mark a message as processed - ATOMIC with INSERT OR IGNORE"""
    if not msg_id:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO processed_messages (msg_id) VALUES (?)", (msg_id,))
    conn.commit()
    inserted = c.rowcount > 0
    conn.close()
    return inserted

def try_mark_and_check(msg_id):
    """ATOMIC: mark as processed AND return True only if it was new"""
    if not msg_id:
        return True  # If no msg_id, process anyway
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Try to insert - if msg_id already exists, this does nothing and rowcount=0
    c.execute("INSERT OR IGNORE INTO processed_messages (msg_id) VALUES (?)", (msg_id,))
    inserted = c.rowcount > 0
    conn.commit()
    conn.close()
    return inserted  # True = new message (was inserted), False = already existed

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
    """Save conversation - preserves quote_state by using UPDATE"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    
    # First try UPDATE (preserves quote_state)
    c.execute("""
        UPDATE conversations 
        SET name = COALESCE(?, name),
            last_message = COALESCE(?, last_message),
            last_message_time = ?
        WHERE phone = ?
    """, (name, last_message, now, phone))
    
    if c.rowcount == 0:
        # Phone not in DB yet - insert new row
        c.execute("""
            INSERT INTO conversations (phone, name, last_message, last_message_time, quote_state)
            VALUES (?, ?, ?, ?, 'none')
        """, (phone, name, last_message, now))
    
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
    
    # Cancel commands - always handled
    if text_lower in ["cancel", "stop", "exit", "nevermind", "forget it"]:
        print(f"  >>> PATH: cancel")
        result = cancel_booking_flow(phone)
        if result:
            return result
        result = cancel_quote_flow(phone)
        if result:
            return result
    
    # Check if in quote flow FIRST - before main menu
    quote_response = handle_quote_flow(phone, text)
    if quote_response:
        print(f"  >>> PATH: quote_flow")
        return quote_response
    
    # Check if in booking flow
    booking_response = handle_booking_flow(phone, text)
    if booking_response:
        print(f"  >>> PATH: booking_flow")
        return booking_response
    
    # Check for tracking intent
    tracking_response = auto_track_shipment(phone, text)
    if tracking_response:
        print(f"  >>> PATH: tracking")
        return tracking_response
    
    # Check for new quote request keywords
    quote_keywords = ["quote", "price", "cost", "rate", "how much", "shipping cost", "get a quote"]
    if any(kw in text_lower for kw in quote_keywords):
        return start_quote_flow(phone)
    
    # Check for booking keywords
    booking_keywords = ["book", "book shipment", "send package", "ship cargo"]
    if text_lower in booking_keywords:
        return start_booking_flow(phone)
    
    # Check for status command
    if text_lower == "status":
        status_response = check_booking_status_message(phone)
        if status_response:
            print(f"  >>> PATH: status_check")
            return status_response
    
    # Check main menu / navigation LAST (only for explicit menu commands)
    menu_response = get_main_menu_response(text_lower, phone)
    if menu_response:
        print(f"  >>> PATH: main_menu")
        return menu_response
    
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
    "awaiting_destination": """🌍 Where are we shipping to?

1️⃣ 🇬🇧 United Kingdom
2️⃣ 🇺🇸 United States
3️⃣ 🇨🇦 Canada""",
    "awaiting_weight": "⚖️ Perfect! What is the approximate weight?\n\n(in kg, e.g. 5kg, 10kg, 200kg)",
    "awaiting_service": """📋 How would you like it shipped?

1️⃣ ✈️ Air Freight (5-9 days)
2️⃣ 🚢 Sea Freight (25-42 days)

Just reply with 1 or 2:""",
}

SERVICE_MAP = {
    "1": ("Air Freight", "NGN 4,000-6,500/kg"),
    "2": ("Sea Freight", "NGN 380-3,000/kg"),
}

DEST_QUOTE_RATES = {
    "uk": {"air": 4500, "sea": 450},
    "us": {"air": 4500, "sea": 500},
    "ca": {"air": 6500, "sea": 3000},
}

def start_quote_flow(phone):
    # Just return the first question - handle_quote_flow will INSERT the quote_request
    return QUOTE_QUESTIONS["awaiting_destination"]
def handle_quote_flow(phone, text):
    """Process quote flow: destination → weight → service → price estimate"""
    print(f"\n--- QUOTE FLOW ---")
    print(f"  phone: {phone}, text: {text}")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM quote_requests 
        WHERE phone = ? AND status = 'pending'
        ORDER BY id DESC LIMIT 1
    """, (phone,))
    quote = c.fetchone()
    conn.close()
    
    print(f"  quote row: {dict(quote) if quote else 'None'}")
    
    # Step 1: Destination
    if not quote:
        dest_key = text.strip()
        dest_map = {"1": "🇬🇧 United Kingdom", "2": "🇺🇸 United States", "3": "🇨🇦 Canada"}
        if dest_key not in dest_map:
            return ("I didn't understand that. Please reply with 1, 2 or 3:\n\n" + 
                   QUOTE_QUESTIONS["awaiting_destination"])
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO quote_requests (phone, origin, destination, status) VALUES (?, 'Nigeria', ?, 'pending')",
            (phone, dest_map[dest_key]))
        conn.commit()
        conn.close()
        return QUOTE_QUESTIONS["awaiting_weight"]
    
    # Step 2: Weight
    elif quote['weight'] is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET weight = ? WHERE phone = ? AND status = 'pending'",
            (text.strip(), phone))
        conn.commit()
        conn.close()
        return QUOTE_QUESTIONS["awaiting_service"]
    
    # Step 3: Service → Calculate and show quote
    elif quote['service_type'] is None:
        service_key = text.strip()
        if service_key not in ["1", "2"]:
            return ("I didn't understand that. Please reply with 1 or 2:\n\n" +
                   QUOTE_QUESTIONS["awaiting_service"])
        
        dest = quote['destination']
        if "United Kingdom" in dest:
            dest_key = "uk"
        elif "United States" in dest:
            dest_key = "us"
        else:
            dest_key = "ca"
        
        try:
            weight_kg = float(''.join(filter(lambda x: x.isdigit() or x=='.', quote['weight'] or '10')))
        except:
            weight_kg = 10.0
        
        rates = DEST_QUOTE_RATES[dest_key]
        if service_key == "1":
            service_name = "Air Freight"
            price_per_kg = rates["air"]
            min_charge = 4500 if dest_key != "ca" else 6000
            transit = "5-9 business days"
        else:
            service_name = "Sea Freight"
            price_per_kg = rates["sea"]
            min_charge = 2000 if dest_key != "ca" else 3000
            transit = "25-42 days"
        
        total = max(weight_kg * price_per_kg, min_charge)
        price_str = f"₦{int(total):,}"
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET service_type = ?, estimated_price = ?, status = 'quoted' WHERE phone = ? AND status = 'pending'",
            (f"{service_name} ({transit})", price_str, phone))
        conn.commit()
        conn.close()
        
        response = (f"📦 Quote Ready!\n\n"
                   f"📍 From: Nigeria\n"
                   f"📍 To: {quote['destination']}\n"
                   f"⚖️ Weight: {weight_kg:.0f}kg\n"
                   f"🚢 {service_name} ({transit})\n"
                   f"💰 Estimated Total: {price_str}\n\n"
                   f"To book now, reply BOOK\n"
                   f"📧 Or email: info@globalline.io")
        
        send_whatsapp_message(ADMIN_NUMBER,
            f"🔔 Quote Generated!\n\nFrom: {phone}\nNigeria → {quote['destination']}\n{weight_kg:.0f}kg\n{service_name}\nEst: {price_str}")
        
        return response
    
    else:
        print(f"  >>> quote complete, returning menu")
        return MAIN_MENU



def start_booking_flow(phone):
    """Start a new booking - insert empty row"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO bookings (phone, status, origin) VALUES (?, 'collecting', 'Nigeria')
    """, (phone,))
    conn.commit()
    conn.close()
    return BOOKING_QUESTIONS["destination"]

def get_current_booking(phone):
    """Get the active collecting booking for this phone"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM bookings 
        WHERE phone = ? AND status = 'collecting' AND payment_status = 'pending'
        ORDER BY id DESC LIMIT 1
    """, (phone,))
    booking = c.fetchone()
    conn.close()
    return dict(booking) if booking else None

def handle_booking_flow(phone, text):
    """Process booking flow step by step"""
    print(f"\n--- BOOKING FLOW ---")
    print(f"  phone: {phone}, text: {text}")
    
    booking = get_current_booking(phone)
    
    if not booking:
        print("  No active booking")
        return None  # Not in booking flow
    
    # Step 1: Destination
    if booking.get('destination') is None:
        dest_key = text.strip()
        if dest_key not in DESTINATIONS:
            return ("I didn't understand that. Please reply with 1, 2, or 3:\n\n" + 
                   BOOKING_QUESTIONS["destination"])
        
        dest_name, dest_airport = DESTINATIONS[dest_key]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET destination = ? WHERE id = ?", (dest_name, booking['id']))
        conn.commit()
        conn.close()
        
        # Store dest_key for pricing calculation
        # (We use the destination text as the key for now)
        return BOOKING_QUESTIONS["receiver_name"]
    
    # Step 2: Receiver name
    elif booking.get('receiver_name') is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET receiver_name = ? WHERE id = ?", (text.strip(), booking['id']))
        conn.commit()
        conn.close()
        return BOOKING_QUESTIONS["receiver_phone"]
    
    # Step 3: Receiver phone
    elif booking.get('receiver_phone') is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET receiver_phone = ? WHERE id = ?", (text.strip(), booking['id']))
        conn.commit()
        conn.close()
        return BOOKING_QUESTIONS["receiver_address"]
    
    # Step 4: Receiver address
    elif booking.get('receiver_address') is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET receiver_address = ? WHERE id = ?", (text.strip(), booking['id']))
        conn.commit()
        conn.close()
        return BOOKING_QUESTIONS["cargo_description"]
    
    # Step 5: Cargo description
    elif booking.get('cargo_description') is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET cargo_description = ? WHERE id = ?", (text.strip(), booking['id']))
        conn.commit()
        conn.close()
        return BOOKING_QUESTIONS["weight"]
    
    # Step 6: Weight - show service options with prices
    elif booking.get('weight') is None:
        weight_kg_str = text.strip()
        # Extract number from weight string
        try:
            weight_kg = float(''.join(filter(lambda x: x.isdigit() or x=='.', weight_kg_str)))
        except:
            weight_kg = 10.0
        
        weight_kg_str = str(weight_kg)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET weight = ? WHERE id = ?", (weight_kg_str, booking['id']))
        conn.commit()
        conn.close()
        
        # Show service options with real prices for this destination
        dest = booking.get('destination', '')
        dest_key = "1"  # default UK
        if "United States" in dest:
            dest_key = "2"
        elif "Canada" in dest:
            dest_key = "3"
        
        # Get rates for this destination
        air_info = AIR_RATES[dest_key]
        sea_info = SEA_RATES[dest_key]
        air_name, air_price_low, air_price_high, air_transit = air_info
        sea_name, sea_price_low, sea_price_high, sea_transit = sea_info
        sea_min = MIN_CHARGES_SEA[dest_key]
        air_min = MIN_CHARGES_AIR[dest_key]
        
        service_msg = f"""⚖️ How would you like it shipped?

1️⃣ ✈️ {air_name} ({air_transit})
   {weight_kg:.0f}kg × ₦{air_price_low:,}/kg = ₦{max(weight_kg*air_price_low, air_min):,.0f}
   (Min charge: ₦{air_min:,})

2️⃣ 🚢 {sea_name} ({sea_transit})
   {weight_kg:.0f}kg × ₦{sea_price_low:,}/kg = ₦{max(weight_kg*sea_price_low, sea_min):,.0f}
   (Min charge: ₦{sea_min:,})

Just reply with 1 or 2:"""
        
        return service_msg
    
    # Step 7: Service type + payment
    elif booking.get('service_type') is None:
        service_key = text.strip()
        if service_key not in ["1", "2"]:
            return ("I didn't understand that. Please reply with 1 or 2:\n\n" +
                   "1️⃣ Air Freight\n2️⃣ Sea Freight")
        
        # Determine destination key
        dest = booking.get('destination', '')
        dest_key = "1"
        if "United States" in dest:
            dest_key = "2"
        elif "Canada" in dest:
            dest_key = "3"
        
        weight_kg = float(''.join(filter(lambda x: x.isdigit() or x=='.', booking.get('weight', '10'))))
        service_name, price_per_kg, min_charge, total, transit = get_rate(dest_key, service_key, weight_kg)
        estimated_price = f"₦{int(total):,}"
        
        # Generate reference
        import uuid
        ref = f"GL{int(uuid.uuid4().int)[:10]}"
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            UPDATE bookings SET service_type = ?, estimated_price = ?, paystack_ref = ? WHERE id = ?
        """, (f"{service_name} ({transit})", estimated_price, ref, booking['id']))
        conn.commit()
        conn.close()
        
        # Create Paystack payment link
        description = f"Shipping Nigeria → {dest}: {booking.get('cargo_description', 'Cargo')} - {weight_kg}kg"
        total_kobo = int(total * 100)
        payment_link = create_paystack_payment_link(total_kobo, None, phone, description, ref)
        
        msg = (f"💰 Booking Summary:\n\n"
               f"📍 From: Nigeria\n"
               f"📍 To: {booking.get('destination', 'N/A')}\n"
               f"📍 Delivery: {booking.get('receiver_address', 'N/A')}\n"
               f"📦 {booking.get('cargo_description', 'Cargo')} - {weight_kg}kg\n"
               f"🚢 {service_name} ({transit})\n"
               f"💰 Total: {estimated_price}\n\n"
               f"Click below to pay:")
        
        if payment_link:
            send_whatsapp_button(phone, msg, payment_link)
        else:
            send_whatsapp_message(phone, msg + f"\n\n🔗 Pay here: https://paystack.com/pay/{ref}")
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET status = 'awaiting_payment' WHERE id = ?", (booking['id'],))
        conn.commit()
        conn.close()
        
        return ("✅ Your payment link has been sent!\n\n"
                "Complete payment and your tracking number will be activated.\n"
                "Reply 'STATUS' to check your booking.")
    
    elif booking.get('paystack_ref') is not None:
        # Already created payment, waiting
        return ("⏳ Payment pending.\n\n"
                f"Click to pay: https://paystack.com/pay/{booking['paystack_ref']}\n\n"
                "After payment, reply 'STATUS' to get your tracking.")
    
    else:
        print("  >>> Booking flow complete (unexpected state)")
        return MAIN_MENU

def send_whatsapp_button(to, text, url):
    """Send WhatsApp message with inline button"""
    button_payload = {
        "to": to,
        "text": text,
        "buttons": [
            {"title": "💳 Pay Now", "url": url}
        ]
    }
    
    url = f"{WHAPI_ENDPOINT}/messages/text"
    headers = {
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, headers=headers, json=button_payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error sending button message: {e}")
        return {"error": str(e)}

def cancel_booking_flow(phone):
    """Cancel the current booking"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM bookings WHERE phone = ? AND status = 'collecting'", (phone,))
    conn.commit()
    conn.close()
    return MAIN_MENU

def check_booking_status_message(phone):
    """Check and report booking status for this phone"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Check most recent booking
    c.execute("""
        SELECT * FROM bookings WHERE phone = ?
        ORDER BY id DESC LIMIT 1
    """, (phone,))
    booking = c.fetchone()
    conn.close()
    
    if not booking:
        return None  # No booking found
    
    booking = dict(booking)
    
    # Check if there's a shipment with tracking
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM shipments WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,))
    shipment = c.fetchone()
    conn.close()
    
    if booking['status'] == 'confirmed' and shipment:
        return (f"📦 Booking Confirmed!\n\n"
               f"🔢 Tracking: {dict(shipment)['tracking_number']}\n"
               f"📊 Status: {dict(shipment)['status']}\n"
               f"📍 Nigeria → {booking.get('destination', 'N/A')}\n"
               f"🚢 {booking['service_type']}\n"
               f"📍 Delivery: {booking.get('receiver_address', 'N/A')}\n\n"
               f"We'll keep you updated! 🚢")
    
    elif booking['status'] == 'awaiting_payment' or booking['payment_status'] == 'pending':
        msg = (f"⏳ Payment Pending\n\n"
              f"📍 Nigeria → {booking.get('destination', 'N/A')}\n"
              f"📦 {booking.get('cargo_description', 'Cargo')} - {booking.get('weight', 'N/A')}kg\n"
              f"🚢 {booking.get('service_type', 'N/A')}\n"
              f"💰 Total: {booking.get('estimated_price', 'N/A')}\n\n"
              f"Click to pay: https://paystack.com/pay/{booking.get('paystack_ref', 'N/A')}\n\n"
              f"After payment, reply STATUS to get your tracking number.")
        return msg
    
    elif booking['payment_status'] == 'paid':
        return (f"✅ Payment Received!\n\n"
               f"Your tracking number will be sent shortly.\n"
               f"We'll notify you when it's ready.")
    
    return None

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
        print(f"\n--- RAW MESSAGE ---")
        print(json.dumps(message, indent=2)[:300])
        
        msg_id = message.get("id")
        from_me = message.get("from_me")
        phone = message.get("from")
        text = message.get("text", {}).get("body", "")
        name = message.get("contact", {}).get("name", "Customer")
        
        print(f"\n--- PARSED ---")
        print(f"  msg_id: {msg_id}")
        print(f"  from_me: {from_me}")
        print(f"  phone: {phone}")
        print(f"  text: {text[:100] if text else '(empty)'}")
        
        # Skip outgoing messages (from us)
        if from_me:
            print(f"  >>> SKIP: from_me=True (our own message)")
            continue
        
        # Deduplication - ATOMIC: try to claim this msg_id
        if not try_mark_and_check(msg_id):
            print(f"  >>> SKIP: already processed (msg_id={msg_id})")
            continue
        
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

@app.route("/webhook/paystack", methods=["POST"])
def webhook_paystack():
    """Handle Paystack payment confirmation"""
    data = request.json or {}
    event = data.get("event")
    
    print(f"\n=== PAYSTACK WEBHOOK ===")
    print(f"Event: {event}")
    print(f"Data: {json.dumps(data.get('data', {}), indent=2)}")
    
    if event == "transaction.success":
        tx_data = data.get("data", {})
        ref = tx_data.get("reference")
        status = tx_data.get("status")
        
        if ref and status == "success":
            # Find booking by paystack_ref
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM bookings WHERE paystack_ref = ?", (ref,))
            booking = c.fetchone()
            conn.close()
            
            if booking:
                # Generate tracking number
                import uuid
                tracking = "GL" + str(uuid.uuid4().int)[:10]
                
                # Update booking
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("""
                    UPDATE bookings SET 
                        payment_status = 'paid',
                        status = 'confirmed'
                    WHERE paystack_ref = ?
                """, (ref,))
                conn.commit()
                
                # Create shipment record
                c.execute("""
                    INSERT INTO shipments (tracking_number, phone, origin, destination, status)
                    VALUES (?, ?, ?, ?, 'Order Confirmed')
                """, (tracking, booking['phone'], 
                      "Nigeria",
                      booking.get('destination', 'N/A')))
                conn.commit()
                conn.close()
                
                # Notify customer
                msg = (f"✅ PAYMENT CONFIRMED!\n\n"
                       f"🔢 Your Tracking Number: {tracking}\n\n"
                       f"📦 {booking['cargo_description']} - {booking['weight']}kg\n"
                       f"🚢 {booking['service_type']}\n"
                       f"📍 To: {booking['destination']}\n"
                       f"📍 Delivery: {booking['receiver_address']}\n\n"
                       f"We'll notify you at every step of your shipment's journey!\n"
                       f"🚢 GlobalLine Logistics")
                
                send_whatsapp_message(booking['phone'], msg)
                
                # Notify admin
                send_whatsapp_message(ADMIN_NUMBER,
                    f"🔔 BOOKING PAID!\n\n"
                    f"Ref: {ref}\n"
                    f"Tracking: {tracking}\n"
                    f"Customer: {booking['phone']}\n"
                    f"{booking['cargo_description']} - {booking['weight']}\n"
                    f"Service: {booking['service_type']}")
                
                print(f"=== Payment confirmed for {ref}, tracking: {tracking} ===")
    
    return jsonify({"status": "ok"})

@app.route("/api/booking-status", methods=["GET"])
def check_booking_status():
    """Check booking status by phone"""
    phone = request.args.get("phone")
    if not phone:
        return jsonify({"error": "phone required"})
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM bookings WHERE phone = ? 
        ORDER BY id DESC LIMIT 1
    """, (phone,))
    booking = c.fetchone()
    conn.close()
    
    if not booking:
        return jsonify({"status": "not_found"})
    
    return jsonify({
        "status": dict(booking)['status'],
        "payment_status": dict(booking)['payment_status'],
        "paystack_ref": dict(booking)['paystack_ref'],
        "service": dict(booking)['service_type'],
        "price": dict(booking)['estimated_price']
    })

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

@app.route("/api/debug-db", methods=["GET"])
def debug_db():
    """Debug: show all DB state"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Conversations
    c.execute("SELECT * FROM conversations")
    convs = [dict(r) for r in c.fetchall()]
    
    # Quote requests
    c.execute("SELECT * FROM quote_requests ORDER BY id DESC LIMIT 20")
    quotes = [dict(r) for r in c.fetchall()]
    
    # Processed messages
    c.execute("SELECT * FROM processed_messages ORDER BY processed_at DESC LIMIT 20")
    processed = [dict(r) for r in c.fetchall()]
    
    conn.close()
    
    return jsonify({
        "conversations": convs,
        "quote_requests": quotes,
        "processed_messages": processed
    })

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