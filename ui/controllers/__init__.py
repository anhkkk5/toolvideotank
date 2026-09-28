from .pipeline_controller import PipelineController
from .preview_controller import PreviewController
from .subtitle_controller import SubtitleController

# Lazy import — BatchPipelineController kéo theo runtime_paths,
# chỉ cần khi user mở Batch panel.
def _get_batch_controller():
    from .batch_pipeline_controller import BatchPipelineController
    return BatchPipelineController

__all__ = [
    "PipelineController",
    "PreviewController",
    "SubtitleController",
    "BatchPipelineController",
]
