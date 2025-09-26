import os
import json
import hmac
import hashlib
import base64
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# 环境变量
CHANNEL_SECRET = os.environ.get('YOUR_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')
LLM_API_KEY = os.environ.get('YOUR_LLM_API_KEY')
LLM_API_URL = os.environ.get('YOUR_LLM_API_URL')

def verify_signature(body, signature):
    if not CHANNEL_SECRET:
        return False
    hash_digest = hmac.new(
        CHANNEL_SECRET.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(hash_digest).decode('utf-8')
    return hmac.compare_digest(signature, expected_signature)

def translate_text(text, target_lang):
    if not LLM_API_KEY or not LLM_API_URL:
        return "翻译服务配置错误"
    
    source_lang = "泰语" if target_lang == "zh" else "中文"
    target_lang_name = "中文" if target_lang == "zh" else "泰语"
    
    prompt = f"请将以下{source_lang}翻译成自然流畅的{target_lang_name}：{text}"
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3
    }
    
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(LLM_API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    except:
        return "翻译失败，请稍后再试"

def send_reply(reply_token, message):
    if not CHANNEL_ACCESS_TOKEN:
        return False
    
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
    }
    
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message}]
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        return response.status_code == 200
    except:
        return False

@app.route('/')
def home():
    return jsonify({
        'status': 'ok',
        'message': 'LINE 翻译机器人运行中',
        'config': {
            'channel_secret': bool(CHANNEL_SECRET),
            'channel_token': bool(CHANNEL_ACCESS_TOKEN),
            'llm_api_key': bool(LLM_API_KEY),
            'llm_api_url': bool(LLM_API_URL)
        }
    })

@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        return 'Missing signature', 400
    
    body = request.get_data(as_text=True)
    if not verify_signature(body, signature):
        return 'Invalid signature', 403
    
    try:
        webhook_data = json.loads(body)
        for event in webhook_data.get('events', []):
            if (event.get('type') == 'message' and 
                event.get('message', {}).get('type') == 'text'):
                
                text = event.get('message', {}).get('text', '').strip()
                reply_token = event.get('replyToken')
                
                if not text or not reply_token:
                    continue
                
                # 跳过已翻译消息
                if text.startswith('🇹🇭') or text.startswith('🇨🇳'):
                    continue
                
                # 语言检测和翻译
                is_thai = any('\u0e00' <= char <= '\u0e7f' for char in text)
                target_lang = "zh" if is_thai else "th"
                
                translated = translate_text(text, target_lang)
                reply_text = f"🇨🇳 {translated}" if is_thai else f"🇹🇭 {translated}"
                
                send_reply(reply_token, reply_text)
        
        return 'OK'
    except:
        return 'Error processing webhook', 500

if __name__ == '__main__':
    app.run(debug=True)
