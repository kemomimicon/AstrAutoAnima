"""Capture OneBot's actual send receipt for exact reply correlation."""
import base64
import hashlib
import json
import re
import secrets
from pathlib import Path


def delivery_scope(event):
    origin = str(getattr(event, 'unified_msg_origin', ''))
    if getattr(event, 'get_platform_name', lambda: '')() == 'qq_official':
        # QQ Official uses placeholder/different self_id values in C2C and @
        # events. The configured platform instance + exact UMO are stable.
        platform_id = str(getattr(event, 'get_platform_id', lambda: '')() or '')
        return origin + '\0qq_official:' + platform_id if origin else ''
    self_id = str(getattr(getattr(event, 'message_obj', None), 'self_id', ''))
    return origin + '\0' + self_id if origin else ''


def _message_id(receipt, depth=0):
    if depth > 2: return None
    if isinstance(receipt, dict):
        value = receipt.get('id') or receipt.get('message_id')
        if value is None and isinstance(receipt.get('data'), dict):
            return _message_id(receipt['data'], depth + 1)
    else:
        value = getattr(receipt, 'id', None) or getattr(receipt, 'message_id', None)
    if isinstance(value, bool) or not isinstance(value, (str, int)): return None
    value = str(value).strip()
    return value if value and len(value) <= 1024 and not any(ord(c) < 32 for c in value) else None


def qq_official_reply_ids(event):
    """Only explicit quoted-message fields; never the current/last message ID."""
    if getattr(event, 'get_platform_name', lambda: '')() != 'qq_official': return set()
    raw = getattr(getattr(event, 'message_obj', None), 'raw_message', None)
    def field(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    result = set()
    reference = field(raw, 'message_reference')
    value = _message_id({'id': field(reference, 'message_id')})
    if value: result.add(value)
    try: quoted = int(field(raw, 'message_type') or 0) == 103
    except (ValueError, TypeError): quoted = False
    elements = field(raw, 'msg_elements')
    if quoted and isinstance(elements, list) and elements:
        value = _message_id({'id': field(elements[0], 'id') or field(elements[0], 'message_id')})
        if value: result.add(value)
    return result


def qq_official_quote_markers(event, replies=()):
    """Read our opaque marker ONLY from original native quoted content."""
    if getattr(event, 'get_platform_name', lambda: '')() != 'qq_official': return set()
    def field(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    raw = getattr(getattr(event, 'message_obj', None), 'raw_message', None)
    texts = []
    # Reply components are constructed from the platform's original quote.
    for reply in replies:
        for key in ('message_str', 'text'):
            value = field(reply, key)
            if isinstance(value, str): texts.append(value)
    carriers = [raw]
    payload = field(raw, 'raw_data')
    if isinstance(payload, dict): carriers.append(payload)
    for carrier in carriers:
        try: quoted = int(field(carrier, 'message_type') or 0) == 103
        except (ValueError, TypeError): quoted = False
        elements = field(carrier, 'msg_elements')
        if quoted and isinstance(elements, list) and elements:
            value = field(elements[0], 'content')
            if isinstance(value, str): texts.append(value)
    result = set()
    for text in texts:
        if len(text) <= 65536:
            result.update('qqref:' + value for value in re.findall(
                r'(?<![A-Za-z0-9_-])AAA-REF:([0-9a-f]{32})(?![A-Za-z0-9_-])', text))
    # Never inspect event.message_str, raw.content or other current-message text.
    return result


def log_qq_official_quote_diagnostic(event, quote_ids, store, logger, quote_markers=()):
    """Bounded, read-only diagnosis. No raw IDs, prompts, URLs or credentials."""
    try:
        if event.get_platform_name() != 'qq_official': return
        def fingerprint(value):
            return hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:16]
        def field(obj, key):
            return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
        ids = {str(value) for value in quote_ids if value}
        marker_ids = set(quote_markers)
        scope = delivery_scope(event)
        raw = getattr(getattr(event, 'message_obj', None), 'raw_message', None)
        raw_data = field(raw, 'raw_data')
        carriers = [('sdk', raw)]
        if isinstance(raw_data, dict): carriers.append(('payload', raw_data))
        shapes = {}
        for label, carrier in carriers:
            reference = field(carrier, 'message_reference')
            elements = field(carrier, 'msg_elements')
            first = elements[0] if isinstance(elements, list) and elements else None
            candidate_ids = set()
            for candidate in (field(reference, 'message_id'), field(first, 'id'), field(first, 'message_id')):
                value = _message_id({'id': candidate})
                if value: candidate_ids.add(value)
            shapes[label] = {'reference_id_present': bool(field(reference, 'message_id')),
                             'elements_count': len(elements) if isinstance(elements, list) else 0,
                             'candidate_fingerprints': sorted(fingerprint(value) for value in candidate_ids)}
        directory = store.root / 'deliveries'
        paths = []
        if directory.is_dir() and not directory.is_symlink():
            from itertools import islice
            for path in islice(directory.glob('*.json'), 1000):
                if not path.is_symlink(): paths.append((path.stat().st_mtime, path))
        rows = []
        errors = 0
        for _, path in sorted(paths, reverse=True)[:200]:
            try:
                if path.stat().st_size > 16384: raise ValueError('oversized record')
                data = json.loads(path.read_text('utf-8-sig'))
                if not isinstance(data, dict): raise ValueError('invalid record')
                message_id = data.get('message_id', '')
                saved_scope = data.get('scope', '')
                rows.append({'id': fingerprint(message_id), 'scope': fingerprint(saved_scope),
                             'same_id': message_id in ids, 'same_marker': message_id in marker_ids,
                             'same_scope': saved_scope == scope})
            except (OSError, ValueError): errors += 1
        report = {'diagnostic': 'qqofficial.2', 'scope': fingerprint(scope),
                  'quote_ids': sorted(fingerprint(value) for value in ids), 'raw_shape': shapes,
                  'marker_ids': sorted(fingerprint(value) for value in marker_ids),
                  'records_examined': len(rows), 'record_errors': errors,
                  'id_matches': sum(row['same_id'] for row in rows),
                  'scope_matches': sum(row['same_scope'] for row in rows),
                  'exact_matches': sum(row['same_id'] and row['same_scope'] for row in rows),
                  'marker_matches': sum(row['same_marker'] and row['same_scope'] for row in rows),
                  'recent_records': rows[:3]}
        logger.info('AAA_QQ_REPLY_DIAG %s', json.dumps(report, ensure_ascii=True, sort_keys=True))
    except Exception:
        # Diagnostics must not turn a recoverable quote into a failed command.
        try: logger.info('AAA_QQ_REPLY_DIAG unavailable (no raw payload logged)')
        except Exception: pass


async def _send_qq_official(event, chain, store, job_id, index, logger):
    # QQ group quotes may include original content/attachments but NO message ID.
    # Put a per-message 128-bit random reference in that SAME message. It is a
    # scoped lookup capability, not a task ID or a global/secret configuration.
    marker = secrets.token_hex(16)
    chain.chain = [*event.plain_result('AAA-REF:' + marker + '\n').chain, *chain.chain]
    sender = getattr(event, '_post_send', None)
    if callable(sender) and hasattr(event, 'send_buffer'):
        # AstrBot v4.27.2 send() is exactly: set send_buffer; await _post_send().
        # Calling that SAME operation retains its return value and all upstream
        # media/retry/markdown/super().send behavior, without sending twice or
        # monkey-patching a shared bot/client method.
        if event.send_buffer is not None:
            raise RuntimeError('QQ 官方发送缓冲仍占用，未覆盖或重复发送，请等待当前发送结束。')
        event.send_buffer = chain
        try:
            receipt = await sender()
        finally:
            if event.send_buffer is chain: event.send_buffer = None
    else:
        # Other versions may expose receipts through send(). Never retry a
        # potentially successful send merely because its return value is empty.
        receipt = await event.send(chain)
    message_id = _message_id(receipt)
    scope = delivery_scope(event)
    if message_id is None or not scope:
        logger.warning('QQ 官方消息发送结束，但回执消息 ID 或会话标识缺失；未猜测关联、未重复发送')
        return
    for identifier in (message_id, 'qqref:' + marker):
        try:
            store.record_delivery(identifier, scope, job_id, index)
        except Exception:
            logger.warning('QQ 官方消息已发送，但原任务关联保存失败；保留任务记录，未重复发送')


async def send_tracked_text(event, text, store, job_id, index, logger):
    """Make a style receipt quotable without interpreting its displayed text."""
    bot = getattr(event, 'bot', None)
    platform = getattr(event, 'get_platform_name', lambda: '')()
    if platform == 'qq_official':
        await _send_qq_official(event, event.plain_result(text), store, job_id, index, logger)
        return
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
    if platform == 'qq_official':
        chain = event.image_result(str(path))
        if caption:
            chain.chain = [*event.plain_result(caption).chain, *chain.chain]
        await _send_qq_official(event, chain, store, job_id, index, logger)
        return
    if platform == 'telegram' and callable(getattr(getattr(event, 'client', None), 'send_photo', None)):
        # AstrBot's TelegramPlatformEvent uses this same PTB client, but its
        # send() discards the Message returned by send_photo(). Preserve it here.
        # Official source: astrbot/core/platform/sources/telegram/tg_event.py.
        group = str(getattr(getattr(event, 'message_obj', None), 'group_id', '') or '')
        target = group or str(event.get_sender_id())
        chat, separator, topic = target.partition('#')
        if (not chat.lstrip('-').isdigit() or int(chat) == 0
                or (separator and (not topic.isdigit() or int(topic) <= 0))):
            raise RuntimeError('Telegram 会话或话题地址无效，图片尚未发送')
        source = Path(path)
        if not source.is_file():
            raise RuntimeError('Telegram 待发送图片不存在')
        payload = {'chat_id': int(chat), 'photo': str(source),
                   'caption': caption or None, 'parse_mode': None}
        if separator:
            payload['message_thread_id'] = int(topic)
        if len(caption) > 1024:
            await event.send(event.plain_result(caption))
            payload['caption'] = None
        receipt = await event.client.send_photo(**payload)
        message_id = getattr(receipt, 'message_id', None)
        if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id > 0:
            try:
                store.record_delivery(str(message_id), delivery_scope(event), job_id, index)
            except Exception:
                logger.warning('Telegram 图片已发送，但消息与任务关联保存失败；未重复发送')
        else:
            logger.warning('Telegram 图片发送后未返回可验证消息 ID；未重复发送')
        return
    if platform == 'discord':
        # AstrBot's generic send() does not expose Discord's message receipt.
        # Send through the adapter's channel so a later reply can identify the
        # exact image, including one image among a five-draw batch.
        import discord
        channel = await event._get_channel()
        if channel is None:
            raise RuntimeError('Discord 频道不可用，图片尚未发送')
        receipt = await channel.send(
            content=caption or None,
            file=discord.File(str(path), filename=Path(path).name),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        message_id = getattr(receipt, 'id', None)
        if message_id is not None:
            try:
                store.record_delivery(str(message_id), delivery_scope(event), job_id, index)
            except Exception:
                logger.warning('Discord 图片已发送，但消息与任务关联保存失败；未重复发送')
        else:
            logger.warning('Discord 图片已发送，但平台未返回消息 ID；未重复发送')
        return
    if platform != 'aiocqhttp' or not callable(getattr(bot, 'call_action', None)):
        if caption:
            await event.send(event.plain_result(caption))
        receipt = await event.send(event.image_result(str(path)))
        # Some adapters return a message receipt, others intentionally return None.
        # Use only a real returned ID; never invent one or send a duplicate image.
        message_id = (receipt.get('message_id') if isinstance(receipt, dict)
                      else getattr(receipt, 'message_id', None))
        if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id > 0:
            try:
                store.record_delivery(str(message_id), delivery_scope(event), job_id, index)
            except Exception:
                logger.warning('图片已发送，但适配器消息与任务关联保存失败；未重复发送')
        elif platform == 'telegram':
            logger.warning('Telegram 适配器未返回可验证消息 ID，引用关联尚未确认；未重复发送')
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
