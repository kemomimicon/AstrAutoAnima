from .nodes import (
    AnimaCaptionBatchGuard,
    AnimaDatasetTypeResolver,
    AnimaImageBatchChunker,
    AnimaReverseCompiler,
    AnimaReverseResultSaver,
    AnimaTrainingCaptionCompiler,
    AnimaTrainingTagFusion,
)


NODE_CLASS_MAPPINGS = {
    "AnimaCaptionBatchGuard": AnimaCaptionBatchGuard,
    "AnimaImageBatchChunker": AnimaImageBatchChunker,
    "AnimaTrainingTagFusion": AnimaTrainingTagFusion,
    "AnimaDatasetTypeResolver": AnimaDatasetTypeResolver,
    "AnimaTrainingCaptionCompiler": AnimaTrainingCaptionCompiler,
    "AnimaReverseCompiler": AnimaReverseCompiler,
    "AnimaReverseResultSaver": AnimaReverseResultSaver,
}


NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaCaptionBatchGuard": "Anima Caption Batch Guard",
    "AnimaImageBatchChunker": "Anima Image Batch Chunker",
    "AnimaTrainingTagFusion": "Anima Training Tag Fusion",
    "AnimaDatasetTypeResolver": "Anima Dataset Type Resolver",
    "AnimaTrainingCaptionCompiler": "Anima Training Caption Compiler",
    "AnimaReverseCompiler": "Anima Reverse Compiler",
    "AnimaReverseResultSaver": "Anima Reverse Result Saver",
}


__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
