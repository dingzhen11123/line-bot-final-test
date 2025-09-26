import os
import requests
import logging
from flask import Flask, request, abort

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

# --- 从 Vercel 的环境变量中安全地获取密钥 ---
YOUR_CHANNEL_SECRET = os.environ.get('YOUR_CHANNEL_SECRET')
YOUR_CHANNEL_ACCESS_TOKEN = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')
YOUR_LLM_API_KEY = os.environ.get('YOUR_LLM_API_KEY')
YOUR_LLM_API_URL = os.environ.get('YOUR_LLM_API_URL')

# 检查环境变量
if not all([YOUR_CHANNEL_SECRET, YOUR_CHANNEL_ACCESS_TOKEN, YOUR_LLM_API_KEY, YOUR_LLM_API_URL]):
    logging.error("启动失败：一个或多个环境变量缺失。请检查 Vercel 项目的环境变量设置。")
    # 在 Vercel 中，我们不应该抛出异常阻止启动
    
# 初始化 LINE Bot 组件
try:
    handler = WebhookHandler(YOUR_CHANNEL_SECRET or "dummy_secret_for_startup")
    configuration = Configuration(access_token=YOUR_CHANNEL_ACCESS_TOKEN or "dummy_token_for_startup")
except Exception as e:
    logging.error(f"Failed to initialize LINE Bot components: {e}")
    handler = None
    configuration = None

def call_your_llm_api_for_translation(text, target_lang):
    """调用 LLM API 进行翻译"""
    if not all([YOUR_LLM_API_KEY, YOUR_LLM_API_URL]):
        return "翻译服务因配置错误而无法使用。"
    
    source_lang_name = "泰语" if target_lang == "zh" else "中文"
    target_lang_name = "中文" if target_lang == "zh" else "泰语"
    
    prompt = f"你是一个专业的翻译，尤其擅长{source_lang_name}和{target_lang_name}之间的生活化翻译。请把以下文本翻译成地道的{target_lang_name}，不要直译，要自然流畅。文本：```{text}```"
    
    headers = {
        "Authorization": f"Bearer {YOUR_LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5
    }
    
    try:
        logging.info(f"Sending request to {YOUR_LLM_API_URL}")
        response = requests.post(YOUR_LLM_API_URL, headers=headers, json=payload, timeout=25)
        response.raise_for_status()
        response_json = response.json()
        translated_text = response_json.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        logging.info("Translation successful.")
        return translated_text
    except Exception as e:
        logging.error(f"API call failed: {e}")
        return "翻译服务暂时出了一点问题。"

@app.route("/", methods=['GET'])
def home():
    """根路径处理"""
    return "LINE Translation Bot is running!"

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Bot webhook 回调处理"""
    if not handler:
        logging.error("Webhook handler not initialized due to missing secret.")
        abort(500)
    
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        logging.error("Missing X-Line-Signature header")
        abort(400)
    
    body = request.get_data(as_text=True)
    logging.info("Request body: " + body)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("Invalid signature")
        abort(400)
    except Exception as e:
        logging.error(f"Error handling request: {e}")
        abort(500)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """处理文本消息"""
    if not configuration:
        logging.error("Configuration not available")
        return
    
    original_text = event.message.text
    
    # 如果消息已经以表情符号开头，说明是翻译结果，不再处理
    if original_text.startswith("🇹🇭") or original_text.startswith("🇨🇳"):
        return
    
    # 检测是否为泰语
    is_thai = any('\u0e00' <= char <= '\u0e7f' for char in original_text)
    target_lang = "zh" if is_thai else "th"
    
    # 调用翻译 API
    translated_text = call_your_llm_api_for_translation(original_text, target_lang)
    
    if translated_text:
        # 根据翻译方向添加对应的表情符号
        reply_text = f"🇨🇳 {translated_text}" if is_thai else f"🇹🇭 {translated_text}"
        
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )
            logging.info("Message replied successfully")
        except Exception as e:
            logging.error(f"Error replying to LINE: {e}")

# Vercel serverless function handler
def handler_func(request):
    """Vercel serverless function handler"""
    return app(request.environ, request.start_response)

# 如果直接运行这个文件（本地测试）
if __name__ == "__main__":
    app.run(debug=True, port=5000)
