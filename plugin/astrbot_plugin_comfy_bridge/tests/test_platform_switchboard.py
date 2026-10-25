import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_comfy_bridge.platform_switchboard import admission_denial, admit_event, safety_subject, valid_credit_subject
from astrbot_plugin_comfy_bridge.delivery_runtime import send_tracked_image


class PlatformSwitchboardTests(unittest.TestCase):
    def test_defaults_and_fail_closed_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(admission_denial(root, 'aiocqhttp'))
            self.assertIsNone(admission_denial(root, 'webchat'))
            self.assertIsNotNone(admission_denial(root, 'telegram'))
            self.assertIsNotNone(admission_denial(root, 'discord'))
            self.assertIsNotNone(admission_denial(root, 'unknown'))
            path = root / 'hub_state' / 'platform_switchboard.json'
            path.parent.mkdir()
            path.write_text(json.dumps({'accept_new': {'qq': True, 'telegram': True,
                                                       'discord': False}}), encoding='utf-8')
            self.assertIsNone(admission_denial(root, 'telegram'))
            self.assertIsNotNone(admission_denial(root, 'discord'))
            path.write_text('{invalid', encoding='utf-8')
            self.assertIsNotNone(admission_denial(root, 'aiocqhttp'))

    def test_admitted_task_finishes_after_switch_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'hub_state' / 'platform_switchboard.json'
            path.parent.mkdir()
            path.write_text(json.dumps({'accept_new': {'qq': True, 'telegram': True,
                                                       'discord': False}}), encoding='utf-8')
            event = SimpleNamespace(get_platform_name=lambda: 'telegram')
            self.assertIsNone(admit_event(root, event))
            path.write_text(json.dumps({'accept_new': {'qq': True, 'telegram': False,
                                                       'discord': False}}), encoding='utf-8')
            self.assertIsNone(admit_event(root, event))
            self.assertIsNotNone(admit_event(root, SimpleNamespace(get_platform_name=lambda: 'telegram')))

    def test_telegram_images_go_to_origin_event(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'result.png'
            image.write_bytes(b'png-test')
            event = SimpleNamespace(get_platform_name=lambda: 'telegram',
                                    send=AsyncMock(), plain_result=lambda value: value,
                                    image_result=lambda value: ('image', value))
            asyncio.run(send_tracked_image(event, image, Mock(), 'job', 0,
                                           Mock(), caption='completed'))
            self.assertEqual(event.send.await_count, 2)
            self.assertEqual(event.send.await_args_list[0].args[0], 'completed')
            self.assertEqual(event.send.await_args_list[1].args[0], ('image', str(image)))

    def test_safety_credit_identity_is_namespaced_by_platform(self):
        self.assertEqual(safety_subject('aiocqhttp', '123456789'), '123456789')
        self.assertEqual(safety_subject('telegram', '123456789'), 'telegram:123456789')
        self.assertEqual(safety_subject('discord', '123456789'), 'discord:123456789')
        with self.assertRaises(ValueError):
            safety_subject('discord', 'not-a-user-id')
        self.assertTrue(valid_credit_subject('123456789'))
        self.assertTrue(valid_credit_subject('discord:123456789'))
        self.assertTrue(valid_credit_subject('telegram:123456789'))
        self.assertFalse(valid_credit_subject('discord:evil'))


if __name__ == '__main__':
    unittest.main()
