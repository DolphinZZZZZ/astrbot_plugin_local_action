from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star, StarTools, register

from .actions import ActionError, LocalActionExecutor, discover_available_shells
from .defaults import DEFAULT_CONFIG
from .core import (
    EventView,
    LocalActionRouter,
    SleepState,
    UI_ONLY_CONFIG_KEYS,
    get_channel_type,
    get_rule_display_name,
    legacy_rule_uses_channel_scope,
    join_text,
    normalize_config,
    normalize_channel_scope,
    normalize_match_mode,
    rule_name_key,
)
from .platform_logs import get_platform_scope_info
from .window_catalog import LocalWindowManager, format_window_info

SESSION_RISK_NOTICE = (
    "LocalAction 风险提醒：本会话首次触发本地动作。"
    "插件可能截图、读取或发送本地文件、读取日志，或执行本机命令；"
    "请确认触发词、渠道范围和动作配置可信。"
)


@register(
    "astrbot_plugin_local_action",
    "Codex",
    "本地快捷动作路由器：命中关键词后直接执行截图、文件、日志或本地命令，并阻止进入大模型。",
    "0.2.0",
)
class LocalActionPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict[str, Any] | None = None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_local_action")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sleep_state_file = self.data_dir / "sleep_state.json"
        self.risk_ack_file = self.data_dir / "risk_ack.json"
        self.risk_ack = self._load_risk_ack()
        self.window_manager = LocalWindowManager()
        self._migrate_config_for_settings_editor()
        self.router = LocalActionRouter(dict(self.config), sleep_state=self._load_sleep_state())
        self._persist_normalized_runtime_config()
        self.executor = LocalActionExecutor(
            self.router.config,
            temp_dir=self.data_dir / "temp",
            window_manager=self.window_manager,
        )

    async def initialize(self):
        self._register_web_apis()
        logger.info("LocalAction 已初始化")

    async def terminate(self):
        self._save_sleep_state_if_needed()
        logger.info("LocalAction 已销毁")

    def _migrate_config_for_settings_editor(self) -> None:
        next_config = copy.deepcopy(dict(self.config))
        changed = False
        for ui_key in UI_ONLY_CONFIG_KEYS:
            if ui_key in next_config:
                next_config.pop(ui_key, None)
                changed = True
        for mode in ("quickaction", "quickcommand"):
            mode_config = next_config.get(mode)
            if not isinstance(mode_config, dict):
                continue
            rules = mode_config.get("rules")
            if not isinstance(rules, list):
                continue
            mode_scope = mode_config.get("channel_scope")
            if not isinstance(mode_scope, dict):
                mode_scope = DEFAULT_CONFIG.get(mode, {}).get("channel_scope")
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                name_key = rule_name_key(mode)
                display_name = get_rule_display_name(mode, rule).strip()
                if display_name and rule.get(name_key) != display_name:
                    rule[name_key] = display_name
                    changed = True
                if display_name and rule.get("name") != display_name:
                    rule["name"] = display_name
                    changed = True
                if not rule.get("__template_key"):
                    rule["__template_key"] = "rule"
                    changed = True
                if "use_channel_scope" not in rule:
                    rule["use_channel_scope"] = legacy_rule_uses_channel_scope(
                        mode_scope, rule
                    )
                    changed = True
        normalized = normalize_config(next_config)
        if next_config.get("sleep_wake") != normalized.get("sleep_wake"):
            next_config["sleep_wake"] = copy.deepcopy(normalized.get("sleep_wake"))
            changed = True
        if _migrate_quickcommand_shell_session_timeout(next_config):
            changed = True
        if next_config.get("advanced_settings") != normalized.get("advanced_settings"):
            next_config["advanced_settings"] = _advanced_settings_schema_value(
                normalized
            )
            changed = True
        quickcommand = next_config.get("quickcommand")
        for mode in ("quickaction", "quickcommand"):
            mode_config = next_config.get(mode)
            normalized_rules = normalized.get(mode, {}).get("rules", [])
            if not isinstance(mode_config, dict) or not isinstance(
                normalized_rules, list
            ):
                continue
            rules = mode_config.get("rules")
            if isinstance(rules, list):
                for index, rule in enumerate(rules):
                    if not isinstance(rule, dict) or index >= len(normalized_rules):
                        continue
                    normalized_rule = normalized_rules[index]
                    if not isinstance(normalized_rule, dict):
                        continue
                    for key in (
                        "__allow_rule_confirm",
                        "__allow_rule_channel_scope",
                        "action",
                    ):
                        if key == "action":
                            value = copy.deepcopy(normalized_rule.get(key) or {})
                        else:
                            value = bool(normalized_rule.get(key, False))
                        if rule.get(key) != value:
                            rule[key] = value
                            changed = True
        if changed:
            self._replace_config(next_config)

    def _persist_normalized_runtime_config(self) -> None:
        normalized = copy.deepcopy(self.router.config)
        normalized["advanced_settings"] = _advanced_settings_schema_value(normalized)
        if dict(self.config) != normalized:
            self._replace_config(normalized)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=20)
    async def localaction_handler(self, event: AstrMessageEvent):
        self.router.update_config(dict(self.config))
        self.executor.config = self.router.config

        decision = self.router.route(self._event_view(event))
        if not decision.handled:
            return

        try:
            risk_notice = self._consume_user_risk_notice(event, decision.mode)
            if risk_notice:
                yield event.plain_result(risk_notice)
            if decision.response_text is not None:
                yield event.plain_result(decision.response_text)
            elif decision.action and decision.rule and decision.mode:
                result = await self.executor.execute(decision.mode, decision.rule)
                text = self.router.action_finished_text(
                    decision.rule,
                    result.text,
                    mode=decision.mode,
                )
                chain = MessageChain().message(text)
                for image_path in result.images:
                    chain.file_image(image_path)
                    event.track_temporary_local_file(image_path)
                for file_path in result.files:
                    chain.chain.append(File(name=Path(file_path).name, file=file_path))
                yield event.chain_result(chain.chain)
            else:
                yield event.plain_result("LocalAction：已处理。")
        except ActionError as exc:
            notice = decision.notice_text or ""
            yield event.plain_result(join_text(notice, f"LocalAction 动作被拒绝：{exc}"))
        except Exception as exc:
            logger.exception("LocalAction 动作执行失败")
            notice = decision.notice_text or ""
            yield event.plain_result(join_text(notice, f"LocalAction 动作执行失败：{exc}"))
        finally:
            self._save_sleep_state_if_needed()
            event.should_call_llm(True)
            if decision.should_stop:
                event.stop_event()

    def _event_view(self, event: AstrMessageEvent) -> EventView:
        platform_name = event.get_platform_name()
        return EventView(
            message=event.get_message_str(),
            sender_id=str(event.get_sender_id()),
            platform_name=platform_name,
            channel_type=get_channel_type(platform_name),
            is_admin=self._is_admin(event),
            unified_msg_origin=event.unified_msg_origin,
        )

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        try:
            if event.is_admin():
                return True
            astrbot_config = self.context.get_config(event.unified_msg_origin)
            admin_ids = [str(x) for x in astrbot_config.get("admins_id", [])]
            return str(event.get_sender_id()) in admin_ids
        except Exception:
            return False

    def _register_web_apis(self) -> None:
        if not hasattr(self.context, "register_web_api"):
            return
        prefix = "/astrbot_plugin_local_action"
        self.context.register_web_api(
            f"{prefix}/windows",
            self.api_windows,
            ["GET"],
            "LocalAction 可见窗口列表",
        )
        self.context.register_web_api(
            f"{prefix}/foreground",
            self.api_foreground_window,
            ["GET"],
            "LocalAction 当前前台窗口",
        )
        self.context.register_web_api(
            f"{prefix}/config",
            self.api_config,
            ["GET"],
            "LocalAction 当前配置",
        )
        self.context.register_web_api(
            f"{prefix}/platform-scope",
            self.api_platform_scope,
            ["GET"],
            "LocalAction 可用消息平台与日志命中渠道",
        )
        self.context.register_web_api(
            f"{prefix}/rules",
            self.api_rules,
            ["POST"],
            "LocalAction 规则列表配置",
        )
        self.context.register_web_api(
            f"{prefix}/rules/full",
            self.api_rules_full,
            ["POST"],
            "LocalAction 完整规则配置",
        )
        self.context.register_web_api(
            f"{prefix}/rules/enabled",
            self.api_rules_enabled,
            ["POST"],
            "LocalAction 规则启用状态配置",
        )
        self.context.register_web_api(
            f"{prefix}/settings/advanced",
            self.api_advanced_settings,
            ["POST"],
            "LocalAction 高级设置配置",
        )
        self.context.register_web_api(
            f"{prefix}/settings/risk-ack",
            self.api_settings_risk_ack,
            ["POST"],
            "LocalAction 设置页风险提示确认",
        )
        self.context.register_web_api(
            f"{prefix}/file-picker",
            self.api_file_picker,
            ["GET"],
            "LocalAction 本地文件路径选择",
        )
        self.context.register_web_api(
            f"{prefix}/screenshot-window",
            self.api_screenshot_window,
            ["POST"],
            "LocalAction 指定窗口截图",
        )
        self.context.register_web_api(
            f"{prefix}/close-process",
            self.api_close_process,
            ["POST"],
            "LocalAction 关闭匹配窗口进程",
        )

    async def api_windows(self):
        from quart import request

        limit = _parse_int(request.args.get("limit"), 80)
        query = str(request.args.get("q") or "").strip().lower()
        include_hidden = _parse_bool(request.args.get("include_hidden"), False)
        include_minimized = _parse_bool(request.args.get("include_minimized"), True)
        windows = await asyncio.to_thread(
            self.window_manager.list_windows,
            include_hidden=include_hidden,
            include_minimized=include_minimized,
        )
        if query:
            windows = [
                item
                for item in windows
                if query in item.process_name.lower()
                or query in item.title.lower()
                or query in item.class_name.lower()
                or query in str(item.pid)
            ]
        return _api_ok({"items": [item.to_dict() for item in windows[:limit]]})

    async def api_config(self):
        self.router.update_config(dict(self.config))
        self.executor.config = self.router.config
        platform_scope = get_platform_scope_info()
        return _api_ok(
            {
                "config": self.router.config,
                "platform_scope": platform_scope,
                "available_shells": discover_available_shells(),
                "settings_risk_notice_acknowledged": self._settings_risk_notice_acknowledged(),
                "initial_channel_scope": _initial_channel_scope_defaults(
                    dict(self.config),
                    self.router.config,
                    platform_scope,
                ),
            }
        )

    async def api_platform_scope(self):
        return _api_ok(get_platform_scope_info())

    async def api_foreground_window(self):
        window = await asyncio.to_thread(self.window_manager.get_foreground_window)
        if not window:
            return _api_error("当前环境无法获取前台窗口。")
        return _api_ok({"item": window.to_dict(), "text": format_window_info(window)})

    async def api_rules(self):
        from quart import request

        payload = await request.get_json(silent=True) or {}
        return self._save_rules(payload)

    async def api_rules_full(self):
        from quart import request

        payload = await request.get_json(silent=True) or {}
        return self._save_rules_full(payload)

    async def api_rules_enabled(self):
        from quart import request

        payload = await request.get_json(silent=True) or {}
        return self._save_rule_enabled_states(payload)

    async def api_advanced_settings(self):
        from quart import request

        payload = await request.get_json(silent=True) or {}
        return self._save_advanced_settings(payload)

    async def api_settings_risk_ack(self):
        self._mark_settings_risk_notice_acknowledged()
        return _api_ok(
            {"settings_risk_notice_acknowledged": True},
            "已确认 LocalAction 风险提示",
        )

    async def api_file_picker(self):
        from quart import request

        pick_type = str(request.args.get("type") or "file").strip().lower()
        path = await asyncio.to_thread(_pick_local_path, pick_type)
        if not path:
            return _api_ok({"path": ""}, "未选择路径")
        return _api_ok({"path": path})

    def _save_rules(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return _api_error("请求数据无效。")
        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in {"quickaction", "quickcommand"}:
            return _api_error("规则模式无效。")
        rows = payload.get("rules")
        if not isinstance(rows, list):
            return _api_error("规则列表无效。")

        current_raw = copy.deepcopy(dict(self.config))
        current_config = normalize_config(current_raw)
        current_rules = current_config.get(mode, {}).get("rules", [])
        if not isinstance(current_rules, list):
            current_rules = []

        next_rules = copy.deepcopy(current_rules)
        for row in rows:
            if not isinstance(row, dict):
                return _api_error("规则行无效。")
            index = _parse_int(row.get("index"), -1)
            if index < 0 or index >= len(next_rules):
                return _api_error(f"规则索引无效：{index}")
            rule = next_rules[index]
            if not isinstance(rule, dict):
                return _api_error(f"规则数据无效：{index}")

            name_key = rule_name_key(mode)
            action_name = str(
                row.get(name_key) or row.get("name") or get_rule_display_name(mode, row)
            ).strip()
            if not action_name:
                return _api_error("规则名称不能为空。")
            keywords = _parse_keywords(row.get("trigger_keywords"))
            if not keywords:
                return _api_error(f"触发关键词不能为空：{action_name}")
            match_mode = _parse_match_mode(row.get("match_mode"))

            rule["enabled"] = _parse_bool(row.get("enabled"), True)
            rule[name_key] = action_name
            rule["name"] = action_name
            rule["trigger_keywords"] = keywords
            rule["match_mode"] = match_mode

        next_config = copy.deepcopy(current_raw)
        next_mode = copy.deepcopy(next_config.get(mode) or {})
        next_mode["rules"] = next_rules
        next_config[mode] = next_mode
        self._replace_config(next_config)
        self.router.update_config(next_config)
        self.executor.config = self.router.config
        return _api_ok({"config": self.router.config}, "已保存")

    def _save_rule_enabled_states(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return _api_error("请求数据无效。")
        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in {"quickaction", "quickcommand"}:
            return _api_error("规则模式无效。")
        rows = payload.get("rules")
        if not isinstance(rows, list):
            return _api_error("规则列表无效。")

        current_raw = copy.deepcopy(dict(self.config))
        current_config = normalize_config(current_raw)
        current_rules = current_config.get(mode, {}).get("rules", [])
        if not isinstance(current_rules, list):
            current_rules = []

        next_rules = copy.deepcopy(current_rules)
        for row in rows:
            if not isinstance(row, dict):
                return _api_error("规则行无效。")
            index = _parse_int(row.get("index"), -1)
            if index < 0 or index >= len(next_rules):
                return _api_error(f"规则索引无效：{index}")
            rule = next_rules[index]
            if not isinstance(rule, dict):
                return _api_error(f"规则数据无效：{index}")
            rule["enabled"] = _parse_bool(row.get("enabled"), True)

        next_config = copy.deepcopy(current_raw)
        next_mode = copy.deepcopy(next_config.get(mode) or {})
        if "enabled" in payload:
            next_mode["enabled"] = _parse_bool(payload.get("enabled"), True)
        next_mode["rules"] = next_rules
        next_config[mode] = next_mode
        self._replace_config(next_config)
        self.router.update_config(next_config)
        self.executor.config = self.router.config
        return _api_ok({"config": self.router.config}, "已保存")

    def _save_rules_full(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return _api_error("请求数据无效。")
        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in {"quickaction", "quickcommand"}:
            return _api_error("规则模式无效。")
        rows = payload.get("rules")
        if not isinstance(rows, list):
            return _api_error("规则列表无效。")

        next_rules: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                return _api_error(f"规则行无效：{index + 1}")
            cleaned = _clean_rule(mode, row)
            error = cleaned.pop("__error", "")
            if error:
                return _api_error(f"{error}：第 {index + 1} 条")
            next_rules.append(cleaned)

        current_raw = copy.deepcopy(dict(self.config))
        next_config = copy.deepcopy(current_raw)
        next_mode = copy.deepcopy(next_config.get(mode) or {})
        if "enabled" in payload:
            next_mode["enabled"] = _parse_bool(payload.get("enabled"), True)
        if "admin_only" in payload:
            next_mode["admin_only"] = _parse_bool(payload.get("admin_only"), True)
        if "notice_template" in payload:
            next_mode["notice_template"] = str(payload.get("notice_template") or "")
        if "sync_with_quickaction_channel_scope" in payload and mode == "quickcommand":
            next_mode["sync_with_quickaction_channel_scope"] = _parse_bool(
                payload.get("sync_with_quickaction_channel_scope"), False
            )
        if "channel_scope" in payload and isinstance(payload.get("channel_scope"), dict):
            next_mode["channel_scope"] = _clean_channel_scope(payload.get("channel_scope"))
        if "confirm" in payload:
            next_mode["confirm"] = _clean_confirm(payload.get("confirm"))
        if mode == "quickcommand" and "ssh_mode" in payload:
            next_mode["ssh_mode"] = _clean_ssh_mode(payload.get("ssh_mode"))
        next_mode["rules"] = next_rules
        if (
            mode == "quickcommand"
            and next_mode.get("sync_with_quickaction_channel_scope", False)
        ):
            quickaction = next_config.get("quickaction") or {}
            next_mode["channel_scope"] = _clean_channel_scope(
                quickaction.get("channel_scope") or {}
            )
        next_config[mode] = next_mode
        self._replace_config(next_config)
        self.router.update_config(next_config)
        self.executor.config = self.router.config
        return _api_ok({"config": self.router.config}, "已保存")

    def _save_advanced_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return _api_error("请求数据无效。")

        current_raw = copy.deepcopy(dict(self.config))
        next_config = copy.deepcopy(current_raw)
        next_config.pop("advanced_settings", None)
        next_config["advanced_settings_enabled"] = _parse_bool(
            payload.get("advanced_settings_enabled"),
            bool(next_config.get("advanced_settings_enabled", False)),
        )
        next_config["max_file_size_mb"] = _clean_file_size_limit_mb(
            payload.get("max_file_size_mb"),
            next_config.get("max_file_size_mb", DEFAULT_CONFIG["max_file_size_mb"]),
        )
        for key in (
            "quickaction_rule_confirm_enabled",
            "quickaction_rule_channel_scope_enabled",
            "quickcommand_rule_confirm_enabled",
            "quickcommand_rule_channel_scope_enabled",
        ):
            next_config[key] = False
        next_config["sleep_wake"] = _clean_sleep_wake(
            payload.get("sleep_wake"),
            next_config.get("sleep_wake"),
        )
        if "quickaction_allowed_paths" in payload:
            quickaction = copy.deepcopy(next_config.get("quickaction") or {})
            quickaction["allowed_paths"] = _parse_keywords(
                payload.get("quickaction_allowed_paths")
            )
            next_config["quickaction"] = quickaction

        normalized = normalize_config(next_config)
        normalized["advanced_settings"] = _advanced_settings_schema_value(normalized)
        self._replace_config(normalized)
        self.router.update_config(normalized)
        self.executor.config = self.router.config
        return _api_ok({"config": self.router.config}, "已保存")

    def _replace_config(self, next_config: dict[str, Any]) -> None:
        for ui_key in UI_ONLY_CONFIG_KEYS:
            next_config.pop(ui_key, None)
        if hasattr(self.config, "save_config"):
            self.config.save_config(next_config)
            return
        if isinstance(self.config, dict):
            self.config.clear()
            self.config.update(next_config)
            return
        self.config = next_config

    async def api_screenshot_window(self):
        from quart import request

        payload = await request.get_json(silent=True) or {}
        selector = payload.get("selector") or {}
        result = await asyncio.to_thread(self.executor._screenshot_window, selector)
        data = {
            "ok": result.ok,
            "text": result.text,
            "images": result.images,
        }
        if result.ok:
            return _api_ok(data)
        return _api_error(result.text or "窗口截图失败。", data=data)

    async def api_close_process(self):
        from quart import request

        payload = await request.get_json(silent=True) or {}
        selector = payload.get("selector") or {}
        force = bool(payload.get("force", True))
        include_children = bool(payload.get("include_children", True))
        result = await asyncio.to_thread(
            self.executor._close_process,
            selector,
            force,
            include_children,
        )
        data = {"ok": result.ok, "text": result.text}
        if result.ok:
            return _api_ok(data)
        return _api_error(result.text or "关闭进程失败。", data=data)

    def _load_risk_ack(self) -> dict[str, Any]:
        try:
            if self.risk_ack_file.exists():
                data = json.loads(self.risk_ack_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            logger.warning("LocalAction 读取 risk_ack.json 失败：%s", exc)
        return {}

    def _save_risk_ack(self) -> None:
        try:
            self.risk_ack_file.write_text(
                json.dumps(self.risk_ack, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("LocalAction 写入 risk_ack.json 失败：%s", exc)

    def _settings_risk_notice_acknowledged(self) -> bool:
        return bool(self.risk_ack.get("settings_risk_notice_acknowledged"))

    def _mark_settings_risk_notice_acknowledged(self) -> None:
        self.risk_ack["settings_risk_notice_acknowledged"] = True
        self.risk_ack["settings_risk_notice_acknowledged_at"] = (
            datetime.now(timezone.utc).astimezone().isoformat()
        )
        self._save_risk_ack()

    def _consume_user_risk_notice(
        self, event: AstrMessageEvent, mode: str | None
    ) -> str | None:
        if mode not in {"quickaction", "quickcommand"}:
            return None
        user_key = self._risk_notice_user_key(event)
        sent = self.risk_ack.get("user_risk_notice_sent")
        if not isinstance(sent, dict):
            sent = {}
        if user_key in sent:
            return None
        sent[user_key] = {
            "mode": mode,
            "sent_at": datetime.now(timezone.utc).astimezone().isoformat(),
        }
        self.risk_ack["user_risk_notice_sent"] = sent
        self._save_risk_ack()
        return SESSION_RISK_NOTICE

    def _risk_notice_user_key(self, event: AstrMessageEvent) -> str:
        try:
            platform_name = str(event.get_platform_name() or "unknown")
        except Exception:
            platform_name = "unknown"
        try:
            sender_id = str(event.get_sender_id())
        except Exception:
            sender_id = "unknown"
        return f"{platform_name}:{sender_id}"

    def _load_sleep_state(self) -> SleepState:
        try:
            if self.sleep_state_file.exists():
                return SleepState.from_json(json.loads(self.sleep_state_file.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.warning("LocalAction 读取 sleep_state.json 失败：%s", exc)
        return SleepState()

    def _save_sleep_state_if_needed(self) -> None:
        if not self.router.config.get("advanced_settings_enabled", False):
            return
        try:
            self.sleep_state_file.write_text(
                json.dumps(self.router.sleep_state.to_json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("LocalAction 写入 sleep_state.json 失败：%s", exc)


def _api_ok(data: dict[str, Any] | None = None, message: str | None = None) -> dict[str, Any]:
    return {"status": "ok", "message": message, "data": data or {}}


def _api_error(message: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "error", "message": message, "data": data or {}}


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_file_size_limit_mb(value: Any, default: Any = None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    try:
        limit = float(text)
    except (TypeError, ValueError):
        return _clean_file_size_limit_mb(default, DEFAULT_CONFIG["max_file_size_mb"])
    if limit < 0:
        return None
    return limit


def _file_size_limit_schema_value(value: Any) -> str:
    limit = _clean_file_size_limit_mb(value, None)
    if limit is None:
        return ""
    return f"{limit:g}"


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        text = str(value or "")
        for separator in (",", "，", "、", ";", "；"):
            text = text.replace(separator, "\n")
        items = text.splitlines()
    return [str(item).strip() for item in items if str(item).strip()]


def _pick_local_path(pick_type: str = "file") -> str:
    if os.name != "nt":
        return ""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if pick_type == "directory":
            path = filedialog.askdirectory(parent=root, mustexist=True)
        else:
            path = filedialog.askopenfilename(parent=root)
        root.destroy()
    except Exception as exc:
        logger.warning("LocalAction 路径选择器打开失败：%s", exc)
        return ""
    return str(path or "").strip()


def _parse_match_mode(value: Any, default: str = "contains") -> str:
    mode = str(value or default).strip().lower()
    if mode in {"contains", "exact", "prefix", "regex"}:
        return mode
    return default


ACTION_TYPES = {
    "screenshot_fullscreen",
    "screenshot_window",
    "list_windows",
    "read_file",
    "tail_file",
    "send_file",
    "run_command",
    "run_predefined_command",
    "close_process",
}


def _clean_rule(mode: str, row: dict[str, Any]) -> dict[str, Any]:
    name_key = rule_name_key(mode)
    fallback_name = _first_keyword(row.get("trigger_keywords"))
    default_name = "New QuickAction" if mode == "quickaction" else "New QuickCommand"
    action_name = str(
        row.get(name_key) or row.get("name") or fallback_name or default_name
    ).strip()
    keywords = _parse_keywords(row.get("trigger_keywords"))
    if not action_name:
        return {"__error": "规则名称不能为空"}

    action = _clean_action(row.get("action"), mode=mode)
    if "__error" in action:
        return action

    rule = copy.deepcopy(row)
    rule["__template_key"] = "rule"
    rule["enabled"] = _parse_bool(row.get("enabled"), True)
    rule[name_key] = action_name
    rule["name"] = action_name
    rule["trigger_keywords"] = keywords
    rule["match_mode"] = _parse_match_mode(row.get("match_mode"))
    rule["use_channel_scope"] = _parse_bool(row.get("use_channel_scope"), False)
    rule["action"] = action

    if "channel_scope" in rule and isinstance(rule["channel_scope"], dict):
        rule["channel_scope"] = _clean_channel_scope(rule["channel_scope"])
    if "confirm" in rule and isinstance(rule["confirm"], dict):
        rule["confirm"] = _clean_confirm(rule["confirm"])
    for key in ("__allow_rule_confirm", "__allow_rule_channel_scope"):
        if key in rule:
            rule[key] = bool(rule[key])
    return rule


def _clean_action(value: Any, *, mode: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"type": "run_command", "shell": "pwsh", "command": "", "timeout": 10} if mode == "quickcommand" else {"type": "screenshot_fullscreen"}
    source = copy.deepcopy(value)
    action_type = str(source.get("type") or "").strip()
    if not action_type:
        return {"type": ""}
    if mode == "quickcommand" and action_type != "run_command":
        return {"__error": "QuickCommand 只支持执行命令"}
    if action_type not in ACTION_TYPES:
        return {"__error": f"不支持的动作类型：{action_type}"}

    action: dict[str, Any] = {"type": action_type}
    if action_type in {"screenshot_window", "list_windows", "close_process"}:
        selector = source.get("selector")
        action["selector"] = selector if isinstance(selector, dict) else {}
    if action_type in {"read_file", "tail_file", "send_file"}:
        path = str(source.get("path") or "").strip()
        if path:
            action["path"] = path
    if action_type == "tail_file":
        action["lines"] = max(1, _parse_int(source.get("lines"), 100))
    if action_type == "list_windows":
        action["limit"] = max(1, _parse_int(source.get("limit"), 20))
    if action_type == "run_command":
        action["shell"] = str(source.get("shell") or "pwsh").strip() or "pwsh"
        action["command"] = str(source.get("command") or "").strip()
        action["timeout"] = max(1, _parse_int(source.get("timeout"), 10))
    if action_type == "run_predefined_command":
        command_id = str(source.get("command_id") or "").strip()
        action["command_id"] = command_id
    if action_type == "close_process":
        action["force"] = _parse_bool(source.get("force"), True)
        action["include_children"] = _parse_bool(source.get("include_children"), True)
    return action


def _clean_channel_scope(value: dict[str, Any]) -> dict[str, Any]:
    mode = str(value.get("mode") or "global").strip().lower()
    if mode not in {"global", "include", "exclude", "custom"}:
        mode = "global"
    return {
        "mode": mode,
        "include_channels": _parse_keywords(value.get("include_channels")),
        "exclude_channels": _parse_keywords(value.get("exclude_channels")),
        "platform_names": _parse_keywords(value.get("platform_names")),
    }


def _clean_confirm(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "enabled": _parse_bool(value.get("enabled"), False),
        "confirm_text": str(value.get("confirm_text") or "确认").strip() or "确认",
        "timeout_seconds": max(1, _parse_int(value.get("timeout_seconds"), 30)),
    }


def _clean_ssh_mode(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    default = DEFAULT_CONFIG["quickcommand"]["ssh_mode"]
    return {
        "enabled": _parse_bool(value.get("enabled"), bool(default["enabled"])),
        "trigger_keywords": _parse_keywords(
            value.get("trigger_keywords", default["trigger_keywords"])
        ),
        "exit_keywords": _parse_keywords(
            value.get("exit_keywords", default["exit_keywords"])
        ),
        "match_mode": normalize_match_mode(value.get("match_mode"), default="exact"),
        "shell": str(value.get("shell") or default["shell"]).strip()
        or str(default["shell"]),
        "timeout": max(1, _parse_int(value.get("timeout"), int(default["timeout"]))),
    }


def _migrate_quickcommand_shell_session_timeout(config: dict[str, Any]) -> bool:
    quickcommand = config.get("quickcommand")
    if not isinstance(quickcommand, dict):
        return False
    ssh_mode = quickcommand.get("ssh_mode")
    if not isinstance(ssh_mode, dict):
        return False
    if _parse_int(ssh_mode.get("timeout"), 0) != 10:
        return False
    ssh_mode["timeout"] = int(DEFAULT_CONFIG["quickcommand"]["ssh_mode"]["timeout"])
    return True


def _clean_sleep_wake(value: Any, current: Any = None) -> dict[str, Any]:
    source = copy.deepcopy(current) if isinstance(current, dict) else {}
    if isinstance(value, dict):
        source.update(copy.deepcopy(value))
    default = DEFAULT_CONFIG["sleep_wake"]
    def keywords(key: str) -> list[str]:
        if key not in source:
            return list(default[key])
        return _parse_keywords(source.get(key))

    return {
        "enabled": _parse_bool(source.get("enabled"), bool(default["enabled"])),
        "sleep_match_mode": _parse_match_mode(
            source.get("sleep_match_mode"), str(default["sleep_match_mode"])
        ),
        "sleep_keywords": keywords("sleep_keywords"),
        "permanent_sleep_keywords": keywords("permanent_sleep_keywords"),
        "wake_keywords": keywords("wake_keywords"),
        "wake_all_keywords": keywords("wake_all_keywords"),
        "status_keywords": keywords("status_keywords"),
        "default_sleep_seconds": max(
            1,
            _parse_int(
                source.get("default_sleep_seconds"),
                int(default["default_sleep_seconds"]),
            ),
        ),
        "persist_sleep_state": True,
        "allow_global_sleep": True,
        "allow_mode_sleep": False,
        "allow_rule_sleep": False,
        "admin_only": _parse_bool(source.get("admin_only"), bool(default["admin_only"])),
        "notice": copy.deepcopy(source.get("notice") or default.get("notice", {})),
    }


def _advanced_settings_schema_value(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": _parse_bool(config.get("advanced_settings_enabled"), False),
        "max_file_size_mb": _file_size_limit_schema_value(config.get("max_file_size_mb")),
        "quickaction_rule_confirm_enabled": False,
        "quickaction_rule_channel_scope_enabled": False,
        "quickcommand_rule_confirm_enabled": False,
        "quickcommand_rule_channel_scope_enabled": False,
        "sleep_wake": _clean_sleep_wake(config.get("sleep_wake")),
    }


def _first_keyword(value: Any) -> str:
    keywords = _parse_keywords(value)
    return keywords[0] if keywords else ""


def _initial_channel_scope_defaults(
    raw_config: dict[str, Any],
    normalized_config: dict[str, Any],
    platform_scope: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mode": "include",
        "active_channels": list(platform_scope.get("active_channels") or []),
        "apply_modes": {
            mode: _channel_scope_is_initial(raw_config, normalized_config, mode)
            for mode in ("quickaction", "quickcommand")
        },
    }


def _channel_scope_is_initial(
    raw_config: dict[str, Any],
    normalized_config: dict[str, Any],
    mode: str,
) -> bool:
    raw_mode = raw_config.get(mode)
    if not isinstance(raw_mode, dict):
        return True
    raw_scope = raw_mode.get("channel_scope")
    if not isinstance(raw_scope, dict):
        return True
    default_scope = DEFAULT_CONFIG.get(mode, {}).get("channel_scope")
    return normalize_channel_scope(raw_scope) == normalize_channel_scope(default_scope)
