# proxy.py PORT LOG: a loopback HTTP proxy that only records what a client asks it to reach, then refuses.
import socketserver, sys, time
class H(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline().decode(errors="replace").strip()
        with open(sys.argv[2], "a") as f:
            f.write("%s proxy got: %s\n" % (time.strftime("%H:%M:%S"), line))
        self.wfile.write(b"HTTP/1.1 403 Forbidden (recording proxy, nothing forwarded)\r\nContent-Length: 0\r\n\r\n")
socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(("127.0.0.1", int(sys.argv[1])), H)
print("proxy: ready on 127.0.0.1:%s" % sys.argv[1], flush=True)
srv.serve_forever()
