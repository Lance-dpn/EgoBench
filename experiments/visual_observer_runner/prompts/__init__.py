"""Central prompt entrypoint for the visual-observer runner.

This package mirrors the official run/prompts.py idea while keeping the three
visual-runner prompt surfaces in separate files:

- service.py: service agent prompt
- observer_event.py: first-stage observer event-localizer prompts
- observer_detail.py: second-stage observer detail-reader prompt
- observer_scenario.py: scenario-level visual guidance shared by observer prompts
"""

from experiments.visual_observer_runner.prompts.observer_detail import (  # noqa: F401
    OBSERVER_DETAIL_PROMPT_VERSION,
    QWEN_SEQUENCE_DETAIL_PROMPT,
    build_qwen_sequence_prompt,
)
from experiments.visual_observer_runner.prompts.observer_event import (  # noqa: F401
    OBSERVER_EVENT_PROMPT_VERSION,
    QWEN_FRAME_EVENT_LOCALIZER_PROMPT,
    QWEN_VIDEO_EVENT_LOCALIZER_PROMPT,
    build_qwen_event_prompt,
    build_qwen_video_event_prompt,
)
from experiments.visual_observer_runner.prompts.observer_scenario import (  # noqa: F401
    SCENARIO_VISUAL_GUIDANCE,
    build_observer_scene_description,
)
from experiments.visual_observer_runner.prompts.service import (  # noqa: F401
    SERVICE_PROMPT_VERSION,
    build_service_agent_prompt,
)
