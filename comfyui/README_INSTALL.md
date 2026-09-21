# Anima 工作流包 0.5.0-beta.2 安装说明

2026-09-11 修订：公开附件名仍为 `Anima_Workflow_Pack-0.5.0.zip`，内容已升级至 beta2。
修复训练环境隔离安装器对多行 Popen、末尾逗号及 UTF-8 参数的处理。已下载旧包的用户请重新下载，
以本次发布的 SHA256SUMS.txt 为准。工作流 JSON 与自定义节点相对 beta1 未变。

本目录随 AstrAutoAnima 0.5.0-beta.1 公开测试版发布。高级工作流仍标记 Beta，必须先在测试实例验证。

## 包含内容

- `Anima_HQ_Txt2Img_Beta_api.json`：HQ Stable/Beauty。
- `Anima_Refine_Existing_Beta_api.json`：Light/Medium 低重绘精修。
- `Anima_SeedVR2_Refine_Beta_api.json`：SeedVR2 分块放大。
- `Anima_WD_CT_JoyCaption_Reverse_Beta.json`：可视化反推。
- `Anima_WD_CT_JoyCaption_Reverse_Beta_api.json`：插件调用反推。
- `Anima_WD_EVA02_Safe_Caption_Train_v2.json`：炼丹打标与质检。
- `ComfyUI-AstrAutoAnima-Workflow-Tools`：反推编译、保存、训练闸门与批次编码节点。

模型权重和外部节点不包含在仓库或 ZIP 中。

## 最简单的安装方式

从仓库根目录运行 `一键部署_AstrAutoAnima.bat`（Windows）或
`sh 一键部署_AstrAutoAnima.sh`（Linux），选择 ComfyUI 根目录，保留“自定义节点与工作流”
勾选，先点“仅预检”，确认后再部署。外部节点/模型只有主动勾选才会联网拉取。

## 手动安装

1. 把 `custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools` 复制到
   `COMFYUI_ROOT/custom_nodes/`。
2. 把 `workflows/*.json` 复制到 `COMFYUI_ROOT/user/default/workflows/`。
3. 使用启动 ComfyUI 的同一个 Python 安装辅助节点 `requirements.txt`。
4. 完整重启 ComfyUI。
5. 打开工作流，把所有 `YOUR_*` 模型、LoRA 和训练路径占位符改成自己的文件。
6. 保存可视化工作流，并用 **Save (API Format)** 重新导出插件调用版本。

不要只把不存在的 LoRA 权重设为 0；ComfyUI 仍会校验文件名。应选择真实存在的占位 LoRA，
或按自己的拓扑重新连接节点并同步修改插件节点映射。

## 外部依赖

反推可使用：

- <https://github.com/nestflow/ComfyUI-Booru-Tagger>
- <https://github.com/judian17/ComfyUI-joycaption-beta-one-GGUF>

SeedVR2 可使用：

- <https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler>
- <https://github.com/moonwhaler/comfyui-seedvr2-tilingupscaler>

CL Tagger v2 属于受许可约束的模型，必须由用户在其模型页自行接受条款并手动安装；一键部署
助手不会尝试绕过许可。所有外部项目和模型继续遵守各自许可证。

## 验收

重启后访问 `http://COMFYUI_HOST:8188/object_info`，确认所选工作流要求的节点均已出现。
然后在 ComfyUI 中手动跑通一次，再配置 AstrBot 插件的工作流路径和节点 ID。训练工作流默认
先做小批量标注与质检，不应未经抽查直接启动全量训练。
