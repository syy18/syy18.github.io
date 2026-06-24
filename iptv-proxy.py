#!/usr/bin/env python3
"""IPTV 本地服务器 v12 - 性能优化版"""
import http.server, socketserver, urllib.parse
import os, sys, ssl, socket, time, threading, json
from http.client import HTTPConnection, HTTPSConnection

PORT = int(sys.argv[1]) if len(sys.argv)>1 else 18888
HOST = sys.argv[2] if len(sys.argv)>2 else '0.0.0.0'
REPO = os.path.dirname(os.path.abspath(__file__))
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

_lock = threading.Lock()
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137.0.0.0 Safari/537.36'

# 连接池: {(scheme,host,port): HTTPConnection}
_conn_pool = {}
_pool_lock = threading.Lock()

def _get_conn(target):
    """获取/复用上游HTTP连接"""
    p = urllib.parse.urlparse(target)
    key = (p.scheme, p.netloc)
    with _pool_lock:
        conn = _conn_pool.get(key)
        if conn:
            try:
                conn.request('HEAD' if False else 'GET', '', body=None)
                # 简单检测连接是否存活
                del _conn_pool[key]
                conn.close()
            except:
                try: del _conn_pool[key]
                except: pass
                conn = None
    if p.scheme == 'https':
        c = HTTPSConnection(p.netloc, timeout=10, context=ssl_ctx)
    else:
        c = HTTPConnection(p.netloc, timeout=10)
    return c, p

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {args[0]}\n")
        sys.stderr.flush()

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_HEAD(self):
        p = self.path.split('?')[0]
        if p.startswith('/proxy/'):
            self._proxy(head_only=True)
        else:
            self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        p = self.path.split('?')[0]
        if p=='/' or p=='/status': self._json({"ok":True,"v":12}); return
        if p.startswith('/proxy/'): self._proxy(); return
        self._static(p)

    def _static(self, path):
        if path=='/': path='/iptv.html'
        fp=os.path.normpath(os.path.join(REPO,path.lstrip('/')))
        if not fp.startswith(REPO): self.send_error(403); return
        if not os.path.isfile(fp): self.send_error(404); return
        ext=os.path.splitext(fp)[1].lower()
        m={'.html':'text/html; charset=utf-8','.css':'text/css','.js':'application/javascript',
           '.json':'application/json','.m3u':'application/x-mpegurl','.m3u8':'application/vnd.apple.mpegurl',
           '.bat':'text/plain'}
        with open(fp,'rb') as f: d=f.read()
        self.send_response(200); self.send_header('Content-Type',m.get(ext,'application/octet-stream'))
        self.send_header('Content-Length',len(d)); self.end_headers(); self.wfile.write(d)

    def _proxy(self, head_only=False):
        enc=self.path[7:]
        try: target=urllib.parse.unquote(enc)
        except: self.send_error(400); return

        # 相对路径解析
        if not target.startswith(('http://','https://')):
            with _lock:
                base=_last_base.get('url')
            if base:
                target=base.rsplit('/',1)[0]+'/'+target
            else:
                self.send_error(400,"No base"); return
        elif '.m3u8' in target.lower():
            with _lock:
                _last_base['url'] = target

        is_m3u8 = '.m3u8' in target.lower()
        p = urllib.parse.urlparse(target)

        try:
            # 使用 http.client 直接连接（比 urllib 快）
            if p.scheme == 'https':
                conn = HTTPSConnection(p.netloc, timeout=10, context=ssl_ctx)
            else:
                conn = HTTPConnection(p.netloc, timeout=10)

            path_query = p.path
            if p.query: path_query += '?' + p.query
            headers = {
                'User-Agent': UA,
                'Referer': f'{p.scheme}://{p.netloc}/',
                'Host': p.netloc,
            }
            method = 'HEAD' if head_only else 'GET'
            conn.request(method, path_query, headers=headers)
            r = conn.getresponse()

            ct = r.getheader('Content-Type', 'application/octet-stream')
            if is_m3u8 or 'mpegurl' in ct.lower():
                ct = 'application/vnd.apple.mpegurl'

            if head_only:
                self.send_response(200); self._cors()
                self.send_header('Content-Type', ct)
                self.end_headers()
                r.read()
                conn.close()
                return

            # m3u8: 直接透传（不重写，让浏览器自动解析相对路径）
            if is_m3u8:
                data = r.read()
                conn.close()
                self.send_response(200); self._cors()
                self.send_header('Content-Type', ct)
                self.send_header('Content-Length', len(data))
                self.end_headers()
                self.wfile.write(data)
                self.log_message("M3U8 %d bytes %s", len(data), target[:70])
            else:
                # .ts等: 流式传输，大缓冲区
                cl = r.getheader('Content-Length')
                self.send_response(200); self._cors()
                self.send_header('Content-Type', ct)
                if cl:
                    self.send_header('Content-Length', cl)
                self.end_headers()
                total = 0
                while True:
                    chunk = r.read(262144)  # 256KB 缓冲区
                    if not chunk: break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        total += len(chunk)
                    except (BrokenPipeError, OSError):
                        break
                conn.close()
                self.log_message("OK %d %s", total, target[:70])

        except Exception as e:
            try: self.send_error(502)
            except: pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,HEAD,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','*')

    def _json(self, o):
        d=json.dumps(o).encode()
        self.send_response(200); self._cors()
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',len(d)); self.end_headers(); self.wfile.write(d)

_last_base = {'url': None}

class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads=True; allow_reuse_address=True

if __name__=="__main__":
    import socket as _sock
    srv=S((HOST,PORT),H)
    _ip=_sock.gethostbyname(_sock.gethostname())
    print(f"IPTV v12 -> http://{_ip}:{PORT}/iptv.html")
    print(f"  LAN access: http://{_ip}:{PORT}/iptv.html")
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.server_close()
