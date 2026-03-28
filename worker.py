#!/usr/bin/env python3
"""
GlobalLine WhatsApp - Background Worker
Handles follow-ups, alerts, and scheduled messages
"""

import os
import sqlite3
import requests
from datetime import datetime, timedelta
import time

# Config
WHAPI_TOKEN = "ut9iTWoHtpK1tPpPVmtQSytn3HcZtLNO"
WHAPI_ENDPOINT = "https://gate.whapi.cloud"
DB_PATH = "/data/globalline-whatsapp/automation.db"
ADMIN_NUMBER = "447490347577"

def send_whatsapp_message(to, text):
    """Send WhatsApp message via WHAPI"""
    url = f"{WHAPI_ENDPOINT}/messages/text"
    headers = {
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "typing": True,
        "to": to,
        "body": text
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return {"error": str(e)}

def process_follow_ups():
    """Check and send follow-up messages"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get pending follow-ups that are due
    c.execute("""
        SELECT * FROM follow_ups 
        WHERE sent = 0 
        AND datetime(created_at, '+' || day || ' days') <= datetime('now')
    """)
    pending = c.fetchall()
    
    for follow_up in pending:
        phone = follow_up[1]
        message = follow_up[3]
        
        # Send message
        result = send_whatsapp_message(phone, message)
        print(f"Follow-up sent to {phone}: {message[:50]}...")
        
        # Mark as sent
        c.execute("UPDATE follow_ups SET sent = 1 WHERE id = ?", (follow_up[0],))
    
    conn.commit()
    conn.close()

def check_quote_requests():
    """Check for pending quote requests and send alerts"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get new quote requests (unresponded for > 1 hour)
    c.execute("""
        SELECT * FROM quote_requests 
        WHERE status = 'new' 
        AND datetime(created_at, '+1 hour') <= datetime('now')
    """)
    pending = c.fetchall()
    
    if pending:
        # Alert admin
        alert_msg = f"🔔 {len(pending)} pending quote requests need attention!\n\n"
        for q in pending[:5]:  # Show first 5
            alert_msg += f"• {q[1]} - {q[2]} → {q[3]} ({q[4]}kg)\n"
        
        send_whatsapp_message(ADMIN_NUMBER, alert_msg)
    
    conn.close()

def daily_summary():
    """Send daily summary to admin"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Count today's conversations
    c.execute("""
        SELECT COUNT(*) FROM conversations 
        WHERE date(last_message_time) = date('now')
    """)
    today_convos = c.fetchone()[0]
    
    # Count today's quotes
    c.execute("""
        SELECT COUNT(*) FROM quote_requests 
        WHERE date(created_at) = date('now')
    """)
    today_quotes = c.fetchone()[0]
    
    # Total conversations
    c.execute("SELECT COUNT(*) FROM conversations")
    total_convos = c.fetchone()[0]
    
    conn.close()
    
    summary = f"""📊 GLOBALLINE DAILY SUMMARY

📅 Date: {today}

💬 Conversations today: {today_convos}
📦 Quote requests today: {today_quotes
 total_convos}
👥 Total customers: {total_convos}

🚢 GlobalLine Logistics"""
    
    send_whatsapp_message(ADMIN_NUMBER, summary)

def worker_loop():
    """Main worker loop"""
    print("🚀 GlobalLine WhatsApp Worker Started")
    
    while True:
        try:
            # Process follow-ups
            process_follow_ups()
            
            # Check quote requests
            check_quote_requests()
            
        except Exception as e:
            print(f"Worker error: {e}")
        
        time.sleep(60)  # Check every minute

if __name__ == "__main__":
    worker_loop()