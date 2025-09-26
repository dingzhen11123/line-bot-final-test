import os
import sys
import requests
import logging
from flask import Flask, request, abort

# 添加当前目录到 Python 路径
sys.path.insert(0, os.path.dirname(__file__))

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

# 初始化 Flask 应用
app = Flask(__name__)

# 设置日志记录
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 从环境变量中获取配置 ---
CHANNEL_SECRET = os.environ.get('YOUR_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')
LLM_API_KEY = os.environ.get('YOUR_LLM_API_KEY')
LLM_API_URL = os.environ.get('YOUR_LLM_API_URL')

# 全局变量用于存储初始化后的对象
handler = None
configuration = None

def initialize_line_bot():
    """初始化 LINE Bot 组件"""
    global handler, configuration
    
    if not CHANNEL_SECRET:
        logger.error("Missing CHANNEL_SECRET")
        return False
        
    if not CHANNEL_ACCESS_TOKEN:
        logger.error("Missing CHANNEL_ACCESS_TOKEN")
        return False
    
    try:
        handler = WebhookHandler(CHANNEL_SECRET)
        configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
        logger.info("LINE Bot components initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize LINE Bot components: {e}")
        return False

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
        logger.info(f"Calling translation API: {LLM_API_URL}")
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=25)
        response.raise_for_status()
        
        response_data = response.json()
        translated_text = response_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        
        if translated_text:
            logger.info("Translation successful")
            return translated_text
        else:
            logger.warning("Empty translation result")
            return "翻译结果为空"
            
    except requests.exceptions.Timeout:
        logger.error("Translation API timeout")
        return "翻译服务超时"
    except requests.exceptions.RequestException as e:
        logger.error(f"Translation API request failed: {e}")
        return "翻译服务暂时不可用"
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return "翻译失败"

@app.route("/", methods=['GET'])
def home():
    """健康检查端点"""
    return {
        "status": "ok",
        "message": "LINE Translation Bot is running",
        "config_status": {
            "channel_secret": bool(CHANNEL_SECRET),
            "channel_token": bool(CHANNEL_ACCESS_TOKEN),
            "llm_api_key": bool(LLM_API_KEY),
            "llm_api_url": bool(LLM_API_URL)
        }
    }

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 回调"""
    global handler
    
    # 延迟初始化
    if handler is None:
        if not initialize_line_bot():
            logger.error("Failed to initialize LINE Bot")
            abort(500)
    
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        logger.error("Missing signature")
        abort(400)
    
    body = request.get_data(as_text=True)
    logger.info(f"Received webhook: {body[:100]}...")
    
    try:
        handler.handle(body, signature)
        return 'OK'
    except InvalidSignatureError:
        logger.error("Invalid signature")
        abort(400)
    except Exception as e:
        logger.error(f"Webhook handling error: {e}")
        abort(500)

@app.route("/test", methods=['GET'])
def test():
    """测试端点"""
    return {"message": "Test endpoint working"}

# 注册消息事件处理器
def register_handlers():
    """注册事件处理器"""
    global handler
    
    if handler is None:
        return
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """处理文本消息"""
        try:
            original_text = event.message.text.strip()
            logger.info(f"Received message: {original_text}")
            
            # 忽略已翻译的消息
            if original_text.startswith("🇹🇭") or original_text.startswith("🇨🇳"):
                logger.info("Ignoring translated message")
                return
            
            # 检测语言
            is_thai = any('\u0e00' <= char <= '\u0e7f' for char in original_text)
            target_lang = "zh" if is_thai else "th"
            
            logger.info(f"Detected language: {'Thai' if is_thai else 'Chinese'}, target: {target_lang}")
            
            # 翻译
            translated_text = call_translation_api(original_text, target_lang)
            
            # 回复
            reply_text = f"🇨🇳 {translated_text}" if is_thai else f"🇹🇭 {translated_text}"
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )
            
            logger.info("Reply sent successfully")
            
        except Exception as e:
            logger.error(f"Message handling error: {e}")

# 注册处理器
register_handlers()

# Vercel serverless function
def handler_func(environ, start_response):
    """WSGI handler for Vercel"""
    return app(environ, start_response)

# 对于 Vercel，导出 app
app = app
