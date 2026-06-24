#!/usr/bin/env python3
"""IPTV 本地服务器 v11 - iOS兼容：HEAD支持 + m3u8重写"""
import http.server, socketserver, urllib.request, urllib.error, urllib.parse
import os, sys, ssl, socket, time, threading, json

PORT = int(sys.argv[1]) if len(sys.argv)>1 else 18888
HOST = sys.argv[2] if len(sys.argv)>2 else '0.0.0.0'
REPO = os.path.dirname(os.path.abspath(__file__))
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

_lock = threading.Lock()
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {args[0]}\n")
        sys.stderr.flush()

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_HEAD(self):
        """iOS原生HLS会先发HEAD请求探测"""
        p = self.path.split('?')[0]
        if p.startswith('/proxy/'):
            self._proxy(head_only=True)
        else:
            self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        p = self.path.split('?')[0]
        if p=='/' or p=='/status': self._json({"ok":True,"v":11}); return
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

        # 解析相对路径（兼容旧的播放器请求）
        if not target.startswith(('http://','https://')):
            with _lock:
                base=self._get_base()
            if base:
                target=base.rsplit('/',1)[0]+'/'+target
                self.log_message("REL -> %s", target[:90])
            else:
                self.send_error(400,"No base"); return

        is_m3u8 = '.m3u8' in target.lower()

        try:
            req=urllib.request.Request(target, method='HEAD' if head_only else 'GET')
            req.add_header('User-Agent', UA)
            p=urllib.parse.urlparse(target)
            req.add_header('Referer',f'{p.scheme}://{p.netloc}/')
            req.add_header('Origin',f'{p.scheme}://{p.netloc}')
            r=urllib.request.urlopen(req,timeout=8,context=ssl_ctx)

            ct=r.headers.get('Content-Type','application/octet-stream')
            if is_m3u8 or 'mpegurl' in ct.lower():
                ct='application/vnd.apple.mpegurl'

            if head_only:
                self.send_response(200); self._cors()
                self.send_header('Content-Type', ct)
                self.end_headers()
                self.log_message("HEAD OK %s", target[:70])
                return

            # GET模式：读取数据
            if is_m3u8:
                # m3u8: 读取后重写URL，让iOS原生播放器能正确跟随
                data=r.read()
                text=data.decode('utf-8', errors='ignore')
                base_url = target.rsplit('/', 1)[0] + '/'
                lines = text.split('\n')
                rewritten = []
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        # 分片URL行：改写为绝对代理URL
                        if not stripped.startswith(('http://', 'https://')):
                            stripped = base_url + stripped
                        proxy_path = '/proxy/' + urllib.parse.quote(stripped, safe='')
                        rewritten.append(proxy_path)
                    else:
                        rewritten.append(line)
                out = '\n'.join(rewritten).encode('utf-8')
                # 只发一次HTTP头
                self.send_response(200); self._cors()
                self.send_header('Content-Type', ct)
                self.send_header('Content-Length', len(out))
                self.end_headers()
                self.wfile.write(out)
                self.log_message("M3U8 rewrite %d -> %d bytes %s", len(data), len(out), target[:70])
            else:
                # .ts等：流式传输
                cl=r.headers.get('Content-Length')
                self.send_response(200); self._cors()
                self.send_header('Content-Type', ct)
                if cl:
                    self.send_header('Content-Length', cl)
                self.end_headers()
                total=0
                while True:
                    chunk=r.read(65536)
                    if not chunk: break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        total+=len(chunk)
                    except (BrokenPipeError, OSError):
                        break
                self.log_message("OK %d %s", total, target[:70])

        except urllib.error.HTTPError as e:
            self.send_error(e.code)
        except urllib.error.URLError:
            self.send_error(502)
        except socket.timeout:
            self.send_error(504)
        except (ConnectionAbortedError,BrokenPipeError,OSError):
            pass
        except:
            try: self.send_error(500)
            except: pass

    def _get_base(self):
        """获取当前会话的基础URL（线程安全）"""
        with _lock:
            return _last_base.get('url')

    def _set_base(self, url):
        with _lock:
            _last_base['url'] = url

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
    print(f"IPTV v11 -> http://{_ip}:{PORT}/iptv.html")
    print(f"  LAN access: http://{_ip}:{PORT}/iptv.html")
    try: srv.serve_forever()
    except KeyboardInterrupt: srv.server_close()
