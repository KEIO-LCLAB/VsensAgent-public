"""
core/skills/skill_registry.py
Local skill dispatcher — no OpenAI tool-calling schemas required.

Skills are plain Python functions decorated with @SkillRegistry.register().
The LLM emits action names in its <control> block; the registry routes
each action to the corresponding handler and returns the result.

Public API
----------
SkillRegistry.register(action_name)      — decorator for registering a skill
SkillRegistry.dispatch(action, target, parameters) -> dict
SkillRegistry.list_skills()              — returns list of registered action names
"""
import logging
import traceback
from typing import Callable

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Class-level skill registry.  Skills are registered as side-effects when
    their module is imported; import ``core.skills.scene_skills`` at startup
    to populate all default scene skills.
    """

    _registry: dict[str, Callable] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    @classmethod
    def register(cls, action_name: str) -> Callable:
        """
        Decorator factory.  Usage::

            @SkillRegistry.register("set_state")
            def skill_set_state(target, params):
                ...
        """
        def decorator(fn: Callable) -> Callable:
            if action_name in cls._registry:
                logger.warning(
                    "[SkillRegistry] Overwriting existing skill '%s' with %s",
                    action_name, fn.__name__
                )
            cls._registry[action_name] = fn
            logger.debug("[SkillRegistry] Registered skill '%s'", action_name)
            return fn
        return decorator

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    @classmethod
    def dispatch(cls, action: str, target: str, parameters: dict) -> dict:
        """
        Route an action to its registered handler.

        Returns
        -------
        dict — the skill's return value, or an error/unknown dict on failure.
        """
        handler = cls._registry.get(action)
        if handler is None:
            logger.warning("[SkillRegistry] Unknown skill: '%s'", action)
            return {"status": "unknown_skill", "action": action, "target": target}

        try:
            result = handler(target, parameters)
            return result
        except AssertionError as exc:
            logger.warning(
                "[SkillRegistry] Validation error in skill '%s': %s", action, exc
            )
            return {
                "status": "skill_validation_error",
                "action": action,
                "target": target,
                "message": str(exc),
            }
        except Exception:
            logger.error(
                "[SkillRegistry] Unexpected error in skill '%s':\n%s",
                action, traceback.format_exc()
            )
            return {
                "status": "skill_error",
                "action": action,
                "target": target,
                "message": traceback.format_exc(),
            }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @classmethod
    def list_skills(cls) -> list[str]:
        """Return a sorted list of all registered action names."""
        return sorted(cls._registry.keys())
