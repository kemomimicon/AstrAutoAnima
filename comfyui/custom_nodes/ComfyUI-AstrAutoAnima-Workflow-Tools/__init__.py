from .nodes import (
    AnimaSafetyAuditResult,
    AnimaCaptionBatchGuard,
    AnimaDatasetTypeResolver,
    AnimaImageBatchChunker,
    AnimaPromptBatchEncode,
    AnimaReverseCompiler,
    AnimaReverseResultSaver,
    AnimaTrainingCaptionCompiler,
    AnimaTrainingTagFusion,
    install_anima_batch_conditioning_compat,
)
from .idle_admission import install_idle_admission

install_idle_admission()


if install_anima_batch_conditioning_compat():
    print("[AstrAutoAnima] Anima batched conditioning compatibility enabled.")
else:
    print("[AstrAutoAnima] Anima batched conditioning compatibility unavailable.")


NODE_CLASS_MAPPINGS = {
    "AnimaSafetyAuditResult": AnimaSafetyAuditResult,
    "AnimaCaptionBatchGuard": AnimaCaptionBatchGuard,
    "AnimaImageBatchChunker": AnimaImageBatchChunker,
    "AnimaPromptBatchEncode": AnimaPromptBatchEncode,
    "AnimaTrainingTagFusion": AnimaTrainingTagFusion,
    "AnimaDatasetTypeResolver": AnimaDatasetTypeResolver,
    "AnimaTrainingCaptionCompiler": AnimaTrainingCaptionCompiler,
    "AnimaReverseCompiler": AnimaReverseCompiler,
    "AnimaReverseResultSaver": AnimaReverseResultSaver,
}


NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaCaptionBatchGuard": "Anima Caption Batch Guard",
    "AnimaImageBatchChunker": "Anima Image Batch Chunker",
    "AnimaPromptBatchEncode": "Anima Prompt Batch Encode",
    "AnimaTrainingTagFusion": "Anima Training Tag Fusion",
    "AnimaDatasetTypeResolver": "Anima Dataset Type Resolver",
    "AnimaTrainingCaptionCompiler": "Anima Training Caption Compiler",
    "AnimaReverseCompiler": "Anima Reverse Compiler",
    "AnimaReverseResultSaver": "Anima Reverse Result Saver",
}


__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
