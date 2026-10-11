from pathlib import Path

from core.memory.semantic_memory import SemanticMemory
from .registry import load_feature_registry


class PromptComposer:
    def __init__(self, project_root=None):
        self.project_root = self._resolve_project_root(project_root)
        self.registry = load_feature_registry(project_root=self.project_root)

    @staticmethod
    def _resolve_project_root(project_root) -> Path:
        base_dir = Path(__file__).resolve().parents[2]
        requested = Path(project_root or ".")
        candidates = [requested]
        if not requested.is_absolute():
            candidates.append((base_dir / requested).resolve())
        candidates.append(base_dir)

        for candidate in candidates:
            if (candidate / "data" / "prompts" / "manifests" / "features.json").exists():
                return candidate

        return requested

    def compose(self, enabled_features=None) -> str:
        features = enabled_features or [
            name for name, feature in self.registry.items() if feature.enabled_by_default
        ]
        sections = self._load_core_sections()
        for feature_name in features:
            feature_prompt = self._load_feature_sections(feature_name)
            sections.extend(feature_prompt)
        return "\n\n".join(section for section in sections if section)

    def _load_core_sections(self) -> list[str]:
        prompt_root = self.project_root / "data" / "prompts"
        core_files = [
            prompt_root / "core" / "identity.txt",
            prompt_root / "core" / "behavior.txt",
            prompt_root / "core" / "decision_policy.txt",
            prompt_root / "core" / "output_contract.txt",
        ]
        sections = [path.read_text(encoding="utf-8").strip() for path in core_files if path.exists()]
        knowledge_section = self._load_static_knowledge_section()
        if knowledge_section:
            sections.append(knowledge_section)
        return sections

    def _load_feature_sections(self, feature_name: str) -> list[str]:
        prompt_root = self.project_root / "data" / "prompts"
        feature = self.registry.get(feature_name)
        if not feature:
            return []
        sections = []
        for relative_path in feature.prompt_files:
            path = prompt_root / relative_path
            if path.exists():
                sections.append(path.read_text(encoding="utf-8").strip())
        return sections

    def _load_static_knowledge_section(self) -> str:
        knowledge_dir = self.project_root / "data" / "memory" / "knowledge"
        semantic = SemanticMemory(str(knowledge_dir))

        scene_conventions = semantic.get("scene_conventions") or {}
        sensors = semantic.get("sensors") or {}
        sensor_catalog = sensors.get("sensors") if isinstance(sensors, dict) else None

        if not scene_conventions and not sensor_catalog:
            return ""

        parts = ["Static domain knowledge:"]

        coordinate_system = scene_conventions.get("coordinate_system")
        if coordinate_system:
            parts.append(f"- Coordinate system: {coordinate_system}")

        units = scene_conventions.get("units")
        if units:
            parts.append(f"- Units: {units}")

        object_naming = scene_conventions.get("object_naming") or {}
        if object_naming:
            parts.append("- Naming conventions:")
            for key, value in object_naming.items():
                parts.append(f"  - {key}: {value}")

        common_states = (scene_conventions.get("state_values") or {}).get("common") or []
        if common_states:
            parts.append(f"- Common state values: {', '.join(common_states)}")

        if isinstance(sensor_catalog, dict) and sensor_catalog:
            parts.append("Available sensor types:")
            for sensor_name, sensor_info in sensor_catalog.items():
                if not isinstance(sensor_info, dict):
                    parts.append(f"- {sensor_name}")
                    continue

                line = f"- {sensor_name}: {sensor_info.get('description', '').strip()}"
                placement = sensor_info.get("typical_placement")
                if placement:
                    line += f" Typical placement: {placement}"

                key_parameters = sensor_info.get("key_parameters") or []
                if key_parameters:
                    line += f" Key parameters: {', '.join(key_parameters)}."
                else:
                    line += " Key parameters: none."

                snapshot_fields = sensor_info.get("snapshot_fields") or []
                if snapshot_fields:
                    line += f" Snapshot fields: {', '.join(snapshot_fields)}."

                value_notes = sensor_info.get("value_notes")
                if value_notes:
                    line += f" Value notes: {value_notes}"

                parts.append(line.strip())

        return "\n".join(parts)
