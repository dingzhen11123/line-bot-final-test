import os
import json
import requests
import logging
from urllib.parse import parse_qs

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 环境变量
CHANNEL_SECRET = os.environ.get('YOUR_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')
LLM_API_KEY = os.environ.get('YOUR_LLM_API_KEY')
LLM_API_URL = os.environ.get('YOUR_LLM_API_URL')

def verify_signature(body, signature):
    """验证 LINE 签名"""
    import hmac
    import hashlib
    import base64
    
    if not CHANNEL_SECRET:
        return False
        
    hash_digest = hmac.new(
        CHANNEL_SECRET.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    expected_signature = base64.b64encode(hash_digest).decode('utf-8')
    return hmac.compare_digest(signature, expected_signature)

def call_translation_api(text, target_lang):
    """调用翻译 API"""
    if not LLM_API_KEY or not LLM_API_URL:
        return "翻译服务配置错误"
    
    source_lang_name = "泰语" if target_lang == "zh" else "中文"
    target_lang_name = "中文" if target_lang == "zh" else "泰语"
    
    prompt = f"你是一个专业的翻译，尤其擅长{source_lang_name}和{target_lang_name}之间的生活化翻译。请把以下文本翻译成地道的{target_lang_name}，不要直译，要自然流畅。文本：```{text}```"
    
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5
    }
    
    try:
        logger.info("Calling translation API")
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=25)
        response.raise_for_status()
        
        response_data = response.json()
        translated_text = response_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        
        if translated_text:
            logger.info("Translation successful")
            return translated_text
        else:
            return "翻译结果为空"
            
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return "翻译失败"

def send_reply_message(reply_token, message_text):
    """发送回复消息"""
    if not CHANNEL_ACCESS_TOKEN:
        logger.error("Missing access token")
        return False
    
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
    }
    
    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": message_text
            }
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Reply sent successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to send reply: {e}")
        return False

def handle_webhook_event(event):
    """处理 webhook 事件"""
    if event.get("type") != "message":
        return
    
    message = event.get("message", {})
    if message.get("type") != "text":
        return
    
    original_text = message.get("text", "").strip()
    reply_token = event.get("replyToken")
    
    if not original_text or not reply_token:
        return
    
    logger.info(f"Processing message: {original_text}")
    
    # 忽略已翻译的消息
    if original_text.startswith("🇹🇭") or original_text.startswith("🇨🇳"):
        logger.info("Ignoring translated message")
        return
    
    # 检测语言
    is_thai = any('\u0e00' <= char <= '\u0e7f' for char in original_text)
    target_lang = "zh" if is_thai else "th"
    
    logger.info(f"Language detected: {'Thai' if is_thai else 'Chinese'}")
    
    # 翻译
    translated_text = call_translation_api(original_text, target_lang)
    
    # 回复
    reply_text = f"🇨🇳 {translated_text}" if is_thai else f"🇹🇭 {translated_text}"
    send_reply_message(reply_token, reply_text)

def handler(request):
    """Vercel serverless function handler"""
    try:
        # 获取请求方法
        method = request.get('httpMethod', request.get('method', 'GET')).upper()
        path = request.get('path', '/')
        
        # 处理 GET 请求 (健康检查)
        if method == 'GET':
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'status': 'ok',
                    'message': 'LINE Translation Bot is running',
                    'path': path,
                    'config_status': {
                        'channel_secret': bool(CHANNEL_SECRET),
                        'channel_token': bool(CHANNEL_ACCESS_TOKEN),
                        'llm_api_key': bool(LLM_API_KEY),
                        'llm_api_url': bool(LLM_API_URL)
                    }
                })
            }
        
        # 处理 POST 请求 (webhook)
        if method == 'POST' and (path == '/callback' or path == '/'):
            # 获取请求体
            body = request.get('body', '')
            if request.get('isBase64Encoded'):
                import base64
                body = base64.b64decode(body).decode('utf-8')
            
            # 获取签名
            headers = request.get('headers', {})
            signature = headers.get('x-line-signature') or headers.get('X-Line-Signature')
            
            if not signature:
                logger.error("Missing signature")
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'Missing signature'})
                }
            
            # 验证签名
            if not verify_signature(body, signature):
                logger.error("Invalid signature")
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'Invalid signature'})
                }
            
            # 解析 webhook 数据
            try:
                webhook_data = json.loads(body)
                events = webhook_data.get('events', [])
                
                for event in events:
                    handle_webhook_event(event)
                
                return {
                    'statusCode': 200,
                    'body': 'OK'
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'Invalid JSON'})
                }
        
        # 其他请求
        return {
            'statusCode': 404,
            'body': json.dumps({'error': 'Not Found'})
        }
        
    except Exception as e:
        logger.error(f"Handler error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal Server Error'})
        }

# Vercel 导出
def main(request):
    return handler(request)
