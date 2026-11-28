"""Framework-independent Pi RPC event translation (checked against Pi docs/rpc.md)."""

DIALOG_METHODS=('select','confirm','input','editor')


class RpcEvents:
    """Framework-free event reducer, testable without an authenticated Pi install.

    Returns ``(kind, value)`` tuples:
    text · log · error · done · model · extension_dialog · status
    """
    def interpret(self,event:dict):
        typ=event.get('type','')
        if typ=='message_update':
            part=event.get('assistantMessageEvent',{}) or {}
            if part.get('type')=='text_delta':return ('text',str(part.get('delta','')))
            return None
        if typ=='message_end':
            message=event.get('message') or {}
            if message.get('role')=='assistant' and message.get('stopReason') in ('error','aborted'):
                reason=message.get('errorMessage') or ('Request aborted' if message.get('stopReason')=='aborted' else 'Model error')
                return ('log','Model: '+str(reason))
            return None
        if typ in ('tool_execution_start','tool_execution_end'):
            return ('log',('Running tool' if typ.endswith('start') else 'Tool finished')+': '+str(event.get('toolName','unknown')))
        if typ in ('auto_retry_start','compaction_start'):
            return ('log','Pi: '+typ.replace('_',' '))
        if typ=='response':
            if not event.get('success',False):
                return ('error',str(event.get('error','Pi command rejected')))
            command=event.get('command')
            if command=='get_state':
                model=(event.get('data') or {}).get('model') or {}
                return ('model',(str(model.get('provider','')),str(model.get('id',''))))
            if command=='prompt' and ((event.get('data') or {}).get('disposition')=='handled'):
                # An extension command handled the input without an agent run.
                return ('done','')
            return None
        # agent_settled is the authoritative end of a run; agent_end is accepted
        # for older Pi releases that do not emit agent_settled.
        if typ in ('agent_settled','agent_end'):return ('done',typ)
        if typ=='extension_ui_request':
            method=str(event.get('method',''))
            if method in DIALOG_METHODS:return ('extension_dialog',event)
            text=event.get('message') or event.get('statusText') or event.get('text') or event.get('title')
            if text:return ('status',str(text))
            return None
        if typ in ('agent_error','extension_error'):return ('error',str(event.get('error','Unknown agent error')))
        return None
