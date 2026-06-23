#!/usr/bin/env python3
"""
IPTV 本地代理服务器
解决 Chrome/Edge 浏览器 HTTPS 页面无法播放 HTTP 频道的问题

使用方法:
  python iptv-proxy.py          # 默认监听 18888 端口
  python iptv-proxy.py 28888    # 自定义端口

启动后打开电视墙页面，点击「🛡️ 代理」开启即可
"""
import http.server
import urllib.request
import urllib.error
import sys
import os
import ssl
import socket
import threading
import time

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18888
PROXY_PREFIX = '/proxy/'
TIMEOUT = 15

# 自定义 SSL context（忽略上游证书错误）
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 简化日志
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {args[0]}\n")
        sys.stderr.flush()

    def do_OPTIONS(self):
        """处理 CORS preflight"""
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/' or self.path == '/status':
            self._send_json({"status": "ok", "proxy": f"http://localhost:{LISTEN_PORT}"})
            return

        if self.path.startswith(PROXY_PREFIX):
            self._handle_proxy()
            return

        self.send_error(404)

    def _handle_proxy(self):
        # 从路径中提取目标 URL
        encoded_url = self.path[len(PROXY_PREFIX):]
        # 支持 ?url=... 和直接路径两种格式
        if encoded_url.startswith('?url='):
            encoded_url = encoded_url[5:]
        
        try:
            target_url = urllib.parse.unquote(encoded_url)
        except Exception:
            self.send_error(400, "Invalid URL")
            return

        if not target_url.startswith(('http://', 'https://')):
            self.send_error(400, "Only HTTP/HTTPS URLs allowed")
            return

        self.log_message("PROXY -> %s", target_url[:100])

        try:
            req = urllib.request.Request(target_url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            req.add_header('Referer', target_url.split('/live/')[0] + '/' if '/live/' in target_url else target_url.rsplit('/', 1)[0] + '/')
            req.add_header('Origin', target_url.split('://')[0] + '://' + target_url.split('://')[1].split('/')[0])

            resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_ctx)
            data = resp.read()

            # 根据内容类型设置
            content_type = resp.headers.get('Content-Type', 'application/octet-stream')
            # 如果是 m3u8，修改 Content-Type
            if target_url.endswith('.m3u8') or 'mpegurl' in content_type.lower():
                content_type = 'application/vnd.apple.mpegurl'

            self.send_response(200)
            self._cors_headers()
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(data))
            # 允许缓存 m3u8 manifest
            if target_url.endswith('.m3u8'):
                self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)

        except urllib.error.HTTPError as e:
            self.log_message("HTTP %d: %s", e.code, target_url[:80])
            self.send_error(e.code, f"Upstream error: {e.code}")
        except urllib.error.URLError as e:
            self.log_message("URL Error: %s -> %s", str(e.reason)[:50], target_url[:80])
            self.send_error(502, f"Connection failed: {e.reason}")
        except socket.timeout:
            self.log_message("Timeout: %s", target_url[:80])
            self.send_error(504, "Upstream timeout")
        except Exception as e:
            self.log_message("Error: %s", str(e)[:80])
            self.send_error(500, str(e)[:200])

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')

    def _send_json(self, obj):
        import json
        data = json.dumps(obj).encode()
        self.send_response(200)
        self._cors_headers()
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)


def main():
    server = http.server.HTTPServer(('127.0.0.1', LISTEN_PORT), ProxyHandler)
    print(f"""
╔══════════════════════════════════════════════╗
║  📺 IPTV 本地代理已启动                       ║
║                                              ║
║  地址: http://127.0.0.1:{LISTEN_PORT:<5}              ║
║  状态: http://127.0.0.1:{LISTEN_PORT}/status         ║
║                                              ║
║  使用方法:                                    ║
║  1. 打开电视墙页面                             ║
║  2. 点击工具栏「🛡️ 代理」按钮                 ║
║  3. 如提示输入代理地址，填入上面的地址           ║
║                                              ║
║  按 Ctrl+C 停止                               ║
╚══════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 代理已停止")
        server.server_close()

if __name__ == "__main__":
    main()
