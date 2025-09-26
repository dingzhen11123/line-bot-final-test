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
    raise ValueError("一个或多个环境变量缺失，应用无法启动。")

handler = WebhookHandler(YOUR_CHANNEL_SECRET)
configuration = Configuration(access_token=YOUR_CHANNEL_ACCESS_TOKEN)

def call_your_llm_api_for_translation(text, target_lang):
    source_lang_name = "泰语" if target_lang == "zh" else "中文"
    target_lang_name = "中文" if target_lang == "zh" else "泰语"

    prompt = f"""
    你是一个专业的翻译，尤其擅长{source_lang_name}和{target_lang_name}之间的生活化和社交化翻译。
    你的任务是把以下用三个反引号包围的{source_lang_name}文本翻译成地道的、符合当地人说话习惯的{target_lang_name}。
    翻译要求：
    1. 不要直译，要意译，确保表达方式自然、流畅。
    2. 考虑文化和语境，准确传达信息。
    3. 直接输出翻译结果，不要添加任何额外的解释。
    需要翻译的文本：
    ```
    {text}
    ```
    """

    headers = {
        "Authorization": f"Bearer {YOUR_LLM_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
    }

    try:
        logging.info(f"正在向 {YOUR_LLM_API_URL} 发送翻译请求...")
        response = requests.post(YOUR_LLM_API_URL, headers=headers, json=payload, timeout=25)
        response.raise_for_status()

        response_json = response.json()
        translated_text = response_json.get("choices")[0].get("message").get("content").strip()
        logging.info("成功获取翻译结果。")
        return translated_text

    except Exception as e:
        logging.error(f"调用LLM API时出错: {e}")
        return "翻译服务暂时出了一点问题。"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    logging.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        logging.error(f"处理请求时出错: {e}")
        abort(500)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    original_text = event.message.text
    if original_text.startswith("🇹🇭") or original_text.startswith("🇨🇳"):
        return
    is_thai = any('\u0e00' <= char <= '\u0e7f' for char in original_text)
    target_lang = "zh" if is_thai else "th"
    translated_text = call_your_llm_api_for_translation(original_text, target_lang)
    if translated_text:
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
        except Exception as e:
            logging.error(f"回复LINE消息时出错: {e}")
