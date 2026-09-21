from delivery_runtime import basic_image_caption


def test_caption_omits_internal_identifiers():
    text = basic_image_caption({'character_name': 'A', 'style_name': 'B', 'job_id': 'job_secret', 'canvas': '1024x1024'},
                               {'ratio': '1:1'}, {'id': 'G-001', 'sha256': 'secret'})
    assert text == '角色=A｜画风=B｜比例=1:1｜提示词编号=G-001'
    assert 'secret' not in text
