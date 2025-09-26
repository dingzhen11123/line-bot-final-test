from http.server import BaseHTTPRequestHandler
import os
import json
import requests
import logging
import hmac
import hashlib
import base64
from urllib.parse import urlparse

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """处理GET请求 - 健康检查"""
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # 获取环境变量状态
            config_status = {
                'channel_secret': bool(os.environ.get('YOUR_CHANNEL_SECRET')),
                'channel_token': bool(os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')),
                'llm_api_key': bool(os.environ.get('YOUR_LLM_API_KEY')),
                'llm_api_url': bool(os.environ.get('YOUR_LLM_API_URL'))
            }
            
            response_data = {
                'status': 'success',
                'message': 'LINE翻译机器人正在运行',
                'timestamp': str(__import__('datetime').datetime.now()),
                'path': self.path,
                'config': config_status,
                'version': '1.0.0'
            }
            
            response_json = json.dumps(response_data, ensure_ascii=False, indent=2)
            self.wfile.write(response_json.encode('utf-8'))
            
        except Exception as e:
            logger.error(f"GET请求错误: {e}")
            self.send_error(500)

    def do_POST(self):
        """处理POST请求 - LINE Webhook"""
        try:
            # 获取环境变量
            channel_secret = os.environ.get('YOUR_CHANNEL_SECRET')
            channel_token = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')
            llm_api_key = os.environ.get('YOUR_LLM_API_KEY')
            llm_api_url = os.environ.get('YOUR_LLM_API_URL')
            
            if not all([channel_secret, channel_token, llm_api_key, llm_api_url]):
                logger.error("环境变量缺失")
                self.send_error(500, "服务配置错误")
                return
            
            # 获取请求头
            signature = self.headers.get('X-Line-Signature') or self.headers.get('x-line-signature')
            
            if not signature:
                logger.error("缺少签名头")
                self.send_error(400, "缺少签名")
                return
            
            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                logger.error("请求体为空")
                self.send_error(400, "请求体为空")
                return
                
            post_data = self.rfile.read(content_length)
            body = post_data.decode('utf-8')
            
            # 验证签名
            if not self._verify_signature(body, signature, channel_secret):
                logger.error("签名验证失败")
                self.send_error(403, "签名验证失败")
                return
            
            # 解析webhook数据
            try:
                webhook_data = json.loads(body)
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {e}")
                self.send_error(400, "无效的JSON数据")
                return
            
            # 处理事件
            events = webhook_data.get('events', [])
            for event in events:
                if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
                    self._handle_text_message(event, channel_token, llm_api_key, llm_api_url)
            
            # 发送成功响应
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
            
        except Exception as e:
            logger.error(f"POST请求处理错误: {e}")
            self.send_error(500, "内部服务器错误")
    
    def _verify_signature(self, body, signature, secret):
        """验证LINE签名"""
        try:
            hash_digest = hmac.new(
                secret.encode('utf-8'),
                body.encode('utf-8'),
                hashlib.sha256
            ).digest()
            expected_signature = base64.b64encode(hash_digest).decode('utf-8')
            return hmac.compare_digest(signature, expected_signature)
        except Exception as e:
            logger.error(f"签名验证异常: {e}")
            return False
    
    def _handle_text_message(self, event, channel_token, llm_api_key, llm_api_url):
        """处理文本消息"""
        try:
            message_text = event.get('message', {}).get('text', '').strip()
            reply_token = event.get('replyToken')
            
            if not message_text or not reply_token:
                return
            
            logger.info(f"收到消息: {message_text[:50]}...")
            
            # 跳过已翻译的消息
            if message_text.startswith('🇹🇭') or message_text.startswith('🇨🇳'):
                logger.info("跳过已翻译消息")
                return
            
            # 语言检测
            is_thai = any('\u0e00' <= char <= '\u0e7f' for char in message_text)
            target_lang = "zh" if is_thai else "th"
            
            logger.info(f"检测到语言: {'泰语' if is_thai else '中文'} -> {'中文' if is_thai else '泰语'}")
            
            # 翻译
            translated_text = self._call_translation_api(message_text, target_lang, llm_api_key, llm_api_url)
            
            if translated_text:
                # 添加语言标识
                reply_text = f"🇨🇳 {translated_text}" if is_thai else f"🇹🇭 {translated_text}"
                
                # 发送回复
                self._send_line_reply(reply_token, reply_text, channel_token)
            
        except Exception as e:
            logger.error(f"处理文本消息错误: {e}")
    
    def _call_translation_api(self, text, target_lang, api_key, api_url):
        """调用翻译API"""
        try:
            source_lang_name = "泰语" if target_lang == "zh" else "中文"
            target_lang_name = "中文" if target_lang == "zh" else "泰语"
            
            prompt = f"你是专业翻译，擅长{source_lang_name}和{target_lang_name}互译。请将以下文本翻译成自然流畅的{target_lang_name}，保持原意但符合目标语言习惯：\n\n{text}"
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 1000
            }
            
            logger.info("调用翻译API...")
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            translated = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            if translated:
                logger.info("翻译成功")
                return translated
            else:
                logger.warning("翻译结果为空")
                return "抱歉，翻译失败了"
                
        except requests.exceptions.Timeout:
            logger.error("翻译API超时")
            return "翻译服务超时，请稍后再试"
        except requests.exceptions.RequestException as e:
            logger.error(f"翻译API请求失败: {e}")
            return "翻译服务暂时不可用"
        except Exception as e:
            logger.error(f"翻译过程发生错误: {e}")
            return "翻译出现问题"
    
    def _send_line_reply(self, reply_token, message, access_token):
        """发送LINE回复消息"""
        try:
            url = "https://api.line.me/v2/bot/message/reply"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }
            
            payload = {
                "replyToken": reply_token,
                "messages": [
                    {
                        "type": "text",
                        "text": message
                    }
                ]
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info("LINE消息发送成功")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"发送LINE消息失败: {e}")
            return False
        except Exception as e:
            logger.error(f"发送LINE消息异常: {e}")
            return False
