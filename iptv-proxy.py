#!/usr/bin/env python3
"""
IPTV 本地代理服务器 v2（多线程版）
解决 Chrome/Edge 浏览器 HTTPS 页面无法播放 HTTP 频道的问题

使用方法:
  python iptv-proxy.py          # 默认监听 18888 端口
  python iptv-proxy.py 28888    # 自定义端口
"""
import http.server
import socketserver
import urllib.request
import urllib.error
import urllib.parse
import sys
import ssl
import socket
import time
import threading

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18888
PROXY_PREFIX = '/proxy/'
TIMEOUT = 20

# 自定义 SSL context（忽略上游证书错误）
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# 连接池：复用 TCP 连接提升速度
import http.client

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {threading.current_thread().name} {args[0]}\n")
        sys.stderr.flush()

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/' or self.path == '/status':
            self._send_json({"status": "ok", "proxy": f"http://localhost:{LISTEN_PORT}", "threads": threading.active_count()})
            return

        if self.path.startswith(PROXY_PREFIX):
            self._handle_proxy()
            return

        self.send_error(404)

    def _handle_proxy(self):
        encoded_url = self.path[len(PROXY_PREFIX):]
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

        self.log_message("-> %s", target_url[:100])

        try:
            req = urllib.request.Request(target_url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            # 添加合理的 Referer
            parsed = urllib.parse.urlparse(target_url)
            req.add_header('Referer', f'{parsed.scheme}://{parsed.netloc}/')
            req.add_header('Origin', f'{parsed.scheme}://{parsed.netloc}')

            resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_ctx)
            data = resp.read()

            content_type = resp.headers.get('Content-Type', 'application/octet-stream')
            if target_url.endswith('.m3u8') or 'mpegurl' in content_type.lower():
                content_type = 'application/vnd.apple.mpegurl'

            self.send_response(200)
            self._cors_headers()
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(data))
            if target_url.endswith('.m3u8'):
                self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)
            self.log_message("<- 200 %d bytes", len(data))

        except urllib.error.HTTPError as e:
            self.log_message("<- HTTP %d: %s", e.code, target_url[:80])
            self.send_error(e.code, f"Upstream error: {e.code}")
        except urllib.error.URLError as e:
            self.log_message("<- URL Error: %s", str(e.reason)[:50])
            self.send_error(502, f"Connection failed: {e.reason}")
        except socket.timeout:
            self.log_message("<- Timeout: %s", target_url[:80])
            self.send_error(504, "Upstream timeout")
        except (ConnectionAbortedError, BrokenPipeError, OSError) as e:
            self.log_message("<- ConnReset: %s", str(e)[:50])
        except Exception as e:
            self.log_message("<- Error: %s", str(e)[:80])
            try:
                self.send_error(500, str(e)[:200])
            except:
                pass

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


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    server = ThreadedHTTPServer(('127.0.0.1', LISTEN_PORT), ProxyHandler)
    print(f"""
╔══════════════════════════════════════════════╗
║  📺 IPTV 本地代理 v2（多线程版）已启动       ║
║                                              ║
║  地址: http://127.0.0.1:{LISTEN_PORT:<5}              ║
║  状态: http://127.0.0.1:{LISTEN_PORT}/status         ║
║                                              ║
║  打开电视墙 → 点「🛡️ 代理」→ 选本地代理      ║
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
