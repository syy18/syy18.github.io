#!/usr/bin/env python3
"""
IPTV 本地服务器 v3
同时托管电视墙页面 + IPTV流代理

使用方法:
  python iptv-proxy.py          # 默认监听 18888 端口
  python iptv-proxy.py 28888    # 自定义端口

启动后打开: http://127.0.0.1:18888/iptv.html
"""
import http.server
import socketserver
import urllib.request
import urllib.error
import urllib.parse
import os
import sys
import ssl
import socket
import time
import threading

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18888
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_PREFIX = '/proxy/'
TIMEOUT = 20

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

class IPTVHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {threading.current_thread().name} {args[0]}\n")
        sys.stderr.flush()

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]

        # 状态接口
        if path == '/' or path == '/status':
            self._send_json({"status": "ok", "server": "iptv-v3", "port": LISTEN_PORT})
            return

        # IPTV 流代理
        if path.startswith(PROXY_PREFIX):
            self._handle_proxy()
            return

        # 静态文件服务（托管仓库里的文件）
        self._serve_static(path)

    def _serve_static(self, path):
        """从仓库目录提供静态文件"""
        if path == '/':
            path = '/iptv.html'

        # 安全检查：防止目录遍历
        file_path = os.path.normpath(os.path.join(REPO_DIR, path.lstrip('/')))
        if not file_path.startswith(REPO_DIR):
            self.send_error(403)
            return

        if not os.path.isfile(file_path):
            self.send_error(404)
            return

        # MIME 类型
        ext = os.path.splitext(file_path)[1].lower()
        mime_types = {
            '.html': 'text/html; charset=utf-8',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.json': 'application/json',
            '.m3u': 'application/x-mpegurl',
            '.m3u8': 'application/vnd.apple.mpegurl',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon',
        }
        content_type = mime_types.get(ext, 'application/octet-stream')

        with open(file_path, 'rb') as f:
            data = f.read()

        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)
        self.log_message("STATIC 200 %s (%d bytes)", path, len(data))

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

        self.log_message("PROXY -> %s", target_url[:100])

        try:
            req = urllib.request.Request(target_url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
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
            self.log_message("PROXY <- 200 %d bytes", len(data))

        except urllib.error.HTTPError as e:
            self.log_message("PROXY <- HTTP %d", e.code)
            self.send_error(e.code, f"Upstream: {e.code}")
        except urllib.error.URLError as e:
            self.log_message("PROXY <- Error: %s", str(e.reason)[:50])
            self.send_error(502, f"Conn fail: {e.reason}")
        except socket.timeout:
            self.log_message("PROXY <- Timeout")
            self.send_error(504, "Timeout")
        except (ConnectionAbortedError, BrokenPipeError, OSError):
            pass
        except Exception as e:
            self.log_message("PROXY <- Err: %s", str(e)[:80])
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
    server = ThreadedHTTPServer(('127.0.0.1', LISTEN_PORT), IPTVHandler)
    print(f"""
╔══════════════════════════════════════════════════════╗
║  📺 IPTV 本地服务器 v3                               ║
║                                                      ║
║  电视墙: http://127.0.0.1:{LISTEN_PORT}/iptv.html             ║
║  状态:   http://127.0.0.1:{LISTEN_PORT}/status                ║
║                                                      ║
║  ✅ 直接打开上面的电视墙链接即可观看所有频道          ║
║  ✅ 无需代理开关，页面本身已是 HTTP                    ║
║  ✅ 所有流直连，无中转延迟                             ║
║                                                      ║
║  按 Ctrl+C 停止                                       ║
╚══════════════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")
        server.server_close()

if __name__ == "__main__":
    main()
