"""Only admission guarding and activity reporting; never shuts down ComfyUI."""
import time
from .idle_guard import admission, root_path


def install_idle_admission():
    try:
        from server import PromptServer
        from aiohttp import web
    except ImportError:
        return False
    instance = PromptServer.instance
    if getattr(instance, '_aaa_idle_admission_installed', False):
        return True
    state = {'activity': time.time(), 'active_requests': 0}

    @web.middleware
    async def guard(request, handler):
        if request.method != 'POST' or request.path.rstrip('/') not in {'/prompt', '/api/prompt'}:
            return await handler(request)
        try:
            lease = admission()
        except Exception:
            return web.json_response({'error': '实例准备休眠，暂不接受新任务'}, status=503)
        state['activity'] = time.time()
        state['active_requests'] += 1
        try:
            return await handler(request)
        finally:
            state['activity'] = time.time()
            state['active_requests'] -= 1
            if lease:
                lease.close()

    @instance.routes.get('/aaa/idle-status')
    async def status(request):
        return web.json_response({'version': 1, 'root': str(root_path()), **state})

    instance.app.middlewares.append(guard)
    instance._aaa_idle_admission_installed = True
    return True
