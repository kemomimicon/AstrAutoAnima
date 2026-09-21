"""Capture OneBot's actual send receipt for exact reply correlation."""
import base64
from pathlib import Path


def delivery_scope(event):
    origin = str(getattr(event, 'unified_msg_origin', ''))
    self_id = str(getattr(getattr(event, 'message_obj', None), 'self_id', ''))
    return origin + '\0' + self_id if origin else ''


async def send_tracked_text(event, text, store, job_id, index, logger):
    """Make a style receipt quotable without interpreting its displayed text."""
    bot = getattr(event, 'bot', None)
    platform = getattr(event, 'get_platform_name', lambda: '')()
    group = str(event.get_group_id() or '') if platform == 'aiocqhttp' else ''
    target = group or str(event.get_sender_id())
    if platform != 'aiocqhttp' or not callable(getattr(bot, 'call_action', None)) or not target.isdigit():
        await event.send(event.plain_result(text))
        return
    payload = {'message': [{'type': 'text', 'data': {'text': text}}],
               'group_id' if group else 'user_id': int(target)}
    self_id = getattr(event.message_obj, 'self_id', None)
    if self_id:
        payload['self_id'] = self_id
    receipt = await bot.call_action('send_group_msg' if group else 'send_private_msg', **payload)
    if isinstance(receipt, dict):
        message_id = receipt.get('message_id')
        if message_id is None and isinstance(receipt.get('data'), dict):
            message_id = receipt['data'].get('message_id')
        if message_id is not None:
            try:
                store.record_delivery(str(message_id), delivery_scope(event), job_id, index)
            except Exception:
                logger.warning('画风说明已发送，但任务关联保存失败；未重复发送')


def basic_image_caption(plan, options, entry=None):
    return (f"角色={plan.get('character_name') or '无'}｜画风={plan.get('style_name') or '当前画风'}"
            f"｜比例={options.get('ratio') or plan.get('canvas') or '工作流默认'}"
            f"｜提示词编号={(entry or {}).get('id') or '自定义'}")


async def send_tracked_image(event, path, store, job_id, index, logger, caption=''):
    bot = getattr(event, 'bot', None)
    platform = getattr(event, 'get_platform_name', lambda: '')()
    if platform != 'aiocqhttp' or not callable(getattr(bot, 'call_action', None)):
        if caption:
            await event.send(event.plain_result(caption))
        await event.send(event.image_result(str(path)))
        return
    group = str(event.get_group_id() or '')
    target = group or str(event.get_sender_id())
    if not target.isdigit():
        if caption:
            await event.send(event.plain_result(caption))
        await event.send(event.image_result(str(path)))
        return
    payload = {'message': [{'type': 'image', 'data': {'file': 'base64://' + base64.b64encode(Path(path).read_bytes()).decode()}}],
               'group_id' if group else 'user_id': int(target)}
    if caption:
        payload['message'].insert(0, {'type': 'text', 'data': {'text': caption}})
    self_id = getattr(event.message_obj, 'self_id', None)
    if self_id: payload['self_id'] = self_id
    # On an uncertain send error, do not send again and risk duplicate images.
    receipt = await bot.call_action('send_group_msg' if group else 'send_private_msg', **payload)
    if isinstance(receipt, dict):
        message_id = receipt.get('message_id')
        if message_id is None and isinstance(receipt.get('data'), dict): message_id = receipt['data'].get('message_id')
        if message_id is not None:
            try:
                store.record_delivery(str(message_id), delivery_scope(event), job_id, index)
            except Exception:
                logger.warning('图片已发送，但消息与任务关联保存失败；未重复发送')
