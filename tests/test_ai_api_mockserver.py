"""Real HTTP integration against a local mock server, no cloud accounts."""
from __future__ import annotations
import json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from spm_studio.ai.providers import request_chat

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0'))
        body=json.loads(self.rfile.read(n))
        if self.path.endswith(':generateContent'):
            data={'candidates':[{'content':{'parts':[{'text':'Gemini test'}]}}]}
        elif self.path.endswith('/messages'):
            data={'content':[{'type':'text','text':'Anthropic test'}]}
        elif self.path.endswith('/api/chat'):
            data={'message':{'content':'Ollama test'}}
        else:
            data={'choices':[{'message':{'content':'OpenAI-compatible test'}}]}
        result=json.dumps(data).encode()
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(result)));self.end_headers();self.wfile.write(result)
    def log_message(self,*args):pass


def test_multiple_real_provider_http_adapters():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        for provider,expected in [('custom','OpenAI-compatible test'),('anthropic','Anthropic test'),
                                  ('gemini','Gemini test'),('ollama','Ollama test')]:
            assert request_chat(provider,'test-model',[{'role':'user','content':'Hi'}],
                                api_key='test-key',base=base)=='{}'.format(expected)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
