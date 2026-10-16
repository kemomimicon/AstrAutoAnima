import copy
import json
import secrets
from .workflow_runtime import WorkflowError


def copy_context(job: dict, index: int, overrides: dict):
    """Recover editable prompt/options from an authorized job, never its tickets."""
    inputs = job.get("input", {})
    if str(overrides.get('style', '')).startswith('__hub_suite_') and not (inputs.get('prompt') or inputs.get('raw_batch_prompts')):
        raise WorkflowError('原图缺少独立基础提示词，不能可靠去除原角色画风以执行套组')
    batches = inputs.get("raw_batch_prompts") or inputs.get("batch_prompts") or []
    if batches:
        if not 0 <= index < len(batches):
            raise WorkflowError("原任务图片索引无效")
        prompt = batches[index]
    else:
        prompt = inputs.get("prompt") or inputs.get("compiled_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise WorkflowError("原任务未保存可编辑提示词")
    allowed = {"character", "character_variant", "style", "character_tag_mode", "ratio", "width", "height", "size", "sampler", "scheduler", "steps", "cfg", "lighting_key", "lighting_effect", "material_primary", "material_details", "material_surface", "camera_distance", "camera_yaw", "camera_pitch", "camera_lens", "camera_roll", "detail_hands", "detail_feet", "detail_face"}
    aliases = {"steps": "sampler_steps", "cfg": "sampler_cfg", "sampler": "sampler_preset"}
    allowed.update(aliases.values())
    allowed.update({"character_strength", "character_model", "character_clip", "style_scale"})
    options = {aliases.get(k, k): copy.deepcopy(v) for k,v in inputs.get("generation_options", {}).items() if k in allowed}
    model = job.get("model", {})
    for key in ("character", "style"):
        if key not in options and model.get(key + "_name"):
            options[key] = model[key + "_name"]
    for key in ("steps", "cfg", "scheduler"):
        if job.get("sampling", {}).get(key) is not None:
            options[aliases.get(key, key)] = job["sampling"][key]
    if job.get("sampling", {}).get("sampler_name"):
        options["sampler_preset"] = job["sampling"]["sampler_name"]
        if not any(k in overrides for k in ("sampler", "sampler_preset")):
            options["_replay_sampler_name"] = job["sampling"]["sampler_name"]
    if job.get("sampling", {}).get("denoise") is not None:
        options["_replay_denoise"] = job["sampling"]["denoise"]
    if not any(k in options for k in ("ratio", "size", "width", "height")):
        sizes = {(n.get("inputs", {}).get("width"), n.get("inputs", {}).get("height"))
                 for n in job.get("workflow_snapshot", {}).values()
                 if isinstance(n.get("inputs", {}).get("width"), int) and isinstance(n.get("inputs", {}).get("height"), int)}
        if len(sizes) == 1:
            options["width"], options["height"] = sizes.pop()
    if any(k in overrides for k in ("ratio", "size", "width", "height")):
        for key in ("ratio", "size", "width", "height"):
            options.pop(key, None)
    if "character" in overrides:
        options.pop("character_variant", None)
    options.update({aliases.get(k, k): v for k,v in overrides.items() if k in allowed})
    for kind in ("character", "style"):
        saved = inputs.get("preset_snapshot", {}).get(kind)
        if kind not in overrides and isinstance(saved, dict):
            options["_copy_" + kind] = copy.deepcopy(saved)
            options[kind] = options.get(kind) or "原任务" + kind
    return prompt, options


def append_prompt(original: str, addition: str) -> str:
    """Literal addition: never ask a model to rewrite or discard the source."""
    if not isinstance(original, str) or not original.strip():
        raise WorkflowError("原任务未保存可编辑提示词")
    result = original + (", " + addition.strip() if addition.strip() else "")
    if len(result) > 16000:
        raise WorkflowError("追加后的提示词超过 16000 字符，请缩短补充内容")
    return result


def append_snapshot_prompt(job: dict, graph: dict, index: int, addition: str):
    """Patch supported positive encoders only; reject unknown/shared conditioning."""
    graph = copy.deepcopy(graph)
    positive, negative = set(), set()

    def walk(value, seen):
        if not (isinstance(value, list) and len(value) == 2 and str(value[0]) in graph):
            return
        key = str(value[0])
        if key in seen:
            return
        seen.add(key)
        for field, child in graph[key].get("inputs", {}).items():
            if field not in {"model", "clip", "vae", "negative", "negative_prompt"}:
                walk(child, seen)

    for node in graph.values():
        for field, value in node.get("inputs", {}).items():
            if field in {"positive", "positive_prompt"}:
                if isinstance(value, str):
                    raise WorkflowError("原工作流使用内联提示词，暂不支持安全追加")
                walk(value, positive)
            elif field in {"negative", "negative_prompt"}:
                walk(value, negative)
    targets = []
    for key in positive:
        node = graph[key]
        if node.get("class_type") == "CLIPTextEncode":
            fields = ["text"]
        elif node.get("class_type") == "AnimaPromptBatchEncode":
            fields = ["prompts_json"]
        else:
            if any(field in node.get("inputs", {}) for field in ("text", "text_g", "text_l", "prompt", "prompts_json")):
                raise WorkflowError("原工作流含未支持的正向文本节点，拒绝只修改部分提示词")
            continue
        if key in negative:
            raise WorkflowError("原工作流正负提示词共用节点，不能安全追加")
        for field in fields:
            value = node.get("inputs", {}).get(field)
            if not isinstance(value, str):
                raise WorkflowError("原提示词由动态节点提供，不能可靠追加；请使用无修改重跑")
            if field == "prompts_json":
                values = json.loads(value)
                if not isinstance(values, list) or len(values) != 1:
                    raise WorkflowError("重跑批次未收敛为一张，拒绝错配提示词")
                node["inputs"][field] = json.dumps([append_prompt(values[0], addition)], ensure_ascii=False)
            else:
                node["inputs"][field] = append_prompt(value, addition)
            targets.append((key, field))
    if not targets:
        raise WorkflowError("原工作流没有可安全追加的正向文本节点；不会退回默认工作流")
    result = copy.deepcopy(job)
    inputs = result.setdefault("input", {})
    for field in ("prompt", "compiled_prompt"):
        if isinstance(inputs.get(field), str) and inputs[field].strip():
            inputs[field] = append_prompt(inputs[field], addition)
    for field in ("batch_prompts", "raw_batch_prompts"):
        values = inputs.get(field)
        if values:
            if not 0 <= index < len(values):
                raise WorkflowError("原批次提示词序号不一致")
            values[index] = append_prompt(values[index], addition)
    inputs["remake_edit_mode"] = "append_snapshot"
    inputs["remake_addition"] = addition
    return result, graph


def quoted_style_preset(job):
    """Use only recorded style content, never the full positive prompt or live presets."""
    import math
    snapshot = job.get('input', {}).get('preset_snapshot', {}).get('style')
    stack = job.get('model', {}).get('lora_stack')
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('prompt', ''), str) or not isinstance(stack, list):
        raise WorkflowError('原任务缺少可靠画风快照，不能从显示文本猜测保存')
    loras = []
    for entry in stack:
        if entry.get('kind') != 'style':
            continue
        name = entry.get('name')
        if not isinstance(name, str) or not name.strip():
            raise WorkflowError('原任务画风 LoRA 文件名无效')
        weights = [entry.get('strength_model'), entry.get('strength_clip')]
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in weights):
            raise WorkflowError('原任务画风权重不完整或无效')
        loras.append(dict(name=name, strength_model=weights[0], strength_clip=weights[1]))
    prompt = snapshot.get('prompt', '').strip()
    if not loras and not prompt:
        raise WorkflowError('该图没有可保存的画风配置')
    return {'loras': loras, 'prompt': prompt, 'match': []}


def replay_workflow(job: dict, index: int, *, fixed_seed: bool = False):
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise WorkflowError('原任务图片索引无效')
    graph = copy.deepcopy(job.get("workflow_snapshot"))
    if not isinstance(graph, dict) or not graph:
        raise WorkflowError("旧任务未保存工作流快照，无法保证按原参数重跑。")
    batch = job.get("input", {}).get("batch_prompts", [])
    seed = secrets.randbelow(2**32)
    old_seed = job.get("sampling", {}).get("seed")
    if fixed_seed:
        if isinstance(old_seed, bool) or not isinstance(old_seed, int) or old_seed < 0:
            raise WorkflowError('原任务未保存有效种子，不能固定种子重跑')
        if batch and len(batch) > 1:
            raise WorkflowError('原图来自合批采样，无法保证单张恢复同一随机噪声；请取消固定种子')
        seed = old_seed
    if not fixed_seed and seed == old_seed:
        seed = (seed + 1) % 2**32
    changed = False
    for node in graph.values():
        inputs = node.get("inputs", {})
        for name in ("seed", "noise_seed"):
            if isinstance(inputs.get(name), int):
                if not fixed_seed:
                    inputs[name] = seed
                changed = True
        if batch and node.get("class_type") == "AnimaPromptBatchEncode":
            if index >= len(batch):
                raise WorkflowError("原批次图片索引无效")
            inputs["prompts_json"] = json.dumps([batch[index]], ensure_ascii=False)
        if batch and "batch_size" in inputs:
            inputs["batch_size"] = 1
    if not changed:
        raise WorkflowError("原工作流没有可识别的随机种子节点，拒绝伪装成重新采样。")
    return graph, seed, (0 if batch else job.get("input", {}).get("replay_output_index", index))


def hq_replay_job(store, job):
    """Replay a recorded base -> optional detail repair -> SeedVR2 chain."""
    base_id = job.get('enhance', {}).get('hq_base_job_id')
    if not base_id or str(base_id) == str(job.get('job_id', '')):
        return job
    base = store.get_job(base_id)
    base_graph = copy.deepcopy(base.get('workflow_snapshot', {}))
    final_graph = copy.deepcopy(job.get('workflow_snapshot', {}))

    def remap(graph, prefix):
        for node in graph.values():
            for key, value in node.get('inputs', {}).items():
                if isinstance(value, list) and len(value) == 2 and str(value[0]) in graph and isinstance(value[1], int):
                    node['inputs'][key] = [prefix + str(value[0]), value[1]]
        return {prefix + key: node for key, node in graph.items()}

    def connect(source_graph, target_graph, source_prefix):
        outputs = [
            node.get('inputs', {}).get('images')
            for node in source_graph.values()
            if node.get('class_type') == 'SaveImage'
        ]
        loaders = [
            key
            for key, node in target_graph.items()
            if node.get('class_type') == 'LoadImage'
        ]
        if len(outputs) != 1 or len(loaders) != 1 or not isinstance(outputs[0], list):
            raise WorkflowError('HQ 原任务链路不唯一，拒绝跳过局部修复或只重跑放大阶段')
        source_output = [source_prefix + str(outputs[0][0]), outputs[0][1]]
        loader = loaders[0]
        for node in target_graph.values():
            for key, value in node.get('inputs', {}).items():
                if isinstance(value, list) and len(value) == 2 and str(value[0]) == loader:
                    if value[1] != 0:
                        raise WorkflowError('HQ 链路依赖输入遮罩，无法安全合并重跑')
                    node['inputs'][key] = source_output.copy()
        del target_graph[loader]

    detail_id = job.get('enhance', {}).get('hq_detail_job_id')
    if detail_id and str(detail_id) != str(job.get('job_id', '')):
        detail = store.get_job(detail_id)
        detail_graph = copy.deepcopy(detail.get('workflow_snapshot', {}))
        connect(base_graph, detail_graph, 'base_')
        connect(detail_graph, final_graph, 'detail_')
        merged = remap(base_graph, 'base_')
        merged = {k: v for k, v in merged.items() if v.get('class_type') not in {'SaveImage', 'PreviewImage'}}
        detail_remapped = remap(detail_graph, 'detail_')
        merged.update({k: v for k, v in detail_remapped.items() if v.get('class_type') not in {'SaveImage', 'PreviewImage'}})
    else:
        connect(base_graph, final_graph, 'base_')
        merged = remap(base_graph, 'base_')
        merged = {k: v for k, v in merged.items() if v.get('class_type') not in {'SaveImage', 'PreviewImage'}}
    merged.update(remap(final_graph, 'final_'))
    result = copy.deepcopy(job)
    result['workflow_snapshot'] = merged
    result['input'] = copy.deepcopy(base.get('input', {}))
    result['model'] = copy.deepcopy(base.get('model', {}))
    result['sampling'] = copy.deepcopy(base.get('sampling', {}))
    result['enhance'].pop('hq_base_job_id', None)
    result['enhance'].pop('hq_detail_job_id', None)
    result['enhance']['hq_replay_full_chain'] = True
    return result
