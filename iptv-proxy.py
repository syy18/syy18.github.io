#!/usr/bin/env python3
"""IPTV 本地服务器 v7 - 连接池加速 + 流式传输"""
import http.server, socketserver, urllib.parse
import os, sys, ssl, socket, time, threading
from http.client import HTTPConnection, HTTPSConnection

PORT = int(sys.argv[1]) if len(sys.argv)>1 else 18888
REPO = os.path.dirname(os.path.abspath(__file__))
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# 全局基础URL
_last_base = {'url': None}
_lock = threading.Lock()

# HTTP连接池
class ConnectionPool:
    def __init__(self):
        self._conns = {}
        self._lock = threading.Lock()

    def get(self, host, port, https=False):
        key = (host, port, https)
        with self._lock:
            if key in self._conns:
                conn = self._conns.pop(key)
                try:
                    conn.request('HEAD', '/')
                    return conn
                except:
                    pass
        if https:
            conn = HTTPSConnection(host, port, timeout=15, context=ssl_ctx)
        else:
            conn = HTTPConnection(host, port, timeout=15)
        return conn

    def put(self, host, port, https, conn):
        key = (host, port, https)
        with self._lock:
            if len(self._conns) < 20:
                self._conns[key] = conn

pool = ConnectionPool()

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {args[0]}\n")
        sys.stderr.flush()

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        p = self.path.split('?')[0]
        if p=='/' or p=='/status': self._json({"ok":True,"v":7}); return
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

    def _proxy(self):
        enc=self.path[7:]  # /proxy/
        try: target=urllib.parse.unquote(enc)
        except: self.send_error(400); return

        if not target.startswith(('http://','https://')):
            with _lock:
                base=_last_base['url']
            if base:
                target=base.rsplit('/',1)[0]+'/'+target
                self.log_message("REL -> %s", target[:90])
            else:
                self.send_error(400,"No base"); return
        else:
            if '.m3u8' in target:
                with _lock:
                    _last_base['url']=target
                self.log_message("BASE = %s", target[:90])

        try:
            p=urllib.parse.urlparse(target)
            https=p.scheme=='https'
            host=p.port and p.hostname or p.hostname
            port=p.port or (443 if https else 80)
            path=p.path or '/'
            if p.query: path+='?'+p.query

            conn=pool.get(p.hostname, port, https)
            headers={
                'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer':f'{p.scheme}://{p.netloc}/',
                'Origin':f'{p.scheme}://{p.netloc}',
                'Host':p.netloc
            }
            conn.request('GET', path, headers=headers)
            r=conn.getresponse()

            # 读取响应体
            data=r.read()
            ct=r.headers.get('Content-Type','application/octet-stream')
            if target.endswith('.m3u8') or 'mpegurl' in ct.lower(): ct='application/vnd.apple.mpegurl'

            self.send_response(r.status); self._cors()
            self.send_header('Content-Type',ct); self.send_header('Content-Length',len(data))
            self.end_headers(); self.wfile.write(data)
            pool.put(p.hostname, port, https, conn)
            self.log_message("OK %d",len(data))
        except Exception as e:
            self.log_message("ERR %s",str(e)[:60])
            try: self.send_error(502)
            except: pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','*')

    def _json(self, o):
        import json; d=json.dumps(o).encode()
        self.send_response(200); self._cors()
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',len(d)); self.end_headers(); self.wfile.write(d)

class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads=True; allow_reuse_address=True

if __name__=="__main__":
    import socket as _sock
    srv=S(('0.0.0.0',PORT),H)
    _ip=_sock.gethostbyname(_sock.gethostname())
    print(f"IPTV v7 -> http://{_ip}:{PORT}/iptv.html")
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.server_close()
