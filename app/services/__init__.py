from importlib import import_module

__all__ = [
    "AsrMergeService",
    "ChunkingService",
    "CharacterVoiceResolver",
    "CharacterSegmentSplitter",
    "CharacterCorrectionService",
    "CharacterIntegrityGate",
    "PostOCRCharacterResolver",
    "EngineRuntime",
    "GUIProjectBridge",
    "GPUStageScheduler",
    "OpenAISpeakerAnalysisService",
    "ProjectService",
    "ResourceDownloadService",
    "SegmentRegroupService",
    "SegmentService",
    "SpeakerDiarizationService",
    "SpeakerEmbeddingClusterer",
    "VoiceCatalogService",
    "WorkflowRuntime",
    "SubtitleMergeService",
    "SubtitleTranslationService",
]

_MODULE_MAP = {
    "AsrMergeService": ".asr_merge_service",
    "ChunkingService": ".chunking_service",
    "CharacterVoiceResolver": ".character_voice_resolver",
    "CharacterSegmentSplitter": ".character_segment_splitter",
    "CharacterCorrectionService": ".character_correction_service",
    "CharacterIntegrityGate": ".character_integrity_gate",
    "PostOCRCharacterResolver": ".post_ocr_character_resolver",
    "EngineRuntime": ".engine_runtime",
    "GUIProjectBridge": ".gui_project_bridge",
    "GPUStageScheduler": ".gpu_stage_scheduler",
    "OpenAISpeakerAnalysisService": ".openai_speaker_analysis_service",
    "ProjectService": ".project_service",
    "ResourceDownloadService": ".resource_download_service",
    "SegmentRegroupService": ".segment_regroup_service",
    "SegmentService": ".segment_service",
    "SpeakerDiarizationService": ".speaker_diarization_service",
    "SpeakerEmbeddingClusterer": ".speaker_embedding_clusterer",
    "VoiceCatalogService": ".voice_catalog_service",
    "WorkflowRuntime": ".workflow_runtime",
    "SubtitleMergeService": ".subtitle_merge_service",
    "SubtitleTranslationService": ".subtitle_translation_service",
}


def __getattr__(name):
    module_name = _MODULE_MAP.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
