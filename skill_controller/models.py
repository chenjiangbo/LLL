from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_TAP_SECONDS = 0.05


@dataclass
class IndependentAction:
    name: str = "新动作"
    kind: str = "key"  # key 或 mouse
    value: str = "t"
    press_mode: str = "tap"  # tap 或 hold
    tap_seconds: float = DEFAULT_TAP_SECONDS
    interval_seconds: float = 1.0
    initial_delay_seconds: float = 0.0
    hold_seconds: float = 0.0


@dataclass
class SequenceStep:
    kind: str = "key"  # key、mouse 或 wait
    value: str = "t"
    press_mode: str = "tap"
    tap_seconds: float = DEFAULT_TAP_SECONDS
    hold_seconds: float = 0.0
    wait_after_seconds: float = 0.0


@dataclass
class SequenceAction:
    name: str = "新顺序动作"
    interval_seconds: float = 1.0
    initial_delay_seconds: float = 0.0
    steps: list[SequenceStep] = field(default_factory=list)


@dataclass
class SkillDefinition:
    name: str = "新技能"
    trigger_key: str = "d"
    trigger_mode: str = "toggle"  # toggle、hold、once
    switch_wait_seconds: float = 0.15
    independent_actions: list[IndependentAction] = field(default_factory=list)
    sequence_actions: list[SequenceAction] = field(default_factory=list)


@dataclass
class Profile:
    name: str = "默认方案"
    master_enabled_by_default: bool = True
    master_toggle_key: str = "f2"
    skills: list[SkillDefinition] = field(default_factory=list)


def _step_from_dict(data: dict[str, Any]) -> SequenceStep:
    return SequenceStep(**data)


def _independent_from_dict(data: dict[str, Any]) -> IndependentAction:
    return IndependentAction(**data)


def _sequence_from_dict(data: dict[str, Any]) -> SequenceAction:
    data = dict(data)
    data["steps"] = [_step_from_dict(step) for step in data.get("steps", [])]
    return SequenceAction(**data)


def skill_from_dict(data: dict[str, Any]) -> SkillDefinition:
    data = dict(data)
    data["independent_actions"] = [
        _independent_from_dict(action)
        for action in data.get("independent_actions", [])
    ]
    data["sequence_actions"] = [
        _sequence_from_dict(action)
        for action in data.get("sequence_actions", [])
    ]
    return SkillDefinition(**data)


def profile_from_dict(data: dict[str, Any]) -> Profile:
    data = dict(data)
    data["skills"] = [skill_from_dict(skill) for skill in data.get("skills", [])]
    return Profile(**data)


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    return asdict(profile)


def default_profile() -> Profile:
    return Profile(
        skills=[
            SkillDefinition(
                name="D 示例",
                trigger_key="d",
                independent_actions=[
                    IndependentAction(name="T 每 2 秒", value="t", interval_seconds=2.0),
                    IndependentAction(name="W 每 5 秒", value="w", interval_seconds=5.0),
                    IndependentAction(name="1 每 5 秒", value="1", interval_seconds=5.0),
                    IndependentAction(name="2 每 5 秒", value="2", interval_seconds=5.0),
                ],
            ),
            SkillDefinition(
                name="S 示例",
                trigger_key="s",
                independent_actions=[
                    IndependentAction(name="1 每 2 秒", value="1", interval_seconds=2.0),
                    IndependentAction(name="2 每 3 秒", value="2", interval_seconds=3.0),
                ],
                sequence_actions=[
                    SequenceAction(
                        name="空格后 T",
                        interval_seconds=0.1,
                        steps=[
                            SequenceStep(value="space", wait_after_seconds=0.3),
                            SequenceStep(value="t", wait_after_seconds=0.1),
                        ],
                    )
                ],
            ),
            SkillDefinition(
                name="F 示例",
                trigger_key="f",
                sequence_actions=[
                    SequenceAction(
                        name="T-Q-R",
                        interval_seconds=0.0,
                        steps=[
                            SequenceStep(value="t", wait_after_seconds=0.2),
                            SequenceStep(
                                value="q",
                                press_mode="hold",
                                hold_seconds=2.5,
                                wait_after_seconds=0.0,
                            ),
                            SequenceStep(value="r"),
                        ],
                    )
                ],
            ),
        ]
    )
