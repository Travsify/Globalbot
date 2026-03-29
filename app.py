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
import uuid

app = Flask(__name__)

# Config
WHAPI_TOKEN = os.environ.get("WHAPI_TOKEN")
WHAPI_ENDPOINT = "https://gate.whapi.cloud"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY")
ADMIN_NUMBER = "447490347577"
DB_PATH = os.environ.get("DB_PATH", "/tmp/globalline.db")

# ==========================================
# PRICING - Nigeria → International
# ==========================================

DESTINATIONS = {
    "1": "🇬🇧 United Kingdom",
    "2": "🇺🇸 United States",
    "3": "🇨🇦 Canada",
}

DEST_AIRPORTS = {
    "1": "London (LHR)",
    "2": "New York (JFK)",
    "3": "Toronto (YYZ)",
}

# Express Air: (price_under_500kg, price_500kg_plus, min_charge, transit)
AIR_RATES = {
    "1": (4500, 4000, 4500, "3-5 days"),
    "2": (4500, 4000, 4500, "3-5 days"),
    "3": (6500, 6000, 6000, "5-7 days"),
}

# Ocean: (price_under_500kg, price_500kg_plus, min_charge, transit)
SEA_RATES = {
    "1": (450, 380, 2000, "25-35 days"),
    "2": (500, 400, 2000, "25-35 days"),
    "3": (3000, 2500, 3000, "30-42 days"),
}

# Door-to-Door UK zones: (rate_per_kg, cap)
UK_DOOR_TO_DOOR = {
    "1": (400, 1600),   # Greater London
    "2": (600, 1600),   # South East England
    "3": (800, 1600),   # Midlands
    "4": (1600, 1600),  # North/Scotland/Wales
}

UK_DOOR_ZONE_NAMES = {
    "1": "Greater London",
    "2": "South East England",
    "3": "Midlands (Birmingham, etc.)",
    "4": "North/Scotland/Wales",
}

# ==========================================
# BOOKING QUESTIONS
# ==========================================

Q = {
    "dest": """🌍 Where are we shipping to?

1️⃣ 🇬🇧 United Kingdom
2️⃣ 🇺🇸 United States
3️⃣ 🇨🇦 Canada

Just reply with 1, 2, or 3:""",

    "receiver_name": "📛 What's the receiver's full name?",

    "receiver_phone": "📱 Receiver's phone number?",

    "address": "🏠 Full delivery address?\n(city, street, postal code)",

    "cargo": "📦 What are you shipping?\n(brief description)",

    "weight": """⚖️ Estimated weight?
(in kg, e.g. 10kg, 25kg, 100kg)""",

    "service": """🚢 How would you like to ship?

1️⃣ ✈️ Express Air (3-5 days)
2️⃣ 🚢 Ocean Freight (25-35 days)
3️⃣ 🚛 Road Freight (contact for quote)

Just reply with 1, 2, or 3:""",

    "door": """🏠 Door-to-Door delivery?

1️⃣ Yes, deliver to my address (+£/$)
2️⃣ No, I'll pick up at airport

Just reply with 1 or 2:""",

    "door_zone_uk": """📍 Select delivery zone (UK):

1️⃣ Greater London (+₦400/kg, cap ₦1,600)
2️⃣ South East England (+₦600/kg, cap ₦1,600)
3️⃣ Midlands (+₦800/kg, cap ₦1,600)
4️⃣ North/Scotland/Wales (+₦1,600/kg, cap ₦1,600)

Just reply with 1, 2, 3, or 4:""",
}

def get_rate(dest_key, service_key, weight_kg):
    """Calculate shipping cost"""
    w = float(weight_kg)
    if service_key == "1":  # Express Air
        rate_key = "air"
    elif service_key == "2":  # Ocean
        rate_key = "sea"
    else:
        return None, None, None, None, "Contact for quote"

    if rate_key == "air":
        rates = AIR_RATES[dest_key]
        if w >= 500:
            price_per_kg = rates[1]
        else:
            price_per_kg = rates[0]
        min_charge = rates[2]
        transit = rates[3]
        service_name = "Express Air"
    else:
        rates = SEA_RATES[dest_key]
        if w >= 500:
            price_per_kg = rates[1]
        else:
            price_per_kg = rates[0]
        min_charge = rates[2]
        transit = rates[3]
        service_name = "Ocean Freight"

    total = max(w * price_per_kg, min_charge)
    return service_name, price_per_kg, min_charge, total, transit

def calc_door_fee(zone_key, weight_kg):
    """Calculate door-to-door fee with cap"""
    rate, cap = UK_DOOR_TO_DOOR[zone_key]
    w = float(weight_kg)
    fee = min(w * rate, cap)
    return int(fee)

# ==========================================
# SYSTEM PROMPT
# ==========================================

SYSTEM_PROMPT = """You are GlobalLine Logistics AI assistant on WhatsApp. Help customers with shipping from Nigeria to international destinations.

SERVICES:
1. Express Air Freight (3-5 days) - fastest
2. Ocean Freight (25-35 days) - most economical
3. Road Freight - regional

Keep responses short and helpful. Use emojis. Guide customers to use the menu options (1-5)."""

# ==========================================
# MAIN MENU
# ==========================================

MAIN_MENU = """🏢 GlobalLine Logistics
International Shipping from Nigeria

How can I help you today?

1️⃣ 📦 Get a Quote
2️⃣ 🚢 Book a Shipment
3️⃣ 📍 Track My Shipment
4️⃣ 📋 Our Services
5️⃣ 💬 Contact Us

Just reply with a number (1-5)! 🚢"""

SERVICES_LIST = """📋 GlobalLine Services

✈️ EXPRESS AIR FREIGHT
   Fastest - 3-5 days
   From ₦4,000/kg

🚢 OCEAN FREIGHT
   Most economical - 25-35 days
   From ₦380/kg

🚛 ROAD FREIGHT
   Regional - contact for quote

📦 WAREHOUSING & DISTRIBUTION
   Secure storage & handling

🛒 E-COMMERCE LOGISTICS
   End-to-end for online sellers

🛠️ CUSTOM SOLUTIONS
   Tailored to your needs

🌍 GLOBAL VIRTUAL ADDRESSES
   Shop from US/UK & ship to Nigeria

💳 PAY SUPPLIERS
   We pay your suppliers globally

🔍 SOURCE FOR ME
   We find products for you

🏪 MARKETPLACE
   Shop from our catalog

━━━━━━━━━━━━━━━
💬 Questions? Reply anytime!
🌐 globalline.io"""

CONTACT_INFO = """💬 GlobalLine Contact Us

📍 Nigeria (Head Office):
No 7. JoyceB Road, Off Mobil,
Ring Road, Ibadan, Oyo State
📱 +234 704 700 1714

📍 United Kingdom:
📱 +44 7478 059581

📍 United States:
📱 +1 (211) 358-16478

📧 Email: Info@globalline.io
🌐 Website: globalline.io

💬 We're here to help! 🚢"""

# ==========================================
# DATABASE
# ==========================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
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
        CREATE TABLE IF NOT EXISTS quote_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            origin TEXT DEFAULT 'Nigeria',
            destination TEXT,
            weight TEXT,
            service_type TEXT,
            estimated_price TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            destination TEXT,
            receiver_name TEXT,
            receiver_phone TEXT,
            address TEXT,
            cargo_description TEXT,
            weight TEXT,
            service_type TEXT,
            service_key TEXT,
            dest_key TEXT,
            door_to_door TEXT DEFAULT 'no',
            door_zone TEXT,
            door_fee INTEGER DEFAULT 0,
            freight_total INTEGER DEFAULT 0,
            estimated_price TEXT,
            paystack_ref TEXT,
            payment_status TEXT DEFAULT 'pending',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_number TEXT UNIQUE,
            phone TEXT,
            origin TEXT,
            destination TEXT,
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

init_db()

# ==========================================
# HELPERS
# ==========================================

def send_whatsapp_message(to, text):
    url = f"{WHAPI_ENDPOINT}/messages/text"
    headers = {
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"to": to, "text": text}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return {"error": str(e)}

def send_whatsapp_button(to, text, url):
    """Send message with clickable button"""
    payload = {
        "to": to,
        "text": text,
        "buttons": [{"title": "💳 Pay Now", "url": url}]
    }
    url = f"{WHAPI_ENDPOINT}/messages/text"
    headers = {
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error sending button: {e}")
        return {"error": str(e)}

def save_message(phone, message, direction):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (phone, message, direction) VALUES (?, ?, ?)",
              (phone, message, direction))
    conn.commit()
    conn.close()

def save_conversation(phone, name=None, last_message=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        UPDATE conversations 
        SET name = COALESCE(?, name),
            last_message = COALESCE(?, last_message),
            last_message_time = ?
        WHERE phone = ?
    """, (name, last_message, now, phone))
    if c.rowcount == 0:
        c.execute("""
            INSERT INTO conversations (phone, name, last_message, last_message_time)
            VALUES (?, ?, ?, ?)
        """, (phone, name, last_message, now))
    conn.commit()
    conn.close()

def try_mark_and_check(msg_id):
    """Atomic deduplication"""
    if not msg_id:
        return True
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO processed_messages (msg_id) VALUES (?)", (msg_id,))
    inserted = c.rowcount > 0
    conn.commit()
    conn.close()
    return inserted

def get_conversation_context(phone, limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT * FROM messages WHERE phone = ? 
        ORDER BY created_at DESC LIMIT ?
    """, (phone, limit))
    rows = c.fetchall()
    conn.close()
    return [dict(id=r[0], phone=r[1], message=r[2], direction=r[3], created_at=r[4]) for r in reversed(rows)]

def get_active_booking(phone):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM bookings 
        WHERE phone = ? AND status = 'collecting' AND payment_status = 'pending'
        ORDER BY id DESC LIMIT 1
    """, (phone,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_pending_quote(phone):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM quote_requests 
        WHERE phone = ? AND status = 'pending'
        ORDER BY id DESC LIMIT 1
    """, (phone,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

# ==========================================
# QUOTE FLOW
# ==========================================

def start_quote(phone):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM quote_requests WHERE phone = ? AND status = 'pending'", (phone,))
    c.execute("INSERT INTO quote_requests (phone, status) VALUES (?, 'pending')", (phone,))
    conn.commit()
    conn.close()
    return Q["dest"]

def handle_quote(phone, text):
    """Quote: dest → weight → service → door → zone → price"""
    quote = get_pending_quote(phone)
    if not quote:
        return None  # Not in quote flow

    # Step 1: Destination
    if quote['destination'] is None:
        key = text.strip()
        if key not in DESTINATIONS:
            return ("Please reply with 1, 2, or 3:\n\n" + Q["dest"])
        dest_name = DESTINATIONS[key]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET destination = ? WHERE phone = ? AND status = 'pending'",
                  (dest_name, phone))
        conn.commit()
        conn.close()
        return Q["weight"]
    
    # Step 2: Weight
    elif quote['weight'] is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET weight = ? WHERE phone = ? AND status = 'pending'",
                  (text.strip(), phone))
        conn.commit()
        conn.close()
        return Q["service"]
    
    # Step 3: Service type
    elif quote['service_type'] is None:
        key = text.strip()
        if key not in ["1", "2", "3"]:
            return ("Please reply with 1, 2, or 3:\n\n" + Q["service"])
        
        if key == "3":
            # Road - contact for quote
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE quote_requests SET service_type = ?, status = 'quoted' WHERE phone = ? AND status = 'pending'",
                      ("Road Freight", phone))
            conn.commit()
            conn.close()
            return ("📦 Quote Ready!\n\n"
                   f"📍 Nigeria → {quote['destination']}\n"
                   f"⚖️ {quote['weight']}\n"
                   f"🚛 Road Freight\n\n"
                   f"💰 Road Freight: Contact for quote\n\n"
                   f"📧 Email: Info@globalline.io or call +234 704 700 1714\n\n"
                   f"Ready to book? Reply BOOK 🚢")
        
        # Store service key
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET service_type = ? WHERE phone = ? AND status = 'pending'",
                  (f"service:{key}", phone))
        conn.commit()
        conn.close()
        
        # For door-to-door, only ask if UK destination
        dest_key = None
        for k, v in DESTINATIONS.items():
            if v == quote['destination']:
                dest_key = k
                break
        
        if dest_key == "1":  # UK
            return Q["door"]
        else:
            # Skip door step, go to price for non-UK
            return finish_quote(phone)
    
    # Step 4: Door-to-door
    elif "service:" in (quote['service_type'] or ""):
        key = text.strip()
        
        # Get service key from stored value
        service_key = quote['service_type'].split(":")[1]
        
        if key == "1":  # Yes door
            # Ask zone
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE quote_requests SET service_type = ? WHERE phone = ? AND status = 'pending'",
                      (f"door_yes:{service_key}", phone))
            conn.commit()
            conn.close()
            return Q["door_zone_uk"]
        
        elif key == "2":  # No door
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE quote_requests SET service_type = ? WHERE phone = ? AND status = 'pending'",
                      (f"door_no:{service_key}", phone))
            conn.commit()
            conn.close()
            return finish_quote(phone)
        
        return ("Please reply with 1 or 2:\n\n" + Q["door"])
    
    # Step 5: Door zone
    elif quote['service_type'].startswith("door_yes:"):
        zone_key = text.strip()
        if zone_key not in UK_DOOR_TO_DOOR:
            return ("Please reply with 1, 2, 3, or 4:\n\n" + Q["door_zone_uk"])
        
        service_key = quote['service_type'].split(":")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE quote_requests SET service_type = ? WHERE phone = ? AND status = 'pending'",
                  (f"zone:{zone_key}:{service_key}", phone))
        conn.commit()
        conn.close()
        return finish_quote(phone)
    
    else:
        return None  # Done

def finish_quote(phone):
    """Calculate and show quote"""
    quote = get_pending_quote(phone)
    if not quote:
        return None
    
    # Determine dest key
    dest_key = "1"
    for k, v in DESTINATIONS.items():
        if v == quote['destination']:
            dest_key = k
            break
    
    # Determine service and door
    stype = quote['service_type'] or ""
    door_yes = stype.startswith("door_yes:") or stype.startswith("zone:")
    zone_key = None
    if stype.startswith("zone:"):
        parts = stype.split(":")
        zone_key = parts[1]
        service_key = parts[2]
    elif stype.startswith("door_yes:"):
        service_key = stype.split(":")[1]
    elif stype.startswith("door_no:"):
        service_key = stype.split(":")[1]
    else:
        service_key = "1"
    
    # Get weight
    try:
        weight_kg = float(''.join(filter(lambda x: x.isdigit() or x=='.', quote['weight'] or "10")))
    except:
        weight_kg = 10.0
    
    # Calculate freight
    service_name, price_per_kg, min_charge, freight, transit = get_rate(dest_key, service_key, weight_kg)
    
    # Calculate door fee
    door_fee = 0
    door_display = "No"
    if door_yes and zone_key:
        door_fee = calc_door_fee(zone_key, weight_kg)
        zone_name = UK_DOOR_ZONE_NAMES.get(zone_key, "Selected area")
        door_display = f"Yes ({zone_name})"
    
    total = freight + door_fee
    freight_str = f"₦{int(freight):,}"
    door_str = f"₦{door_fee:,}" if door_fee else "—"
    total_str = f"₦{int(total):,}"
    
    # Update quote with final service type and price
    final_service = service_name
    if door_yes:
        final_service += " + Door-to-Door"
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE quote_requests SET service_type = ?, estimated_price = ?, status = 'quoted' WHERE phone = ? AND status = 'pending'",
              (final_service, total_str, phone))
    conn.commit()
    conn.close()
    
    msg = (f"📦 QUOTE READY!\n\n"
           f"━━━━━━━━━━━━━━━\n"
           f"📍 Nigeria → {quote['destination']}\n"
           f"⚖️ {weight_kg:.0f}kg\n"
           f"🚢 {service_name}\n"
           f"🏠 Door-to-Door: {door_display}\n"
           f"━━━━━━━━━━━━━━━\n"
           f"Freight:        {freight_str}\n")
    if door_fee:
        msg += f"Door-to-Door:  + {door_str}\n"
    msg += (f"━━━━━━━━━━━━━━━\n"
           f"TOTAL:         {total_str}\n"
           f"━━━━━━━━━━━━━━━\n\n"
           f"Ready to book? Reply BOOK! 🚢\n"
           f"Questions? Reply anytime!")
    
    send_whatsapp_message(ADMIN_NUMBER,
        f"🔔 Quote Generated!\n\nFrom: {phone}\nNigeria → {quote['destination']}\n{weight_kg:.0f}kg\n{service_name}\nTotal: {total_str}")
    
    return msg

# ==========================================
# BOOKING FLOW
# ==========================================

def start_booking(phone):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM bookings WHERE phone = ? AND status = 'collecting'", (phone,))
    c.execute("INSERT INTO bookings (phone, status) VALUES (?, 'collecting')", (phone,))
    conn.commit()
    conn.close()
    return Q["dest"]

def handle_booking(phone, text):
    """Booking: dest → receiver → phone → address → cargo → weight → service → door → zone → PAY"""
    booking = get_active_booking(phone)
    if not booking:
        return None  # Not in booking flow

    # Step 1: Destination
    if booking.get('destination') is None:
        key = text.strip()
        if key not in DESTINATIONS:
            return ("Please reply with 1, 2, or 3:\n\n" + Q["dest"])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET destination = ?, dest_key = ? WHERE id = ?",
                  (DESTINATIONS[key], key, booking['id']))
        conn.commit()
        conn.close()
        return Q["receiver_name"]
    
    # Step 2: Receiver name
    elif booking.get('receiver_name') is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET receiver_name = ? WHERE id = ?", (text.strip(), booking['id']))
        conn.commit()
        conn.close()
        return Q["receiver_phone"]
    
    # Step 3: Receiver phone
    elif booking.get('receiver_phone') is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET receiver_phone = ? WHERE id = ?", (text.strip(), booking['id']))
        conn.commit()
        conn.close()
        return Q["address"]
    
    # Step 4: Address
    elif booking.get('address') is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET address = ? WHERE id = ?", (text.strip(), booking['id']))
        conn.commit()
        conn.close()
        return Q["cargo"]
    
    # Step 5: Cargo
    elif booking.get('cargo_description') is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET cargo_description = ? WHERE id = ?", (text.strip(), booking['id']))
        conn.commit()
        conn.close()
        return Q["weight"]
    
    # Step 6: Weight
    elif booking.get('weight') is None:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET weight = ? WHERE id = ?", (text.strip(), booking['id']))
        conn.commit()
        conn.close()
        return Q["service"]
    
    # Step 7: Service
    elif booking.get('service_type') is None:
        key = text.strip()
        if key not in ["1", "2", "3"]:
            return ("Please reply with 1, 2, or 3:\n\n" + Q["service"])
        
        if key == "3":
            return ("🚛 Road Freight: Please contact us for a quote.\n\n"
                   "📧 Info@globalline.io\n"
                   "📱 +234 704 700 1714\n\n"
                   "Or reply CANCEL to start over.")
        
        service_name, price_per_kg, min_charge, freight, transit = get_rate(
            booking['dest_key'], key, booking['weight'])
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET service_type = ?, service_key = ?, freight_total = ? WHERE id = ?",
                  (service_name, key, int(freight), booking['id']))
        conn.commit()
        conn.close()
        
        # Ask door-to-door only for UK
        if booking['dest_key'] == "1":
            return Q["door"]
        else:
            return finish_booking(phone)
    
    # Step 8: Door-to-door (UK only)
    elif booking.get('door_to_door') is None or booking.get('door_to_door') == '':
        key = text.strip()
        if key == "1":  # Yes
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE bookings SET door_to_door = 'yes' WHERE id = ?", (booking['id'],))
            conn.commit()
            conn.close()
            return Q["door_zone_uk"]
        elif key == "2":  # No
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE bookings SET door_to_door = 'no', door_fee = 0 WHERE id = ?", (booking['id'],))
            conn.commit()
            conn.close()
            return finish_booking(phone)
        return ("Please reply with 1 or 2:\n\n" + Q["door"])
    
    # Step 9: Door zone (UK only)
    elif booking.get('door_zone') is None and booking.get('door_to_door') == 'yes':
        zone_key = text.strip()
        if zone_key not in UK_DOOR_TO_DOOR:
            return ("Please reply with 1, 2, 3, or 4:\n\n" + Q["door_zone_uk"])
        
        door_fee = calc_door_fee(zone_key, booking['weight'])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bookings SET door_zone = ?, door_fee = ? WHERE id = ?",
                  (UK_DOOR_ZONE_NAMES[zone_key], door_fee, booking['id']))
        conn.commit()
        conn.close()
        return finish_booking(phone)
    
    else:
        return None  # Done

def finish_booking(phone):
    """Create payment link and send summary"""
    booking = get_active_booking(phone)
    if not booking:
        return None
    
    try:
        weight_kg = float(''.join(filter(lambda x: x.isdigit() or x=='.', booking['weight'] or "10")))
    except:
        weight_kg = 10.0
    
    freight = booking.get('freight_total', 0)
    door_fee = booking.get('door_fee', 0)
    total = freight + door_fee
    total_str = f"₦{int(total):,}"
    freight_str = f"₦{int(freight):,}"
    door_str = f"₦{int(door_fee):,}" if door_fee else "—"
    
    # Generate ref
    ref = f"GL{int(uuid.uuid4().int)[:10]}"
    
    # Update booking
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""UPDATE bookings SET 
        estimated_price = ?, paystack_ref = ?, status = 'awaiting_payment'
        WHERE id = ?""",
        (total_str, ref, booking['id']))
    conn.commit()
    conn.close()
    
    # Create Paystack link
    payment_link = None
    if PAYSTACK_SECRET_KEY:
        desc = f"Shipping Nigeria → {booking['destination']}: {booking['cargo_description']} - {weight_kg:.0f}kg"
        url = "https://api.paystack.co/transaction/link"
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "amount": int(total * 100),
            "email": f"{phone}@globalline.io",
            "currency": "NGN",
            "reference": ref,
            "description": desc,
            "customer_phone": phone,
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            result = r.json()
            if result.get("status"):
                payment_link = result["data"]["link"]
        except Exception as e:
            print(f"Paystack error: {e}")
    
    msg = (f"💰 BOOKING SUMMARY\n"
           f"━━━━━━━━━━━━━━━\n"
           f"📍 Nigeria → {booking['destination']}\n"
           f"🏠 {booking['address']}\n"
           f"👤 {booking['receiver_name']} 📱 {booking['receiver_phone']}\n"
           f"📦 {booking['cargo_description']} - {weight_kg:.0f}kg\n"
           f"🚢 {booking['service_type']}\n"
           f"━━━━━━━━━━━━━━━\n"
           f"Freight:        {freight_str}\n")
    if door_fee:
        msg += f"Door-to-Door:  + {door_str}\n"
    msg += (f"━━━━━━━━━━━━━━━\n"
           f"TOTAL:         {total_str}\n"
           f"━━━━━━━━━━━━━━━\n\n"
           f"💳 Click below to PAY:\n")
    
    if payment_link:
        send_whatsapp_button(phone, msg, payment_link)
    else:
        send_whatsapp_message(phone, msg + f"\n🔗 Pay: https://paystack.com/pay/{ref}")
    
    return ("✅ Payment link sent!\n\n"
           f"Complete payment and your tracking number will be activated.\n"
           f"Reply STATUS to check your booking.")

# ==========================================
# PAYSTACK WEBHOOK
# ==========================================

@app.route("/webhook/paystack", methods=["POST"])
def webhook_paystack():
    data = request.json or {}
    event = data.get("event")
    print(f"\n=== PAYSTACK: {event} ===")
    
    if event == "transaction.success":
        tx = data.get("data", {})
        ref = tx.get("reference")
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM bookings WHERE paystack_ref = ?", (ref,))
        booking = c.fetchone()
        conn.close()
        
        if booking:
            b = dict(booking)
            tracking = "GL" + str(uuid.uuid4().int)[:10]
            
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE bookings SET payment_status = 'paid', status = 'confirmed' WHERE paystack_ref = ?", (ref,))
            c.execute("""INSERT INTO shipments (tracking_number, phone, origin, destination, status)
                         VALUES (?, ?, 'Nigeria', ?, 'Order Confirmed')""",
                     (tracking, b['phone'], b['destination']))
            conn.commit()
            conn.close()
            
            try:
                weight_kg = float(''.join(filter(lambda x: x.isdigit() or x=='.', b['weight'] or "10")))
            except:
                weight_kg = 10.0
            
            msg = (f"✅ PAYMENT CONFIRMED!\n\n"
                   f"🔢 Tracking: {tracking}\n\n"
                   f"━━━━━━━━━━━━━━━\n"
                   f"📍 Nigeria → {b['destination']}\n"
                   f"🏠 {b['address']}\n"
                   f"📦 {b['cargo_description']} - {weight_kg:.0f}kg\n"
                   f"🚢 {b['service_type']}\n"
                   f"💰 Paid: {b['estimated_price']}\n"
                   f"━━━━━━━━━━━━━━━\n\n"
                   f"📋 Next Steps:\n"
                   f"• Drop off at: No 7. JoyceB Road, Off Mobil, Ring Road, Ibadan\n"
                   f"• Or reply PICKUP to schedule collection\n\n"
                   f"🚢 We'll notify you every step!\n"
                   f"GlobalLine Logistics 🚢")
            
            send_whatsapp_message(b['phone'], msg)
            send_whatsapp_message(ADMIN_NUMBER,
                f"🔔 BOOKING PAID!\n\nRef: {ref}\nTracking: {tracking}\n{b['phone']}\n{b['cargo_description']} - {b['weight']}kg\n{b['service_type']}\nTotal: {b['estimated_price']}")
    
    return jsonify({"status": "ok"})

# ==========================================
# AI RESPONSE GENERATOR
# ==========================================

def generate_ai_response(phone, user_message):
    text = user_message.strip()
    text_lower = text.lower()
    
    print(f"\n--- INCOMING: {text[:50]} ---")
    
    # Cancel
    if text_lower in ["cancel", "stop", "exit", "nevermind"]:
        # Cancel both flows
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM bookings WHERE phone = ? AND status = 'collecting'", (phone,))
        c.execute("DELETE FROM quote_requests WHERE phone = ? AND status = 'pending'", (phone,))
        conn.commit()
        conn.close()
        return MAIN_MENU
    
    # Check booking flow
    booking_response = handle_booking(phone, text)
    if booking_response:
        print(f"  >>> BOOKING")
        return booking_response
    
    # Check quote flow
    quote_response = handle_quote(phone, text)
    if quote_response:
        print(f"  >>> QUOTE")
        return quote_response
    
    # Menu / Navigation
    if text_lower in ["menu", "hi", "hello", "hey", "start"]:
        return MAIN_MENU
    
    if text_lower in ["1", "quote"]:
        return start_quote(phone)
    
    if text_lower in ["2", "book"]:
        return start_booking(phone)
    
    if text_lower in ["3", "track", "tracking"]:
        return ("📍 Send me your tracking number!\n\n"
               "E.g. GL1234567890\n\n"
               "Or reply MENU to go back.")
    
    if text_lower in ["4", "services", "list services"]:
        return SERVICES_LIST
    
    if text_lower in ["5", "contact", "help"]:
        return CONTACT_INFO
    
    # Status check
    if text_lower == "status":
        return check_status(phone)
    
    # Track specific number
    if text_lower.startswith("gl"):
        return auto_track(phone, text.upper())
    
    # Quote completion redirect
    if text_lower == "book" or "confirm booking" in text_lower:
        return start_booking(phone)
    
    # Fallback: AI chat
    context = get_conversation_context(phone, limit=10)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in context:
        role = "user" if msg["direction"] == "incoming" else "assistant"
        messages.append({"role": role, "content": msg["message"]})
    messages.append({"role": "user", "content": text})
    
    try:
        req_data = json.dumps({
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "max_tokens": 500,
            "temperature": 0.7
        }).encode()
        
        req = urllib.request.Request(
            GROQ_ENDPOINT,
            data=req_data,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Groq error: {e}")
        return MAIN_MENU

def check_status(phone):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM bookings WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,))
    booking = c.fetchone()
    conn.close()
    
    if not booking:
        return "No booking found. Reply MENU to start!"
    
    b = dict(booking)
    
    if b['status'] == 'confirmed' and b['payment_status'] == 'paid':
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM shipments WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,))
        shipment = c.fetchone()
        conn.close()
        if shipment:
            s = dict(shipment)
            return (f"📦 Booking Confirmed!\n\n"
                   f"🔢 Tracking: {s['tracking_number']}\n"
                   f"📊 Status: {s['status']}\n"
                   f"━━━━━━━━━━━━━━━\n"
                   f"📍 Nigeria → {b['destination']}\n"
                   f"📦 {b['cargo_description']}\n"
                   f"🚢 {b['service_type']}\n\n"
                   f"🚢 We'll update you soon!")
        return (f"✅ Payment confirmed!\n\n"
               f"📦 {b['cargo_description']} - {b['weight']}kg\n"
               f"Tracking number coming soon...")
    
    if b['status'] == 'awaiting_payment':
        return (f"⏳ Payment Pending\n\n"
               f"━━━━━━━━━━━━━━━\n"
               f"📍 Nigeria → {b['destination']}\n"
               f"📦 {b['cargo_description']}\n"
               f"💰 Total: {b['estimated_price']}\n"
               f"━━━━━━━━━━━━━━━\n\n"
               f"🔗 Pay here: https://paystack.com/pay/{b['paystack_ref']}\n\n"
               f"After payment, reply STATUS.")
    
    return MAIN_MENU

def auto_track(phone, text):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM shipments WHERE tracking_number = ?", (text.upper(),))
    shipment = c.fetchone()
    conn.close()
    
    if shipment:
        s = dict(shipment)
        return (f"📦 Shipment Found!\n\n"
               f"🔢 {s['tracking_number']}\n"
               f"📊 Status: {s['status']}\n"
               f"📍 {s['origin']} → {s['destination']}\n\n"
               f"🚢 We'll notify you every step!")
    
    return (f"🔍 {text} not found.\n\n"
           f"Check your tracking number or contact us:\n"
           f"📧 Info@globalline.io")

# ==========================================
# WHAPI WEBHOOK
# ==========================================

@app.route("/webhook/whapi", methods=["GET", "POST"])
def webhook_whapi():
    if request.method == "GET":
        return jsonify({"status": "ok"})
    
    data = request.json or {}
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"status": "ok"})
    
    for message in messages:
        msg_id = message.get("id")
        if message.get("from_me"):
            continue
        if not try_mark_and_check(msg_id):
            continue
        
        phone = message.get("from")
        text = message.get("text", {}).get("body", "")
        name = message.get("from_name", "Customer")
        
        if not text:
            continue
        
        print(f"📩 {phone}: {text[:80]}")
        
        save_message(phone, text, "incoming")
        save_conversation(phone, name, text)
        
        response = generate_ai_response(phone, text)
        
        save_message(phone, response, "outgoing")
        send_whatsapp_message(phone, response)
    
    return jsonify({"status": "ok"})

@app.route("/webhook/status", methods=["POST"])
def webhook_status():
    return jsonify({"status": "ok"})

# ==========================================
# API ROUTES
# ==========================================

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "GlobalLine WhatsApp Bot"})

@app.route("/api/reset-db", methods=["GET"])
def reset_db():
    import os
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    return jsonify({"status": "ok", "message": "Database reset"})

@app.route("/api/debug-db", methods=["GET"])
def debug_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    bookings = [dict(r) for r in c.execute("SELECT * FROM bookings ORDER BY id DESC LIMIT 10")]
    quotes = [dict(r) for r in c.execute("SELECT * FROM quote_requests ORDER BY id DESC LIMIT 10")]
    shipments = [dict(r) for r in c.execute("SELECT * FROM shipments ORDER BY id DESC LIMIT 10")]
    conn.close()
    return jsonify({"bookings": bookings, "quotes": quotes, "shipments": shipments})

@app.route("/api/add-shipment", methods=["POST"])
def add_shipment():
    d = request.json or {}
    phone = d.get("phone")
    origin = d.get("origin", "Nigeria")
    destination = d.get("destination", "Unknown")
    tracking = "GL" + str(uuid.uuid4().int)[:10]
    status = d.get("status", "In Transit")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO shipments (tracking_number, phone, origin, destination, status) VALUES (?, ?, ?, ?, ?)",
              (tracking, phone, origin, destination, status))
    conn.commit()
    conn.close()
    
    if phone:
        send_whatsapp_message(phone,
            f"📦 Shipment Update!\n\n🔢 {tracking}\n📊 Status: {status}\n📍 {origin} → {destination}")
    
    return jsonify({"tracking": tracking, "status": status})

@app.route("/api/update-shipment", methods=["POST"])
def update_shipment():
    d = request.json or {}
    tracking = d.get("tracking_number")
    status = d.get("status")
    phone = d.get("phone")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE shipments SET status = ? WHERE tracking_number = ?", (status, tracking))
    conn.commit()
    if c.rowcount > 0 and phone:
        send_whatsapp_message(phone,
            f"📦 Shipment Update!\n\n🔢 {tracking}\n📊 Status: {status}")
    conn.close()
    return jsonify({"ok": c.rowcount > 0})

@app.route("/api/shipments", methods=["GET"])
def list_shipments():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM shipments ORDER BY id DESC LIMIT 100")]
    conn.close()
    return jsonify({"shipments": rows})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
