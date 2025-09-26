import os
import json
import hmac
import hashlib
import base64
import requests
import logging
from datetime import datetime
from flask import Flask, request, jsonify

# 设置详细日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 环境变量
CHANNEL_SECRET = os.environ.get('YOUR_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')
LLM_API_KEY = os.environ.get('YOUR_LLM_API_KEY')
LLM_API_URL = os.environ.get('YOUR_LLM_API_URL')

# 启动时记录配置状态
logger.info("=== LINE 翻译机器人启动 ===")
logger.info(f"CHANNEL_SECRET: {'已设置' if CHANNEL_SECRET else '未设置'}")
logger.info(f"CHANNEL_ACCESS_TOKEN: {'已设置' if CHANNEL_ACCESS_TOKEN else '未设置'}")
logger.info(f"LLM_API_KEY: {'已设置' if LLM_API_KEY else '未设置'}")
logger.info(f"LLM_API_URL: {LLM_API_URL if LLM_API_URL else '未设置'}")

def verify_signature(body, signature):
    """验证 LINE 签名"""
    logger.info(f"开始验证签名...")
    
    if not CHANNEL_SECRET:
        logger.error("CHANNEL_SECRET 未设置")
        return False
        
    if not signature:
        logger.error("签名为空")
        return False
    
    try:
        hash_digest = hmac.new(
            CHANNEL_SECRET.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256
        ).digest()
        expected_signature = base64.b64encode(hash_digest).decode('utf-8')
        result = hmac.compare_digest(signature, expected_signature)
        
        logger.info(f"签名验证: {'成功' if result else '失败'}")
        if not result:
            logger.error(f"期望签名: {expected_signature[:20]}...")
            logger.error(f"实际签名: {signature[:20]}...")
        
        return result
    except Exception as e:
        logger.error(f"签名验证异常: {e}")
        return False

def translate_text(text, target_lang):
    """翻译文本"""
    logger.info(f"开始翻译: '{text}' -> {target_lang}")
    
    if not LLM_API_KEY:
        logger.error("LLM_API_KEY 未设置")
        return "翻译服务：API Key未配置"
    
    if not LLM_API_URL:
        logger.error("LLM_API_URL 未设置")
        return "翻译服务：API URL未配置"
    
    source_lang = "泰语" if target_lang == "zh" else "中文"
    target_lang_name = "中文" if target_lang == "zh" else "泰语"
    
    # 修改后的 prompt：更严格，要求仅输出翻译
    prompt = f"请将以下{source_lang}翻译成自然流畅、当地人易懂、不会造成误解的{target_lang_name}。仅输出翻译结果，无任何解释、备注、音译或额外文字：\n{text}"
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,  # 保持低温度，确保一致性
        "max_tokens": 1000
    }
    
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        logger.info(f"调用翻译API: {LLM_API_URL}")
        response = requests.post(LLM_API_URL, json=payload, headers=headers, timeout=30)
        
        logger.info(f"翻译API响应状态: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"翻译API错误: {response.text}")
            return f"翻译服务错误 (状态码: {response.status_code})"
        
        result = response.json()
        translated = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        
        # 额外清理：移除任何可能的残留解释（万一有）
        if "：" in translated and translated.startswith(text):  # 简单过滤，如果开头是原文本+冒号
            translated = translated.split("：", 1)[1].strip() if "：" in translated else translated
        
        if translated:
            logger.info(f"翻译成功: '{translated}'")
            return translated
        else:
            logger.error("翻译结果为空")
            return "翻译失败：结果为空"
            
    except requests.exceptions.Timeout:
        logger.error("翻译API超时")
        return "翻译服务超时，请稍后再试"
    except requests.exceptions.RequestException as e:
        logger.error(f"翻译API请求失败: {e}")
        return "翻译服务暂时不可用"
    except Exception as e:
        logger.error(f"翻译过程异常: {e}")
        return "翻译失败，请稍后再试"

def send_reply(reply_token, message):
    """发送 LINE 回复"""
    logger.info(f"准备发送回复: '{message}'")
    
    if not CHANNEL_ACCESS_TOKEN:
        logger.error("CHANNEL_ACCESS_TOKEN 未设置")
        return False
    
    if not reply_token:
        logger.error("reply_token 为空")
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
        logger.info("发送 LINE 回复...")
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        
        logger.info(f"LINE API响应: {response.status_code}")
        
        if response.status_code == 200:
            logger.info("回复发送成功")
            return True
        else:
            logger.error(f"LINE API错误: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"发送回复失败: {e}")
        return False

@app.route('/')
def home():
    """首页 - 显示状态"""
    logger.info("收到首页访问")
    
    config_status = {
        'channel_secret': bool(CHANNEL_SECRET),
        'channel_token': bool(CHANNEL_ACCESS_TOKEN),
        'llm_api_key': bool(LLM_API_KEY),
        'llm_api_url': bool(LLM_API_URL)
    }
    
    response_data = {
        'status': 'ok',
        'message': 'LINE 翻译机器人运行中 🚀',
        'timestamp': datetime.now().isoformat(),
        'config': config_status,
        'webhook_url': 'https://line-bot-final-test.vercel.app/callback'
    }
    
    logger.info(f"返回状态: {config_status}")
    return jsonify(response_data)

@app.route('/test')
def test():
    """测试端点"""
    logger.info("收到测试请求")
    return jsonify({
        'message': '测试成功 ✅',
        'timestamp': datetime.now().isoformat(),
        'status': 'healthy'
    })

@app.route('/callback', methods=['POST'])
def callback():
    """LINE Webhook 回调"""
    logger.info("=" * 50)
    logger.info("收到 LINE Webhook 请求")
    logger.info("=" * 50)
    
    # 记录所有请求头
    logger.info("请求头信息:")
    for header, value in request.headers:
        logger.info(f"  {header}: {value}")
    
    # 获取签名
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        logger.error("缺少 X-Line-Signature 头")
        return jsonify({'error': 'Missing signature'}), 400
    
    # 获取请求体
    body = request.get_data(as_text=True)
    logger.info(f"请求体内容: {body}")
    
    # 验证签名
    if not verify_signature(body, signature):
        logger.error("签名验证失败")
        return jsonify({'error': 'Invalid signature'}), 403
    
    try:
        # 解析 JSON
        webhook_data = json.loads(body)
        events = webhook_data.get('events', [])
        
        logger.info(f"解析到 {len(events)} 个事件")
        
        # 处理每个事件
        for i, event in enumerate(events, 1):
            logger.info(f"--- 处理事件 {i} ---")
            logger.info(f"事件类型: {event.get('type')}")
            
            if event.get('type') == 'message':
                message = event.get('message', {})
                message_type = message.get('type')
                
                logger.info(f"消息类型: {message_type}")
                
                if message_type == 'text':
                    text = message.get('text', '').strip()
                    reply_token = event.get('replyToken')
                    
                    logger.info(f"收到文本: '{text}'")
                    logger.info(f"回复令牌: {reply_token}")
                    
                    if not text:
                        logger.warning("消息文本为空")
                        continue
                    
                    if not reply_token:
                        logger.warning("回复令牌为空")
                        continue
                    
                    # 跳过已翻译的消息
                    if text.startswith('🇹🇭') or text.startswith('🇨🇳'):
                        logger.info("跳过已翻译的消息")
                        continue
                    
                    # 语言检测
                    is_thai = any('\u0e00' <= char <= '\u0e7f' for char in text)
                    target_lang = "zh" if is_thai else "th"
                    
                    detected_lang = "泰语" if is_thai else "中文"
                    target_lang_name = "中文" if target_lang == "zh" else "泰语"
                    
                    logger.info(f"语言检测: {detected_lang} -> {target_lang_name}")
                    
                    # 翻译
                    translated = translate_text(text, target_lang)
                    
                    # 构建回复消息
                    if is_thai:
                        reply_text = f"🇨🇳 {translated}"
                    else:
                        reply_text = f"🇹🇭 {translated}"
                    
                    # 发送回复
                    success = send_reply(reply_token, reply_text)
                    logger.info(f"回复发送: {'成功' if success else '失败'}")
                    
                else:
                    logger.info(f"忽略非文本消息: {message_type}")
            else:
                logger.info(f"忽略非消息事件: {event.get('type')}")
        
        logger.info("=" * 50)
        logger.info("Webhook 处理完成")
        logger.info("=" * 50)
        
        return 'OK', 200
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析错误: {e}")
        return jsonify({'error': 'Invalid JSON'}), 400
    except Exception as e:
        logger.error(f"处理 Webhook 时发生异常: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(404)
def not_found(error):
    logger.warning(f"404 错误: {request.url}")
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 错误: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    logger.info("启动开发服务器")
    app.run(debug=True, host='0.0.0.0', port=5000)
