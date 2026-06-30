from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .defaults import (
    DEFAULT_CONFIG,
    DEFAULT_NOTICE_TEMPLATE,
    DEFAULT_QUICKCOMMAND_NOTICE_TEMPLATE,
)

MODE_DISPLAY_NAMES = {
    "quickaction": "QuickAction Mode",
    "quickcommand": "QuickCommand Mode",
}
ROUTE_MODES = ("quickaction", "quickcommand")
RULE_TEMPLATE_KEY = "rule"
UI_ONLY_CONFIG_KEYS = (
    "__localaction_settings_entry",
    "__localaction_plugin_ui_notice",
)


def rule_name_key(mode: str | None) -> str:
    return "command_name" if mode == "quickcommand" else "action_name"


def get_rule_display_name(mode: str | None, rule: dict[str, Any]) -> str:
    key = rule_name_key(mode)
    fallback_key = "action_name" if key == "command_name" else "command_name"
    return str(rule.get(key) or rule.get("name") or rule.get(fallback_key) or "")


def normalize_rule_name_fields(mode: str | None, rule: dict[str, Any]) -> None:
    name = get_rule_display_name(mode, rule).strip()
    key = rule_name_key(mode)
    rule[key] = name
    if name:
        rule["name"] = name


@dataclass
class EventView:
    message: str
    sender_id: str = ""
    platform_name: str = "unknown"
    channel_type: str = "other"
    is_admin: bool = False
    unified_msg_origin: str = ""


@dataclass
class PendingAction:
    mode: str
    rule: dict[str, Any]
    confirm_text: str
    expires_at: float


@dataclass
class ShellSession:
    shell: str
    timeout: int
    expires_at: float


@dataclass
class RouteDecision:
    handled: bool = False
    should_stop: bool = False
    response_text: str | None = None
    action: dict[str, Any] | None = None
    mode: str | None = None
    rule: dict[str, Any] | None = None
    notice_text: str | None = None


@dataclass(frozen=True)
class KeywordMatch:
    keyword: str
    start: int
    end: int


@dataclass
class SleepEntry:
    until: float | None = None
    forever: bool = False

    def is_active(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if self.forever:
            return True
        return self.until is not None and self.until > now

    def remaining_seconds(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        if self.forever:
            return -1
        if self.until is None:
            return 0
        return max(0, int(self.until - now))

    def to_json(self) -> dict[str, Any]:
        return {"until": self.until, "forever": self.forever}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "SleepEntry":
        return cls(until=data.get("until"), forever=bool(data.get("forever", False)))


@dataclass
class SleepState:
    global_state: SleepEntry = field(default_factory=SleepEntry)
    modes: dict[str, SleepEntry] = field(default_factory=dict)
    rules: dict[str, SleepEntry] = field(default_factory=dict)

    def cleanup_expired(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if self.global_state.until is not None and not self.global_state.is_active(now):
            self.global_state = SleepEntry()
        self.modes.clear()
        self.rules.clear()

    def is_global_sleeping(self, now: float | None = None) -> bool:
        return self.global_state.is_active(now)

    def is_mode_sleeping(self, mode: str, now: float | None = None) -> bool:
        return False

    def is_rule_sleeping(self, rule_name: str, now: float | None = None) -> bool:
        return False

    def target_sleeping(
        self, mode: str, rule_name: str, now: float | None = None
    ) -> bool:
        return self.is_global_sleeping(now)

    def clear_all(self) -> None:
        self.global_state = SleepEntry()
        self.modes.clear()
        self.rules.clear()

    def to_json(self) -> dict[str, Any]:
        return {
            "global": self.global_state.to_json(),
            "modes": {},
            "rules": {},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "SleepState":
        return cls(
            global_state=SleepEntry.from_json(data.get("global", {})),
        )


class LocalActionRouter:
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        now_func=time.time,
        sleep_state: SleepState | None = None,
    ) -> None:
        self.now_func = now_func
        self.config = normalize_config(config or {})
        self.sleep_state = sleep_state or SleepState()
        self.pending: dict[str, PendingAction] = {}
        self.shell_sessions: dict[str, ShellSession] = {}

    def update_config(self, config: dict[str, Any] | None) -> None:
        self.config = normalize_config(config or {})

    def route(self, event: EventView) -> RouteDecision:
        now = self.now_func()
        self.sleep_state.cleanup_expired(now)
        self._cleanup_pending(now)
        sleep_wake_enabled = self._sleep_wake_enabled()

        message = (event.message or "").strip()
        if not message:
            return RouteDecision()

        pending_decision = self._handle_pending_confirmation(event, now)
        if pending_decision is not None:
            return pending_decision

        shell_session_decision = self._handle_shell_session(event, now)
        if shell_session_decision is not None:
            return shell_session_decision

        if sleep_wake_enabled:
            sleep_decision = self._handle_sleep_wake(event, now)
            if sleep_decision is not None:
                return sleep_decision

        if sleep_wake_enabled and self.sleep_state.is_global_sleeping(now):
            return RouteDecision()

        for mode in ROUTE_MODES:
            mode_conf = self.config.get(mode, {})
            if not mode_conf.get("enabled", False):
                continue
            if mode == "quickcommand":
                shell_start_decision = self._handle_shell_session_start(
                    event, mode_conf, now
                )
                if shell_start_decision is not None:
                    return shell_start_decision
            for rule in mode_conf.get("rules", []) or []:
                if not rule or not rule.get("enabled", True):
                    continue
                if not is_action_ready(rule.get("action") or {}):
                    continue
                rule_name = get_rule_display_name(mode, rule)
                if not rule_name:
                    continue
                allow_rule_channel_scope = is_rule_feature_enabled(
                    self.config, mode, "channel_scope"
                )
                channel_scope = (
                    rule.get("channel_scope")
                    if allow_rule_channel_scope and rule.get("use_channel_scope", False)
                    else mode_conf.get("channel_scope")
                )
                if not is_channel_allowed(event, effective_channel_scope(channel_scope)):
                    continue
                if not match_rule(message, rule):
                    continue
                if mode_conf.get("admin_only", True) and not event.is_admin:
                    return RouteDecision(
                        handled=True,
                        should_stop=True,
                        response_text="LocalAction：此动作仅管理员可用。",
                    )

                rule_confirm = rule.get("confirm")
                if not is_rule_feature_enabled(self.config, mode, "confirm"):
                    rule_confirm = None
                confirm = effective_confirm(mode_conf.get("confirm"), rule_confirm)
                if confirm.get("enabled", False):
                    confirm_text = str(confirm.get("confirm_text") or "确认")
                    timeout = int(confirm.get("timeout_seconds") or 30)
                    self.pending[event_key(event)] = PendingAction(
                        mode=mode,
                        rule=rule,
                        confirm_text=confirm_text,
                        expires_at=now + timeout,
                    )
                    return RouteDecision(
                        handled=True,
                        should_stop=True,
                        response_text=(
                            f"LocalAction 请求确认执行动作：{rule_name}\n"
                            f"请在 {timeout} 秒内回复：{confirm_text}"
                        ),
                    )

                return self._action_decision(mode, rule)

        return RouteDecision()

    def _handle_shell_session(
        self, event: EventView, now: float
    ) -> RouteDecision | None:
        key = event_key(event)
        session = self.shell_sessions.get(key)
        if not session:
            return None

        mode_conf = self.config.get("quickcommand", {})
        cfg = mode_conf.get("ssh_mode", {}) if isinstance(mode_conf, dict) else {}
        if not mode_conf.get("enabled", False) or not cfg.get("enabled", False):
            self.shell_sessions.pop(key, None)
            return RouteDecision(
                handled=True,
                should_stop=True,
                response_text="QuickCommand Shell 会话模式已退出。",
            )
        message = (event.message or "").strip()
        if now > session.expires_at:
            self.shell_sessions.pop(key, None)
            return RouteDecision(
                handled=True,
                should_stop=True,
                response_text="QuickCommand Shell 会话模式已超时退出。",
            )
        if match_keyword(
            message,
            cfg.get("exit_keywords", []) or [],
            normalize_match_mode(cfg.get("match_mode"), default="exact"),
        ):
            self.shell_sessions.pop(key, None)
            return RouteDecision(
                handled=True,
                should_stop=True,
                response_text="QuickCommand Shell 会话模式已退出。",
            )

        session.expires_at = now + int(session.timeout)
        action = {
            "type": "run_shell_input",
            "shell": session.shell,
            "command": message,
            "timeout": session.timeout,
        }
        return RouteDecision(
            handled=True,
            should_stop=True,
            action=action,
            mode="quickcommand",
            rule={"command_name": "Shell 会话模式", "name": "Shell 会话模式", "action": action},
            notice_text="QuickCommand Shell 会话模式执行命令：",
        )

    def _handle_shell_session_start(
        self, event: EventView, mode_conf: dict[str, Any], now: float
    ) -> RouteDecision | None:
        cfg = mode_conf.get("ssh_mode")
        if not isinstance(cfg, dict) or not cfg.get("enabled", False):
            return None
        if not is_channel_allowed(
            event, effective_channel_scope(mode_conf.get("channel_scope"))
        ):
            return None
        message = (event.message or "").strip()
        if not match_keyword(
            message,
            cfg.get("trigger_keywords", []) or [],
            normalize_match_mode(cfg.get("match_mode"), default="exact"),
        ):
            return None
        if mode_conf.get("admin_only", True) and not event.is_admin:
            return RouteDecision(
                handled=True,
                should_stop=True,
                response_text="LocalAction：此动作仅管理员可用。",
            )

        timeout = max(1, safe_int(cfg.get("timeout"), 10))
        self.shell_sessions[event_key(event)] = ShellSession(
            shell=str(cfg.get("shell") or "pwsh").strip() or "pwsh",
            timeout=timeout,
            expires_at=now + timeout,
        )
        return RouteDecision(
            handled=True,
            should_stop=True,
            mode="quickcommand",
            response_text=f"QuickCommand Shell 会话模式已进入，{timeout} 秒内无消息将自动退出。",
        )

    def _sleep_wake_enabled(self) -> bool:
        if not self.config.get("advanced_settings_enabled", False):
            return False
        cfg = self.config.get("sleep_wake", {})
        return bool(cfg.get("enabled", True))

    def action_finished_text(
        self,
        rule: dict[str, Any],
        action_text: str | None = None,
        *,
        mode: str | None = None,
    ) -> str:
        notice = self._notice_text(mode, rule)
        return join_text(notice, action_text)

    def _handle_pending_confirmation(
        self, event: EventView, now: float
    ) -> RouteDecision | None:
        key = event_key(event)
        pending = self.pending.get(key)
        if not pending:
            return None

        message = (event.message or "").strip()
        rule_name = get_rule_display_name(pending.mode, pending.rule) or "未命名动作"
        if now > pending.expires_at:
            self.pending.pop(key, None)
            return RouteDecision(
                handled=True,
                should_stop=True,
                response_text=f"LocalAction 动作确认超时，已取消：{rule_name}",
            )
        if message != pending.confirm_text:
            return RouteDecision(
                handled=True,
                should_stop=True,
                response_text=f"确认语不匹配，动作未执行。需要回复：{pending.confirm_text}",
            )

        self.pending.pop(key, None)
        return self._action_decision(pending.mode, pending.rule)

    def _action_decision(self, mode: str, rule: dict[str, Any]) -> RouteDecision:
        action = copy.deepcopy(rule.get("action") or {})
        notice = self._notice_text(mode, rule)
        return RouteDecision(
            handled=True,
            should_stop=True,
            action=action,
            mode=mode,
            rule=rule,
            notice_text=notice,
        )

    def _notice_text(self, mode: str | None, rule: dict[str, Any]) -> str:
        display_name = get_rule_display_name(mode, rule) or "未命名动作"
        action_name = display_name
        command_name = display_name
        mode_conf = self.config.get(mode, {}) if mode else {}
        template = None
        if isinstance(mode_conf, dict):
            template = mode_conf.get("notice_template")
        if template is None:
            template = self.config.get("notice_template")
        if template is None:
            template = (
                DEFAULT_QUICKCOMMAND_NOTICE_TEMPLATE
                if mode == "quickcommand"
                else DEFAULT_NOTICE_TEMPLATE
            )
        return str(template or "").format(
            action_name=action_name,
            command_name=command_name,
        )

    def _cleanup_pending(self, now: float) -> None:
        expired = [key for key, val in self.pending.items() if now > val.expires_at]
        for key in expired:
            self.pending.pop(key, None)

    def _handle_sleep_wake(self, event: EventView, now: float) -> RouteDecision | None:
        cfg = self.config.get("sleep_wake", {})
        message = (event.message or "").strip()
        if not message:
            return None
        if cfg.get("admin_only", True) and not event.is_admin:
            return None

        notice = cfg.get("notice", {})
        sleep_match_mode = normalize_match_mode(
            cfg.get("sleep_match_mode"), default="exact"
        )

        if match_keyword(message, cfg.get("status_keywords", []) or [], "exact"):
            return RouteDecision(
                handled=True,
                should_stop=True,
                response_text=self.status_text(now, notice),
            )

        if match_keyword(message, cfg.get("wake_all_keywords", []) or [], "exact"):
            return self._wake_global(notice)

        permanent_match = match_keyword(
            message, cfg.get("permanent_sleep_keywords", []) or [], sleep_match_mode
        )
        if permanent_match:
            target_text = message[permanent_match.end :].strip()
            return self._sleep_target(
                target_text,
                forever=True,
                seconds=None,
                cfg=cfg,
                notice=notice,
                now=now,
            )

        sleep_match = match_keyword(
            message, cfg.get("sleep_keywords", []) or [], sleep_match_mode
        )
        if sleep_match:
            target_text = message[sleep_match.end :].strip()
            target_name, seconds = split_target_and_duration(
                target_text,
                int(
                    cfg.get("default_sleep_seconds")
                    or DEFAULT_CONFIG["sleep_wake"]["default_sleep_seconds"]
                ),
            )
            return self._sleep_target(
                target_name,
                forever=False,
                seconds=seconds,
                cfg=cfg,
                notice=notice,
                now=now,
            )

        if match_keyword(message, cfg.get("wake_keywords", []) or [], sleep_match_mode):
            return self._wake_global(notice)

        return None

    def _sleep_target(
        self,
        target_text: str,
        *,
        forever: bool,
        seconds: int | None,
        cfg: dict[str, Any],
        notice: dict[str, str],
        now: float,
    ) -> RouteDecision:
        entry = SleepEntry(
            until=None if forever else now + int(seconds or 0),
            forever=forever,
        )
        self.sleep_state.global_state = entry
        if forever:
            text = notice.get(
                "sleep_global_forever",
                "LocalAction 已永久休眠全部 Local Action 拦截，直到手动唤醒。",
            )
        else:
            text = notice.get(
                "sleep_global",
                "LocalAction 已休眠全部 Local Action 拦截 {seconds} 秒。",
            ).format(seconds=seconds)
        return RouteDecision(handled=True, should_stop=True, response_text=text)

    def _wake_global(self, notice: dict[str, str]) -> RouteDecision:
        self.sleep_state.clear_all()
        text = notice.get("wake_global", "LocalAction 已唤醒全部 Local Action 拦截。")
        return RouteDecision(handled=True, should_stop=True, response_text=text)

    def status_text(
        self, now: float | None = None, notice: dict[str, str] | None = None
    ) -> str:
        now = self.now_func() if now is None else now
        notice = notice or self.config.get("sleep_wake", {}).get("notice", {})
        lines = [notice.get("status_title", "LocalAction 当前状态：")]
        lines.append("")
        lines.append(f"全局：{format_entry(self.sleep_state.global_state, now)}")
        return "\n".join(lines)


def normalize_config(user_config: dict[str, Any]) -> dict[str, Any]:
    normalized_user_config = expand_advanced_settings(user_config)
    if (
        "quickaction" not in normalized_user_config
        and "quickshot" in normalized_user_config
    ):
        normalized_user_config["quickaction"] = normalized_user_config["quickshot"]
    normalized_user_config.pop("quickshot", None)
    cfg = deep_merge(DEFAULT_CONFIG, normalized_user_config)
    advanced_settings_enabled = bool(cfg.get("advanced_settings_enabled", False))
    legacy_quickcommand_enabled = (
        "quickcommand_basic_enabled" in normalized_user_config
        and not isinstance(normalized_user_config.get("quickcommand"), dict)
    )

    for mode in ROUTE_MODES:
        cfg.setdefault(mode, {})
        if not isinstance(cfg[mode], dict):
            cfg[mode] = copy.deepcopy(DEFAULT_CONFIG[mode])
        cfg[mode].setdefault("confirm", {})
        cfg[mode]["confirm"].setdefault("confirm_text", "确认")
        if not cfg[mode]["confirm"].get("confirm_text"):
            cfg[mode]["confirm"]["confirm_text"] = "确认"
        cfg[mode].setdefault(
            "notice_template",
            DEFAULT_QUICKCOMMAND_NOTICE_TEMPLATE
            if mode == "quickcommand"
            else DEFAULT_NOTICE_TEMPLATE,
        )
        if mode == "quickcommand":
            normalize_quickcommand_ssh_mode(cfg[mode])
        normalize_rules(cfg[mode], mode)

    migrate_legacy_basic_settings(cfg, normalized_user_config)
    migrate_legacy_file_size_limit(cfg, normalized_user_config)
    normalize_all_channel_scopes(cfg)
    normalize_quickcommand_channel_scope_sync(cfg)
    normalize_sleep_wake_settings(cfg)
    disable_rule_advanced_features(cfg)
    normalize_rule_feature_flags(cfg)
    if legacy_quickcommand_enabled:
        cfg["quickcommand"]["enabled"] = bool(
            normalized_user_config["quickcommand_basic_enabled"]
        )

    if not advanced_settings_enabled:
        cfg["quickaction"]["admin_only"] = bool(
            cfg["quickaction"].get("admin_only", True)
        )
    cfg.pop("quickshot", None)
    cfg.pop("channel_scope", None)
    for ui_key in UI_ONLY_CONFIG_KEYS:
        cfg.pop(ui_key, None)
    for legacy_key in (
        "notice_template",
        "basic_trigger_keywords",
        "basic_confirm_text",
        "basic_admin_only",
        "quickcommand_basic_enabled",
    ):
        cfg.pop(legacy_key, None)

    return cfg


def normalize_rules(mode_conf: dict[str, Any], mode: str | None = None) -> None:
    rules = mode_conf.get("rules")
    if not isinstance(rules, list):
        mode_conf["rules"] = []
        return
    mode_scope = normalize_channel_scope(mode_conf.get("channel_scope"))
    for rule in rules:
        if isinstance(rule, dict):
            normalize_rule_name_fields(mode, rule)
            rule.setdefault("__template_key", RULE_TEMPLATE_KEY)
            rule.setdefault("enabled", True)
            if mode == "quickcommand":
                normalize_quickcommand_rule_action(mode_conf, rule)
            if "use_channel_scope" not in rule:
                rule["use_channel_scope"] = legacy_rule_uses_channel_scope(
                    mode_scope, rule
                )
            else:
                rule["use_channel_scope"] = bool(rule.get("use_channel_scope"))


def normalize_quickcommand_rule_action(
    mode_conf: dict[str, Any], rule: dict[str, Any]
) -> None:
    action = rule.get("action")
    if not isinstance(action, dict):
        rule["action"] = {"type": "run_command", "shell": "pwsh", "command": "", "timeout": 10}
        return
    action_type = str(action.get("type") or "").strip()
    if not action_type:
        rule["action"] = {"type": ""}
        return
    if action_type == "run_predefined_command":
        command_id = str(action.get("command_id") or "").strip()
        command_conf = {}
        commands = mode_conf.get("commands")
        if isinstance(commands, dict) and isinstance(commands.get(command_id), dict):
            command_conf = commands[command_id]
        rule["action"] = {
            "type": "run_command",
            "shell": str(command_conf.get("shell") or action.get("shell") or "pwsh"),
            "command": str(command_conf.get("command") or action.get("command") or ""),
            "timeout": safe_int(command_conf.get("timeout") or action.get("timeout"), 10),
        }
        return
    if action_type == "run_command":
        action["shell"] = str(action.get("shell") or "pwsh").strip() or "pwsh"
        action["command"] = str(action.get("command") or "").strip()
        action["timeout"] = safe_int(action.get("timeout"), 10)
        return
    rule["action"] = {"type": "run_command", "shell": "pwsh", "command": "", "timeout": 10}


def normalize_quickcommand_ssh_mode(mode_conf: dict[str, Any]) -> None:
    default = copy.deepcopy(DEFAULT_CONFIG["quickcommand"]["ssh_mode"])
    source = mode_conf.get("ssh_mode")
    if not isinstance(source, dict):
        source = {}
    merged = deep_merge(default, source)
    mode_conf["ssh_mode"] = {
        "enabled": bool(merged.get("enabled", False)),
        "trigger_keywords": clean_keywords(
            merged.get("trigger_keywords"), default["trigger_keywords"]
        ),
        "exit_keywords": clean_keywords(
            merged.get("exit_keywords"), default["exit_keywords"]
        ),
        "match_mode": normalize_match_mode(merged.get("match_mode"), default="exact"),
        "shell": str(merged.get("shell") or default["shell"]).strip()
        or default["shell"],
        "timeout": max(1, safe_int(merged.get("timeout"), int(default["timeout"]))),
    }


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clean_keywords(value: Any, default: list[str] | tuple[str, ...]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        candidates = re.split(r"[\n,，]+", value)
    elif isinstance(value, (list, tuple)):
        candidates = value
    else:
        candidates = [value]
    result: list[str] = []
    for item in candidates:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def legacy_rule_uses_channel_scope(
    mode_scope: dict[str, Any] | None, rule: dict[str, Any]
) -> bool:
    rule_scope = rule.get("channel_scope")
    return (
        isinstance(rule_scope, dict)
        and normalize_channel_scope(rule_scope) != normalize_channel_scope(mode_scope)
    )


def normalize_all_channel_scopes(cfg: dict[str, Any]) -> None:
    cfg["channel_scope"] = normalize_channel_scope(cfg.get("channel_scope"))
    for mode in ROUTE_MODES:
        mode_conf = cfg.get(mode, {})
        if not isinstance(mode_conf, dict):
            continue
        mode_conf["channel_scope"] = normalize_channel_scope(
            mode_conf.get("channel_scope")
        )
        for rule in mode_conf.get("rules", []) or []:
            if isinstance(rule, dict) and isinstance(rule.get("channel_scope"), dict):
                rule["channel_scope"] = normalize_channel_scope(rule["channel_scope"])


def normalize_quickcommand_channel_scope_sync(cfg: dict[str, Any]) -> None:
    quickcommand = cfg.get("quickcommand")
    quickaction = cfg.get("quickaction")
    if not isinstance(quickcommand, dict) or not isinstance(quickaction, dict):
        return

    sync_enabled = bool(quickcommand.get("sync_with_quickaction_channel_scope", False))
    quickcommand["sync_with_quickaction_channel_scope"] = sync_enabled
    if sync_enabled:
        quickcommand["channel_scope"] = copy.deepcopy(
            quickaction.get("channel_scope") or normalize_channel_scope(None)
        )


def normalize_sleep_wake_settings(cfg: dict[str, Any]) -> None:
    sleep_wake = cfg.get("sleep_wake")
    if not isinstance(sleep_wake, dict):
        return
    if sleep_wake.get("status_keywords") == ["休眠状态", "LocalAction状态"]:
        sleep_wake["status_keywords"] = list(
            DEFAULT_CONFIG["sleep_wake"]["status_keywords"]
        )
    sleep_wake["sleep_match_mode"] = normalize_match_mode(
        sleep_wake.get("sleep_match_mode"), default="exact"
    )
    sleep_wake["persist_sleep_state"] = True
    sleep_wake["allow_global_sleep"] = True
    sleep_wake["allow_mode_sleep"] = False
    sleep_wake["allow_rule_sleep"] = False


def normalize_rule_feature_flags(cfg: dict[str, Any]) -> None:
    for mode in ROUTE_MODES:
        mode_conf = cfg.get(mode)
        if not isinstance(mode_conf, dict):
            continue

        allow_rule_confirm = is_rule_feature_enabled(cfg, mode, "confirm")
        allow_rule_channel_scope = is_rule_feature_enabled(
            cfg, mode, "channel_scope"
        )
        for rule in mode_conf.get("rules", []) or []:
            if not isinstance(rule, dict):
                continue
            rule["__allow_rule_confirm"] = allow_rule_confirm
            rule["__allow_rule_channel_scope"] = allow_rule_channel_scope


def disable_rule_advanced_features(cfg: dict[str, Any]) -> None:
    for key in (
        "quickaction_rule_confirm_enabled",
        "quickaction_rule_channel_scope_enabled",
        "quickcommand_rule_confirm_enabled",
        "quickcommand_rule_channel_scope_enabled",
    ):
        cfg[key] = False


def is_rule_feature_enabled(
    cfg: dict[str, Any], mode: str, feature: str
) -> bool:
    key = f"{mode}_rule_{feature}_enabled"
    return advanced_feature_enabled(cfg, key)


def advanced_feature_enabled(cfg: dict[str, Any], key: str) -> bool:
    return bool(cfg.get("advanced_settings_enabled", False)) and bool(
        cfg.get(key, False)
    )


def normalize_channel_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    normalized = {
        "mode": "global",
        "include_channels": [],
        "exclude_channels": [],
        "platform_names": [],
    }
    if not isinstance(scope, dict):
        return normalized

    normalized.update(copy.deepcopy(scope))
    mode = str(normalized.get("mode") or "global").lower()
    if mode not in {"global", "include", "exclude", "custom"}:
        mode = "global"
    normalized["mode"] = mode

    legacy_channels = scope.get("channels")
    if isinstance(legacy_channels, list):
        if mode == "exclude":
            normalized["exclude_channels"] = list(legacy_channels)
        elif mode == "include":
            normalized["include_channels"] = list(legacy_channels)

    if not isinstance(normalized.get("include_channels"), list):
        normalized["include_channels"] = []
    if not isinstance(normalized.get("exclude_channels"), list):
        normalized["exclude_channels"] = []
    if not isinstance(normalized.get("platform_names"), list):
        normalized["platform_names"] = []
    normalized.pop("channels", None)
    return normalized


def migrate_legacy_basic_settings(
    cfg: dict[str, Any], normalized_user_config: dict[str, Any]
) -> None:
    if "notice_template" in normalized_user_config:
        template = normalized_user_config.get("notice_template")
        for mode in ROUTE_MODES:
            if not has_nested_key(normalized_user_config, mode, "notice_template"):
                cfg[mode]["notice_template"] = template

    if "basic_confirm_text" in normalized_user_config:
        confirm_text = normalized_user_config.get("basic_confirm_text") or "确认"
        for mode in ROUTE_MODES:
            if not has_nested_key(
                normalized_user_config, mode, "confirm", "confirm_text"
            ):
                cfg[mode]["confirm"]["confirm_text"] = confirm_text

    if "basic_admin_only" in normalized_user_config and not has_nested_key(
        normalized_user_config, "quickaction", "admin_only"
    ):
        cfg["quickaction"]["admin_only"] = bool(
            normalized_user_config.get("basic_admin_only")
        )

    if (
        "basic_trigger_keywords" in normalized_user_config
        and not has_nested_key(normalized_user_config, "quickaction", "rules")
        and cfg["quickaction"].get("rules")
    ):
        keywords = normalized_user_config.get("basic_trigger_keywords") or []
        if isinstance(keywords, list):
            cfg["quickaction"]["rules"][0]["trigger_keywords"] = list(keywords)
        else:
            cfg["quickaction"]["rules"][0]["trigger_keywords"] = [str(keywords)]


def migrate_legacy_file_size_limit(
    cfg: dict[str, Any], normalized_user_config: dict[str, Any]
) -> None:
    quickaction = cfg.get("quickaction")
    if not isinstance(quickaction, dict):
        return

    if "max_file_size_mb" not in normalized_user_config:
        user_quickaction = normalized_user_config.get("quickaction")
        if isinstance(user_quickaction, dict) and "max_file_size_mb" in user_quickaction:
            cfg["max_file_size_mb"] = user_quickaction["max_file_size_mb"]

    quickaction.pop("max_file_size_mb", None)


def has_nested_key(data: dict[str, Any], *keys: str) -> bool:
    cursor: Any = data
    for key in keys[:-1]:
        if not isinstance(cursor, dict):
            return False
        cursor = cursor.get(key)
    return isinstance(cursor, dict) and keys[-1] in cursor


def expand_advanced_settings(user_config: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(user_config or {})
    cfg.pop("enabled", None)
    advanced_settings = cfg.pop("advanced_settings", None)
    if not isinstance(advanced_settings, dict):
        return cfg

    if "enabled" in advanced_settings:
        cfg["advanced_settings_enabled"] = bool(advanced_settings["enabled"])
    for key in (
        "sleep_wake",
        "max_file_size_mb",
        "quickaction_rule_confirm_enabled",
        "quickaction_rule_channel_scope_enabled",
        "quickcommand_rule_confirm_enabled",
        "quickcommand_rule_channel_scope_enabled",
    ):
        if key in advanced_settings:
            cfg[key] = advanced_settings[key]
    if "quickaction" not in cfg and "quickshot" in advanced_settings:
        cfg["quickaction"] = advanced_settings["quickshot"]
    if "quickaction" not in cfg and "quickaction" in advanced_settings:
        cfg["quickaction"] = advanced_settings["quickaction"]
    if "quickcommand" not in cfg and "quickcommand" in advanced_settings:
        cfg["quickcommand"] = advanced_settings["quickcommand"]
    cfg.pop("quickshot", None)
    return cfg


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if (
            isinstance(value, dict)
            and isinstance(result.get(key), dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def match_rule(message: str, rule: dict[str, Any]) -> bool:
    keywords = [str(k) for k in rule.get("trigger_keywords", []) or [] if str(k)]
    if not keywords:
        return False
    mode = normalize_match_mode(rule.get("match_mode"), default="contains")
    for keyword in keywords:
        if mode == "exact" and message == keyword:
            return True
        if mode == "prefix" and message.startswith(keyword):
            return True
        if mode == "regex":
            try:
                if re.search(keyword, message):
                    return True
            except re.error:
                continue
        if mode not in {"exact", "prefix", "regex"} and keyword in message:
            return True
    return False


def normalize_match_mode(value: Any, default: str = "contains") -> str:
    fallback = str(default or "contains").strip().lower()
    if fallback not in {"contains", "exact", "prefix", "regex"}:
        fallback = "contains"
    mode = str(value or fallback).strip().lower()
    if mode in {"contains", "exact", "prefix", "regex"}:
        return mode
    return fallback


def match_keyword(
    message: str, keywords: list[str] | tuple[str, ...], mode: str
) -> KeywordMatch | None:
    match_mode = normalize_match_mode(mode)
    ordered = sorted([str(v) for v in keywords if str(v)], key=len, reverse=True)
    for keyword in ordered:
        if match_mode == "exact":
            if message == keyword:
                return KeywordMatch(keyword, 0, len(message))
            continue
        if match_mode == "prefix":
            if message.startswith(keyword):
                rest = message[len(keyword) :]
                if not rest or rest[:1].isspace():
                    return KeywordMatch(keyword, 0, len(keyword))
            continue
        if match_mode == "regex":
            try:
                match = re.search(keyword, message)
            except re.error:
                continue
            if match:
                return KeywordMatch(keyword, match.start(), match.end())
            continue
        index = message.find(keyword)
        if index >= 0:
            return KeywordMatch(keyword, index, index + len(keyword))
    return None


def is_action_ready(action: dict[str, Any]) -> bool:
    action_type = str(action.get("type") or "").strip()
    if not action_type:
        return False
    if action_type == "run_command" and not str(action.get("command") or "").strip():
        return False
    if action_type == "run_predefined_command" and not str(
        action.get("command_id") or ""
    ).strip():
        return False
    return True


def effective_confirm(
    mode_confirm: dict[str, Any] | None, rule_confirm: dict[str, Any] | None
) -> dict[str, Any]:
    base = {"enabled": False, "confirm_text": "确认", "timeout_seconds": 30}
    base.update(mode_confirm or {})
    if rule_confirm:
        base.update(rule_confirm)
    return base


def get_channel_type(platform_name: str) -> str:
    platform = (platform_name or "").lower()
    if platform in {
        "aiocqhttp",
        "napcat",
        "onebot",
        "qq",
        "qqofficial",
        "qq_official",
        "qqofficial_webhook",
        "qq_official_webhook",
    }:
        return "qq"
    if platform in {"webchat", "web"}:
        return "web"
    if platform in {"desktop", "client", "local"}:
        return "client"
    return "other"


def effective_channel_scope(*scopes: dict[str, Any] | None) -> dict[str, Any]:
    for scope in reversed(scopes):
        if scope:
            return scope
    return normalize_channel_scope(None)


def is_channel_allowed(event: EventView, scope: dict[str, Any] | None) -> bool:
    scope = normalize_channel_scope(scope)
    mode = str(scope.get("mode") or "global").lower()
    if mode == "global":
        return True
    channel_type = (event.channel_type or get_channel_type(event.platform_name)).lower()
    platform_name = (event.platform_name or "").lower()
    candidates = {
        normalize_channel_match_value(channel_type),
        normalize_channel_match_value(platform_name),
    }
    if mode == "include":
        channels = {
            normalize_channel_match_value(v)
            for v in scope.get("include_channels", []) or []
        }
        return bool(channels & candidates)
    if mode == "exclude":
        channels = {
            normalize_channel_match_value(v)
            for v in scope.get("exclude_channels", []) or []
        }
        return not bool(channels & candidates)
    if mode == "custom":
        platform_names = {
            normalize_channel_match_value(v)
            for v in scope.get("platform_names", []) or []
        }
        return normalize_channel_match_value(platform_name) in platform_names
    return True


def normalize_channel_match_value(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "qqofficial": "qq_official",
        "qqofficial_webhook": "qq_official_webhook",
    }
    return aliases.get(text, text)


def startswith_keyword(message: str, keywords: list[str]) -> str | None:
    ordered = sorted([str(v) for v in keywords if str(v)], key=len, reverse=True)
    for keyword in ordered:
        if message == keyword or message.startswith(keyword + " "):
            return keyword
        if message.startswith(keyword):
            rest = message[len(keyword) :]
            if not rest or rest[:1].isspace():
                return keyword
    return None


def split_target_and_duration(text: str, default_seconds: int) -> tuple[str, int]:
    text = (text or "").strip()
    if not text:
        return "", default_seconds
    parts = text.split()
    candidate = parts[-1]
    parsed = parse_duration(candidate)
    if parsed is not None:
        return " ".join(parts[:-1]).strip(), parsed

    compact_match = re.search(
        r"(?P<duration>\d+\s*(?:秒|分钟|分|小时|s|sec|min|m|h))$",
        text,
        flags=re.IGNORECASE,
    )
    if compact_match:
        duration_text = compact_match.group("duration")
        parsed = parse_duration(duration_text)
        if parsed is not None:
            return text[: compact_match.start()].strip(), parsed
    return text, default_seconds


def parse_duration(text: str) -> int | None:
    text = (text or "").strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)(秒|s|sec|secs|second|seconds)?", text)
    if match:
        return int(match.group(1))
    match = re.fullmatch(r"(\d+)(分钟|分|min|mins|m|minute|minutes)", text)
    if match:
        return int(match.group(1)) * 60
    match = re.fullmatch(r"(\d+)(小时|时|h|hour|hours)", text)
    if match:
        return int(match.group(1)) * 3600
    return None


def event_key(event: EventView) -> str:
    return event.unified_msg_origin or f"{event.platform_name}:{event.sender_id}"


def format_entry(entry: SleepEntry, now: float) -> str:
    if entry.forever:
        return "永久休眠"
    if entry.until is not None and entry.until > now:
        return f"休眠中，剩余 {entry.remaining_seconds(now)} 秒"
    return "运行中"


def join_text(*parts: str | None) -> str:
    return "\n".join(str(part) for part in parts if part)
