from __future__ import annotations


def build_avatar_review_packet(
    *,
    task_hint: str,
    target_alias: str,
    candidate_id: str,
    avatar_position,
    avatar_rotation,
    motion_name: str,
    motion_mode: str,
    validation_summary: dict,
    artifacts: list[dict],
) -> dict:
    ordered_artifacts = []
    for expected_label in ("avatar_eye", "user_camera"):
        match = next(
            (
                artifact for artifact in (artifacts or [])
                if artifact.get("label") == expected_label and artifact.get("file_path")
            ),
            None,
        )
        if match:
            ordered_artifacts.append(match)

    artifact_paths = [artifact["file_path"] for artifact in ordered_artifacts]

    context_lines = [
        f"Task: {task_hint}",
        f"Target: {target_alias}",
        f"Candidate: {candidate_id}",
        f"Avatar position: {avatar_position}",
        f"Avatar rotation: {avatar_rotation}",
        f"Motion: {motion_name} ({motion_mode})",
        (
            "Validation summary: "
            f"distance_to_target={validation_summary.get('distance_to_target')}, "
            f"facing_score={validation_summary.get('facing_score')}, "
            f"collision_free={validation_summary.get('collision_free')}, "
            f"grounded={validation_summary.get('grounded')}"
        ),
    ]
    if ordered_artifacts:
        context_lines.append("Validation screenshots:")
        for artifact in ordered_artifacts:
            role_description = (
                "what the avatar sees"
                if artifact.get("label") == "avatar_eye"
                else "what the current user camera sees"
            )
            context_lines.append(f"- {artifact.get('label')}: {role_description}")

    return {
        "candidate_id": candidate_id,
        "artifacts": artifact_paths,
        "context_text": "\n".join(context_lines),
    }
