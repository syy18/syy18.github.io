#!/usr/bin/env python3
"""
IPTV 本地服务器 v5
共享基础URL字典，解决多线程相对路径问题
"""
import http.server
import socketserver
import urllib.request
import urllib.error
import urllib.parse
import os, sys, ssl, socket, time, threading

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18888
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_PREFIX = '/proxy/'
TIMEOUT = 20

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# 共享字典：key=客户端IP → value=最后的m3u8基础URL
base_url_map = {}
base_url_lock = threading.Lock()

class IPTVHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {args[0]}\n")
        sys.stderr.flush()

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/' or path == '/status':
            self._send_json({"status": "ok", "server": "iptv-v5"})
            return
        if path.startswith(PROXY_PREFIX):
            self._handle_proxy()
            return
        self._serve_static(path)

    def _serve_static(self, path):
        if path == '/': path = '/iptv.html'
        fp = os.path.normpath(os.path.join(REPO_DIR, path.lstrip('/')))
        if not fp.startswith(REPO_DIR): self.send_error(403); return
        if not os.path.isfile(fp): self.send_error(404); return
        ext = os.path.splitext(fp)[1].lower()
        mimes = {'.html':'text/html; charset=utf-8','.css':'text/css','.js':'application/javascript',
                 '.json':'application/json','.m3u':'application/x-mpegurl','.m3u8':'application/vnd.apple.mpegurl',
                 '.png':'image/png','.jpg':'image/jpeg','.svg':'image/svg+xml','.bat':'text/plain'}
        with open(fp,'rb') as f: data=f.read()
        self.send_response(200)
        self.send_header('Content-Type', mimes.get(ext,'application/octet-stream'))
        self.send_header('Content-Length',len(data))
        self.end_headers()
        self.wfile.write(data)

    def _handle_proxy(self):
        encoded = self.path[len(PROXY_PREFIX):]
        try: target = urllib.parse.unquote(encoded)
        except: self.send_error(400); return

        client_ip = self.client_address[0]

        if not target.startswith(('http://','https://')):
            # 相对路径 → 用客户端IP查基础URL
            with base_url_lock:
                base = base_url_map.get(client_ip)
            if base:
                target = base.rsplit('/',1)[0] + '/' + target
                self.log_message("REL[%s] -> %s", client_ip, target[:80])
            else:
                self.send_error(400, "No base URL"); return
        else:
            # 完整URL → 记录基础URL
            if '.m3u8' in target:
                with base_url_lock:
                    base_url_map[client_ip] = target
                self.log_message("BASE[%s] = %s", client_ip, target[:80])

        self.log_message("PROXY -> %s", target[:100])

        try:
            req = urllib.request.Request(target)
            req.add_header('User-Agent','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            p = urllib.parse.urlparse(target)
            req.add_header('Referer',f'{p.scheme}://{p.netloc}/')
            req.add_header('Origin',f'{p.scheme}://{p.netloc}')
            resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_ctx)
            data = resp.read()
            ct = resp.headers.get('Content-Type','application/octet-stream')
            if target.endswith('.m3u8') or 'mpegurl' in ct.lower():
                ct = 'application/vnd.apple.mpegurl'
            self.send_response(200)
            self._cors_headers()
            self.send_header('Content-Type',ct)
            self.send_header('Content-Length',len(data))
            self.end_headers()
            self.wfile.write(data)
            self.log_message("OK %d bytes", len(data))
        except urllib.error.HTTPError as e:
            self.log_message("ERR HTTP %d",e.code); self.send_error(e.code)
        except urllib.error.URLError as e:
            self.log_message("ERR URL %s",str(e.reason)[:40]); self.send_error(502)
        except socket.timeout:
            self.log_message("TIMEOUT"); self.send_error(504)
        except (ConnectionAbortedError,BrokenPipeError,OSError): pass
        except Exception as e:
            self.log_message("ERR %s",str(e)[:60])
            try: self.send_error(500)
            except: pass

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','*')

    def _send_json(self, obj):
        import json
        d=json.dumps(obj).encode()
        self.send_response(200); self._cors_headers()
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',len(d)); self.end_headers()
        self.wfile.write(d)

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def main():
    server = ThreadedHTTPServer(('127.0.0.1', LISTEN_PORT), IPTVHandler)
    print(f"📺 IPTV v5 running → http://127.0.0.1:{LISTEN_PORT}/iptv.html")
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()

if __name__ == "__main__":
    main()
