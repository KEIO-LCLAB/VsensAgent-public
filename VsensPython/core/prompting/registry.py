import json
from dataclasses import dataclass
from pathlib import Path


CORE_PROMPT = """You are Vsens+, an intelligent assistant embedded in a Unity-based virtual XR environment.
Users interact through XR headsets and voice commands.
You receive structured scene snapshots from Unity, including object positions, states, and sensor data.
Your role is to serve as a cognitive interface between users and the virtual environment, using brief natural language and structured control outputs.
"""


FEATURE_PROMPTS = {
    "control": """Use <control> JSON only when the user expects an action.
<control>
{"actions":[]}
</control>
""",
    "clarification": """Use <clarification> when the user intent is ambiguous and you need the user to choose a target or constraint.
<clarification>
{"question_id":"q_1","prompt":"Please choose an option.","selection_mode":"single","options":[]}
</clarification>
""",
    "proposal": """Use <proposal> when you want to present one or more candidate plans, placements, or configurations before executing them.
<proposal>
{"proposal_id":"p_1","title":"Proposal","summary":"Candidate options.","options":[]}
</proposal>
""",
    "job": """Use job-oriented language for long-running tasks such as simulation, dataset collection, training, or export.
""",
}


@dataclass(frozen=True)
class FeaturePrompt:
    name: str
    enabled_by_default: bool
    prompt_files: list[str]


def load_feature_registry(project_root=None) -> dict[str, FeaturePrompt]:
    base_dir = Path(__file__).resolve().parents[2]
    requested = Path(project_root or ".")
    candidates = [requested]
    if not requested.is_absolute():
        candidates.append((base_dir / requested).resolve())
    candidates.append(base_dir)

    root = requested
    for candidate in candidates:
        if (candidate / "data" / "prompts" / "manifests" / "features.json").exists():
            root = candidate
            break

    manifest_path = root / "data" / "prompts" / "manifests" / "features.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        feature_name: FeaturePrompt(
            name=feature_name,
            enabled_by_default=feature_data.get("enabled_by_default", False),
            prompt_files=list(feature_data.get("prompt_files", [])),
        )
        for feature_name, feature_data in raw.items()
    }
