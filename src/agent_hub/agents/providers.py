"""Real direct model API adapters. Request blocking: run ONLY in worker thread."""
from __future__ import annotations
import json
from urllib.parse import urlparse,quote
from urllib.request import Request,urlopen
from urllib.error import HTTPError

DEFAULT_URLS={'openai':'https://api.openai.com/v1','anthropic':'https://api.anthropic.com/v1',
              'gemini':'https://generativelanguage.googleapis.com/v1beta',
              'openrouter':'https://openrouter.ai/api/v1','ollama':'http://127.0.0.1:11434'}


def endpoint(provider, base=''):
    url=(base or DEFAULT_URLS.get(provider,'' )).rstrip('/')
    parts=urlparse(url)
    if not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Invalid API endpoint')
    if parts.scheme!='https' and not (parts.scheme=='http' and parts.hostname in {'localhost','127.0.0.1','::1'}):
        raise ValueError('Only HTTPS remote endpoints or local HTTP endpoints are allowed')
    return url


def request_chat(provider:str, model:str, messages:list[dict], api_key:str='',base:str='',timeout:int=90) -> str:
    return request_chat_full(provider, model, messages, api_key, base, timeout)['text']


def request_chat_full(provider:str, model:str, messages:list[dict], api_key:str='',base:str='',timeout:int=90,max_tokens:int=4096) -> dict:
    """``{'text', 'model', 'usage'}``; usage only as reported by the provider (else empty)."""
    if not model.strip():raise ValueError('Select a model ID first')
    url=endpoint(provider,base)
    clipped=[{'role':m['role'],'content':m['content']} for m in messages[-25:] if m.get('role') in ('user','assistant')]
    while clipped and clipped[0]['role']!='user':clipped.pop(0)   # providers expect a user turn first
    if not clipped:raise ValueError('Nothing to send')
    if provider=='anthropic':
        dest=url+'/messages'
        payload={'model':model,'max_tokens':max_tokens,'messages':clipped}
        headers={'x-api-key':api_key,'anthropic-version':'2023-06-01'}
    elif provider=='gemini':
        dest=url+'/models/'+quote(model,safe='')+':generateContent'
        payload={'contents':[{'role': 'model' if m['role']=='assistant' else 'user','parts':[{'text':m['content']}]} for m in clipped]}
        headers={'x-goog-api-key':api_key}
    elif provider=='ollama':
        dest=url+'/api/chat'
        payload={'model':model,'messages':clipped,'stream':False}
        headers={}
    elif provider in ('openai','openrouter','custom'):
        dest=url+'/chat/completions'
        payload={'model':model,'messages':clipped,'stream':False}
        headers={'Authorization':'Bearer '+api_key}
    else:raise ValueError('Unknown provider')
    if provider!='ollama' and not api_key:
        raise ValueError('No API key available. Configure a key or use a Pi account connection.')
    req=Request(dest, data=json.dumps(payload).encode(),method='POST',
                headers={'Content-Type':'application/json',**headers})
    try:
        with urlopen(req,timeout=timeout) as response:
            headers=dict(response.headers.items())
            result=json.load(response)
    except HTTPError as exc:
        detail=''
        try:
            body=json.loads(exc.read().decode('utf8','replace') or '{}')
            err=body.get('error',body) if isinstance(body,dict) else body
            detail=str(err.get('message') if isinstance(err,dict) else err)[:300]
        except Exception:
            pass
        from .security import redact
        raise RuntimeError(f'Provider returned HTTP {exc.code}'+(f': {redact(detail)}' if detail else
                           '; check model, access and billing.')) from None
    if provider=='anthropic':
        output=''.join(p.get('text','') for p in result.get('content',[]) if p.get('type')=='text')
    elif provider=='gemini':
        output=''.join(p.get('text','') for c in result.get('candidates',[]) for p in c.get('content',{}).get('parts',[]))
    elif provider=='ollama':
        output=result.get('message',{}).get('content','')
    else:
        output=result.get('choices',[{}])[0].get('message',{}).get('content','')
    if not isinstance(output,str) or not output:
        raise RuntimeError('Provider did not return a textual message')
    usage={}
    u=result.get('usage') if isinstance(result.get('usage'),dict) else {}
    if provider=='anthropic' and u:
        usage={'input_tokens':int(u.get('input_tokens') or 0),'output_tokens':int(u.get('output_tokens') or 0),
               'cached_tokens':int(u.get('cache_read_input_tokens') or 0)}
    elif provider=='gemini' and isinstance(result.get('usageMetadata'),dict):
        m=result['usageMetadata']
        usage={'input_tokens':int(m.get('promptTokenCount') or 0),'output_tokens':int(m.get('candidatesTokenCount') or 0),
               'cached_tokens':int(m.get('cachedContentTokenCount') or 0)}
    elif provider=='ollama':
        usage={'input_tokens':int(result.get('prompt_eval_count') or 0),'output_tokens':int(result.get('eval_count') or 0)}
    elif u:
        usage={'input_tokens':int(u.get('prompt_tokens') or 0),'output_tokens':int(u.get('completion_tokens') or 0),
               'cached_tokens':int((u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0)}
    if usage:
        usage['source']='reported by the provider API'
    ratelimit={k:v for k,v in headers.items() if 'ratelimit' in k.lower()}
    return {'text':output,'model':str(result.get('model') or model),'usage':usage,'ratelimit':ratelimit}
