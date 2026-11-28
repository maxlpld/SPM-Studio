"""Approval channel for Claude Code: a minimal MCP server over stdio (standard library only).

Claude Code is started with ``--permission-prompt-tool mcp__spmhub__approve``: whenever it would show a
permission prompt it calls this tool instead. The tool forwards the request to the Agent Hub over a local
socket (127.0.0.1, one-time token) and returns the user's answer as Claude Code expects it:
``{"behavior": "allow", "updatedInput": {...}}`` or ``{"behavior": "deny", "message": "..."}``.

Run as ``python approval_mcp.py --port N --token T --chat ID``. Never imports SPM Studio or Qt.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys

PROTOCOL = '2025-06-18'
TOOL = {
    'name': 'approve',
    'description': 'Ask the SPM Studio user to allow or deny a tool call (used by Claude Code permission prompts).',
    'inputSchema': {'type': 'object',
                    'properties': {'tool_name': {'type': 'string'}, 'input': {'type': 'object'},
                                   'tool_use_id': {'type': 'string'}},
                    'required': ['tool_name', 'input']},
}


def ask_hub(port: int, token: str, chat: str, tool_name: str, tool_input: dict) -> dict:
    request = json.dumps({'token': token, 'chat': chat, 'tool': tool_name, 'input': tool_input}) + '\n'
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=10) as sock:
            sock.settimeout(None)                      # the user may take their time
            sock.sendall(request.encode('utf8'))
            buffer = b''
            while b'\n' not in buffer:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
        answer = json.loads(buffer.decode('utf8').strip() or '{}')
    except (OSError, ValueError) as exc:
        return {'behavior': 'deny', 'message': f'SPM Studio could not ask the user ({exc}). Try again later.'}
    if answer.get('behavior') == 'allow':
        return {'behavior': 'allow', 'updatedInput': tool_input}
    return {'behavior': 'deny', 'message': str(answer.get('message') or 'The user denied this action.')}


def handle(message: dict, args) -> dict | None:
    method = message.get('method')
    mid = message.get('id')
    if mid is None:                                   # notification
        return None
    if method == 'initialize':
        version = (message.get('params') or {}).get('protocolVersion') or PROTOCOL
        return {'jsonrpc': '2.0', 'id': mid, 'result': {
            'protocolVersion': version, 'capabilities': {'tools': {}},
            'serverInfo': {'name': 'spmhub', 'version': '1.0'}}}
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {}}
    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'tools': [TOOL]}}
    if method == 'tools/call':
        params = message.get('params') or {}
        if params.get('name') != 'approve':
            return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32602, 'message': 'Unknown tool'}}
        arguments = params.get('arguments') or {}
        tool_input = arguments.get('input') if isinstance(arguments.get('input'), dict) else {}
        decision = ask_hub(args.port, args.token, args.chat, str(arguments.get('tool_name', '')), tool_input)
        return {'jsonrpc': '2.0', 'id': mid,
                'result': {'content': [{'type': 'text', 'text': json.dumps(decision)}]}}
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'Method not found: {method}'}}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--chat', default='')
    args = parser.parse_args(argv)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(message, args) if isinstance(message, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()
