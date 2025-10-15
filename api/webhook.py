import os
import json
import base64
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify

# Initialize Flask app
app = Flask(__name__)

# Get environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
FIREBASE_CREDENTIALS_B64 = os.environ.get("FIREBASE_CREDENTIALS")

@app.route('/api/webhook', methods=['POST', 'GET'])
def webhook():
    try:
        # Test endpoint
        if request.method == 'GET':
            return jsonify({
                "status": "Bot is running!", 
                "bot_token_set": bool(TELEGRAM_BOT_TOKEN),
                "firebase_set": bool(FIREBASE_CREDENTIALS_B64)
            })
        
        # Handle Telegram webhook
        data = request.get_json()
        if not data:
            return jsonify({"ok": False, "error": "No data"})
        
        # Simple echo for testing
        if 'message' in data and 'text' in data['message']:
            text = data['message']['text']
            chat_id = data['message']['chat']['id']
            
            # Echo the message back
            send_telegram_message(chat_id, f"You said: {text}")
        
        return jsonify({"ok": True})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

def send_telegram_message(chat_id, text):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except Exception as e:
        print(f"Telegram API error: {e}")

# Initialize Firebase only if credentials exist
if FIREBASE_CREDENTIALS_B64 and not firebase_admin._apps:
    try:
        creds_json = json.loads(base64.b64decode(FIREBASE_CREDENTIALS_B64))
        cred = credentials.Certificate(creds_json)
        firebase_admin.initialize_app(cred)
        print("Firebase initialized successfully")
    except Exception as e:
        print(f"Firebase init error: {e}")

if __name__ == '__main__':
    app.run(debug=True)
