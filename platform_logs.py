from __future__ import annotations

import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
EVENT_PLATFORM_RE = re.compile(r"\[[^\]\n]*\((?P<platform>[A-Za-z0-9_-]+)\)\]")
UMO_BANG_RE = re.compile(r"\b(?P<platform>[A-Za-z][A-Za-z0-9_-]{1,40})![^\s!]+!")
UMO_COLON_RE = re.compile(
    r"\b(?P<platform>[A-Za-z][A-Za-z0-9_-]{1,40})\s*:\s*"
    r"(?:FriendMessage|GroupMessage|GuildMessage|ChannelMessage)\b"
)
PLATFORM_NAME_RE = re.compile(r"\bplatform_name=['\"](?P<platform>[A-Za-z0-9_-]+)['\"]")

FALLBACK_PLATFORM_OPTIONS = [
    ("qq_official", "QQ 官方机器人(WebSocket)"),
    ("qq_official_webhook", "QQ 官方机器人(Webhook)"),
    ("aiocqhttp", "OneBot v11"),
    ("weixin_official_account", "微信公众平台"),
    ("wecom", "企业微信(含微信客服)"),
    ("wecom_ai_bot", "企业微信智能机器人"),
    ("weixin_oc", "个人微信"),
    ("lark", "飞书(Lark)"),
    ("dingtalk", "钉钉(DingTalk)"),
    ("telegram", "Telegram"),
    ("discord", "Discord"),
    ("misskey", "Misskey"),
    ("slack", "Slack"),
    ("line", "Line"),
    ("satori", "Satori"),
    ("kook", "KOOK"),
    ("mattermost", "Mattermost"),
    ("webchat", "WebChat"),
]

PLATFORM_ALIASES = {
    "qqofficial": "qq_official",
    "qq-official": "qq_official",
    "qqofficial_webhook": "qq_official_webhook",
    "qq-official-webhook": "qq_official_webhook",
    "wecom-ai-bot": "wecom_ai_bot",
}


def get_platform_scope_info(
    *,
    log_paths: Iterable[str | os.PathLike[str]] | None = None,
    platform_options: Iterable[tuple[str, str] | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    options = list(platform_options or discover_platform_options())
    active_channels = extract_active_platforms(log_paths, platform_options=options)
    merged = _merge_options(options, active_channels)

    items = [
        {
            "value": value,
            "label": label,
            "active": value in active_channels,
        }
        for value, label in merged
    ]
    return {
        "options": items,
        "channels": items,
        "active_channels": [value for value, _label in merged if value in active_channels],
        "log_paths": [str(path) for path in default_log_paths() if path.exists()]
        if log_paths is None
        else [str(Path(path)) for path in log_paths],
    }


def discover_platform_options() -> list[tuple[str, str]]:
    options: OrderedDict[str, str] = OrderedDict()

    for value, label in _options_from_astrbot_default_config():
        options.setdefault(value, label)
    for value, label in _options_from_astrbot_registry():
        options.setdefault(value, label)
    for value, label in FALLBACK_PLATFORM_OPTIONS:
        options.setdefault(value, label)

    return list(options.items())


def extract_active_platforms(
    log_paths: Iterable[str | os.PathLike[str]] | None = None,
    platform_options: Iterable[tuple[str, str] | dict[str, Any]] | None = None,
) -> set[str]:
    active: set[str] = set()
    paths = [Path(path) for path in log_paths] if log_paths is not None else default_log_paths()
    known_platforms = _known_platform_values(platform_options)

    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    active.update(_extract_platforms_from_log_line(line, known_platforms))
        except OSError:
            continue
    return active


def default_log_paths() -> list[Path]:
    candidates: list[Path] = []

    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path, get_astrbot_root

        root = Path(get_astrbot_root())
        data = Path(get_astrbot_data_path())
        candidates.extend(
            [
                root / "logs" / "backend.log",
                root / "logs" / "desktop.log",
                data / "logs" / "astrbot.log",
                data / "logs" / "astrbot.trace.log",
            ]
        )
    except Exception:
        pass

    home_astrbot = Path.home() / ".astrbot"
    candidates.extend(
        [
            home_astrbot / "logs" / "backend.log",
            home_astrbot / "logs" / "desktop.log",
            home_astrbot / "data" / "logs" / "astrbot.log",
            home_astrbot / "data" / "logs" / "astrbot.trace.log",
        ]
    )

    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def normalize_platform_name(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return PLATFORM_ALIASES.get(text, text)


def format_platform_label(value: str) -> str:
    labels = dict(FALLBACK_PLATFORM_OPTIONS)
    return labels.get(value, value)


def _extract_platforms_from_log_line(line: str, known_platforms: set[str]) -> set[str]:
    clean = ANSI_RE.sub("", line)
    active: set[str] = set()

    if "core.event_bus" in clean:
        match = EVENT_PLATFORM_RE.search(clean)
        if match:
            platform = normalize_platform_name(match.group("platform"))
            if platform in known_platforms:
                active.add(platform)

    if _looks_like_session_record(clean):
        for pattern in (UMO_BANG_RE, UMO_COLON_RE, PLATFORM_NAME_RE):
            for match in pattern.finditer(clean):
                platform = normalize_platform_name(match.group("platform"))
                if platform in known_platforms:
                    active.add(platform)

    return active


def _looks_like_session_record(line: str) -> bool:
    return any(
        marker in line
        for marker in (
            "!",
            "FriendMessage",
            "GroupMessage",
            "GuildMessage",
            "ChannelMessage",
            "core.event_bus",
        )
    )


def _known_platform_values(
    platform_options: Iterable[tuple[str, str] | dict[str, Any]] | None,
) -> set[str]:
    values = {value for value, _label in FALLBACK_PLATFORM_OPTIONS}
    source = list(platform_options or [])
    for option in source:
        if isinstance(option, dict):
            value = option.get("value")
        else:
            value = option[0]
        normalized = normalize_platform_name(value)
        if normalized:
            values.add(normalized)
    return values


def _options_from_astrbot_default_config() -> list[tuple[str, str]]:
    try:
        from astrbot.core.config.default import CONFIG_METADATA_2
    except Exception:
        return []

    templates = (
        CONFIG_METADATA_2.get("platform_group", {})
        .get("metadata", {})
        .get("platform", {})
        .get("config_template", {})
    )
    if not isinstance(templates, dict):
        return []

    options: list[tuple[str, str]] = []
    for label, template in templates.items():
        if not isinstance(template, dict):
            continue
        value = normalize_platform_name(template.get("type"))
        if value:
            options.append((value, str(label)))
    return options


def _options_from_astrbot_registry() -> list[tuple[str, str]]:
    try:
        from astrbot.core.platform.register import platform_registry
    except Exception:
        return []

    options: list[tuple[str, str]] = []
    for platform in platform_registry:
        value = normalize_platform_name(getattr(platform, "name", ""))
        if not value:
            continue
        label = (
            getattr(platform, "adapter_display_name", None)
            or getattr(platform, "description", None)
            or value
        )
        options.append((value, str(label)))
    return options


def _merge_options(
    options: Iterable[tuple[str, str] | dict[str, Any]],
    active_channels: Iterable[str],
) -> list[tuple[str, str]]:
    merged: OrderedDict[str, str] = OrderedDict()
    for option in options:
        if isinstance(option, dict):
            value = normalize_platform_name(option.get("value"))
            label = str(option.get("label") or format_platform_label(value))
        else:
            value = normalize_platform_name(option[0])
            label = str(option[1])
        if value:
            merged.setdefault(value, label)

    for value in sorted({normalize_platform_name(item) for item in active_channels}):
        if value:
            merged.setdefault(value, format_platform_label(value))
    return list(merged.items())
