#!/usr/bin/env python3
"""IPTV 本地服务器 v6 - 全局基础URL，无竞争条件"""
import http.server, socketserver, urllib.request, urllib.error, urllib.parse
import os, sys, ssl, socket, time, threading

PORT = int(sys.argv[1]) if len(sys.argv)>1 else 18888
REPO = os.path.dirname(os.path.abspath(__file__))
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# 全局基础URL - 只设不删
_last_base = {'url': None}
_lock = threading.Lock()

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {args[0]}\n")
        sys.stderr.flush()

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        p = self.path.split('?')[0]
        if p=='/' or p=='/status': self._json({"ok":True,"v":6}); return
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
            # 相对路径 → 用全局基础URL
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
            req=urllib.request.Request(target)
            req.add_header('User-Agent','Mozilla/5.0')
            p=urllib.parse.urlparse(target)
            req.add_header('Referer',f'{p.scheme}://{p.netloc}/')
            req.add_header('Origin',f'{p.scheme}://{p.netloc}')
            r=urllib.request.urlopen(req,timeout=20,context=ssl_ctx)
            data=r.read()
            ct=r.headers.get('Content-Type','application/octet-stream')
            if target.endswith('.m3u8') or 'mpegurl' in ct.lower(): ct='application/vnd.apple.mpegurl'
            self.send_response(200); self._cors()
            self.send_header('Content-Type',ct); self.send_header('Content-Length',len(data))
            self.end_headers(); self.wfile.write(data)
            self.log_message("OK %d",len(data))
        except urllib.error.HTTPError as e: self.send_error(e.code)
        except urllib.error.URLError: self.send_error(502)
        except socket.timeout: self.send_error(504)
        except (ConnectionAbortedError,BrokenPipeError,OSError): pass
        except: 
            try: self.send_error(500)
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
    srv=S(('127.0.0.1',PORT),H)
    print(f"📺 IPTV v6 → http://127.0.0.1:{PORT}/iptv.html")
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.server_close()
