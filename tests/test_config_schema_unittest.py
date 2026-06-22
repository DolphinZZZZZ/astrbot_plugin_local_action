import json
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "astrbot_plugin_local_action"


class ConfigSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

    def _walk_schema_items(self, items, prefix=""):
        for key, meta in items.items():
            if not isinstance(meta, dict) or "type" not in meta:
                continue

            path = f"{prefix}.{key}" if prefix else key
            yield path, meta

            if meta["type"] == "object":
                yield from self._walk_schema_items(meta.get("items", {}), path)
            elif meta["type"] == "template_list":
                for template_key, template in meta.get("templates", {}).items():
                    yield from self._walk_schema_items(
                        template.get("items", {}),
                        f"{path}.templates.{template_key}",
                    )

    def _assert_schema_value_matches_type(self, value, expected_type, path):
        type_checks = {
            "bool": lambda val: isinstance(val, bool),
            "int": lambda val: isinstance(val, int) and not isinstance(val, bool),
            "float": lambda val: isinstance(val, float),
            "string": lambda val: isinstance(val, str),
            "text": lambda val: isinstance(val, str),
            "list": lambda val: isinstance(val, list),
            "template_list": lambda val: isinstance(val, list),
            "object": lambda val: isinstance(val, dict),
        }

        self.assertIn(expected_type, type_checks, f"{path} uses unknown schema type")
        self.assertTrue(
            type_checks[expected_type](value),
            f"{path} default type mismatch: expected {expected_type}, got {type(value).__name__}",
        )

    def test_schema_uses_only_astrbot_native_types(self):
        native_types = {
            "bool",
            "int",
            "float",
            "string",
            "text",
            "list",
            "template_list",
            "object",
        }

        for path, meta in self._walk_schema_items(self.schema):
            self.assertIn(meta["type"], native_types, f"{path} uses unsupported type")

    def test_schema_defaults_match_declared_types(self):
        for path, meta in self._walk_schema_items(self.schema):
            if "default" in meta:
                self._assert_schema_value_matches_type(meta["default"], meta["type"], path)

    def test_plugin_enabled_setting_is_not_rendered(self):
        self.assertNotIn("enabled", self.schema)
        descriptions = json.dumps(self.schema, ensure_ascii=False)
        self.assertNotIn("启用 LocalAction", descriptions)

    def test_settings_entry_is_not_rendered_above_quickaction(self):
        keys = list(self.schema)

        self.assertEqual(keys[1], "quickaction")
        self.assertNotIn("__localaction_settings_entry", self.schema)
        descriptions = json.dumps(self.schema, ensure_ascii=False)
        self.assertNotIn("独立设置页入口", descriptions)
        self.assertNotIn("打开 LocalAction 独立设置页", descriptions)

    def test_plugin_ui_notice_is_rendered_above_quickaction(self):
        keys = list(self.schema)
        notice = self.schema["__localaction_plugin_ui_notice"]

        self.assertEqual(keys[0], "__localaction_plugin_ui_notice")
        self.assertEqual(notice["type"], "object")
        self.assertEqual(notice["description"], "更多设置请进入插件UI界面查看")
        self.assertIn("插件页面", notice["hint"])
        self.assertTrue(notice["obvious_hint"])
        self.assertEqual(notice["items"], {})

    def test_quickaction_and_quickcommand_are_top_level_parent_switches(self):
        keys = list(self.schema)

        self.assertLess(keys.index("quickaction"), keys.index("quickcommand"))
        self.assertLess(keys.index("quickcommand"), keys.index("advanced_settings"))
        self.assertIn("quickaction", self.schema)
        self.assertIn("quickcommand", self.schema)
        self.assertNotIn("quickaction", self.schema["advanced_settings"]["items"])
        self.assertNotIn("quickcommand", self.schema["advanced_settings"]["items"])
        self.assertNotIn("quickshot", json.dumps(self.schema, ensure_ascii=False))
        self.assertEqual(self.schema["quickaction"]["description"], "启用 QuickAction")
        self.assertEqual(self.schema["quickcommand"]["description"], "启用 QuickCommand")
        self.assertNotIn("invisible", self.schema["quickaction"]["items"]["enabled"])
        self.assertNotIn("invisible", self.schema["quickcommand"]["items"]["enabled"])
        self.assertEqual(
            self.schema["quickaction"]["items"]["rules"].get("default")[0]["action_name"],
            "屏幕截图",
        )
        descriptions = json.dumps(self.schema, ensure_ascii=False)
        self.assertIn("QuickAction", descriptions)
        self.assertNotIn("QuickShot", descriptions)
        self.assertNotIn("hint", self.schema["quickaction"])

    def test_flat_runtime_advanced_fields_have_native_schema_metadata(self):
        flat_items = {
            "advanced_settings_enabled": "启用高级设置（兼容字段）",
            "max_file_size_mb": "文件大小上限（兼容字段）",
            "quickaction_rule_confirm_enabled": "QuickAction 规则独立二次确认（本版未开放）",
            "quickaction_rule_channel_scope_enabled": "QuickAction 规则独立渠道范围（本版未开放）",
            "quickcommand_rule_confirm_enabled": "QuickCommand 规则独立二次确认（本版未开放）",
            "quickcommand_rule_channel_scope_enabled": "QuickCommand 规则独立渠道范围（本版未开放）",
            "sleep_wake": "休眠/唤醒运行时配置（兼容字段）",
        }

        for key, description in flat_items.items():
            self.assertIn(key, self.schema)
            self.assertEqual(self.schema[key]["description"], description)
            self.assertIn("hint", self.schema[key])

        self.assertEqual(self.schema["max_file_size_mb"]["type"], "string")
        self.assertEqual(self.schema["max_file_size_mb"]["default"], "50")
        self.assertIn("兼容字段", self.schema["max_file_size_mb"]["description"])
        self.assertFalse(self.schema["advanced_settings_enabled"]["default"])
        for key in flat_items:
            self.assertTrue(self.schema[key]["invisible"])

    def test_advanced_settings_file_size_limit_has_chinese_label_and_hint(self):
        file_size = self.schema["advanced_settings"]["items"]["max_file_size_mb"]

        self.assertEqual(file_size["type"], "string")
        self.assertEqual(file_size["default"], "50")
        self.assertEqual(file_size["description"], "文件大小上限（MB）")
        self.assertIn("read_file", file_size["hint"])
        self.assertIn("0 表示禁止文件动作", file_size["hint"])
        self.assertEqual(file_size["condition"], {"enabled": True})
        self.assertNotIn("invisible", file_size)

    def test_basic_settings_are_not_rendered_above_quickaction(self):
        for legacy_key in (
            "basic_trigger_keywords",
            "basic_admin_only",
            "notice_template",
            "basic_confirm_text",
        ):
            self.assertNotIn(legacy_key, self.schema)

        self.assertIn("notice_template", self.schema["quickaction"]["items"])
        self.assertIn("notice_template", self.schema["quickcommand"]["items"])
        self.assertTrue(self.schema["quickaction"]["items"]["notice_template"]["invisible"])
        self.assertTrue(self.schema["quickcommand"]["items"]["notice_template"]["invisible"])
        self.assertIn(
            "{action_name}",
            self.schema["quickaction"]["items"]["notice_template"]["default"],
        )
        self.assertIn(
            "{command_name}",
            self.schema["quickcommand"]["items"]["notice_template"]["default"],
        )
        self.assertNotIn(
            "{action_name}",
            self.schema["quickcommand"]["items"]["notice_template"]["default"],
        )
        descriptions = json.dumps(self.schema, ensure_ascii=False)
        self.assertNotIn("默认提示语模板", descriptions)
        for section in ("quickaction", "quickcommand"):
            confirm = self.schema[section]["items"]["confirm"]
            self.assertTrue(confirm["invisible"])
            self.assertIn("兼容字段", confirm["description"])
            for item in confirm["items"].values():
                self.assertTrue(item["invisible"])
        self.assertNotIn("QuickAction 二次确认", descriptions)
        self.assertNotIn("QuickCommand 二次确认", descriptions)

    def test_rule_lists_are_directly_below_hidden_mode_settings(self):
        self.assertEqual(
            list(self.schema["quickaction"]["items"])[
                list(self.schema["quickaction"]["items"]).index("confirm") + 1
            ],
            "rules",
        )
        self.assertEqual(
            list(self.schema["quickcommand"]["items"])[
                list(self.schema["quickcommand"]["items"]).index("commands") + 1
            ],
            "rules",
        )

        quickaction_keys = list(self.schema["quickaction"]["items"])
        quickcommand_keys = list(self.schema["quickcommand"]["items"])
        self.assertLess(quickaction_keys.index("rules"), quickaction_keys.index("channel_scope"))
        self.assertLess(
            quickcommand_keys.index("rules"),
            quickcommand_keys.index("sync_with_quickaction_channel_scope"),
        )
        self.assertLess(quickcommand_keys.index("rules"), quickcommand_keys.index("channel_scope"))

    def test_quickaction_and_quickcommand_children_are_hidden_until_enabled(self):
        for section in ("quickaction", "quickcommand"):
            section_items = self.schema[section]["items"]

            for key, meta in section_items.items():
                if key == "enabled":
                    self.assertNotIn("condition", meta)
                elif section == "quickcommand" and key == "channel_scope":
                    self.assertEqual(
                        meta.get("condition"),
                        {"enabled": True, "sync_with_quickaction_channel_scope": False},
                    )
                else:
                    self.assertEqual(meta.get("condition"), {"enabled": True})

    def test_advanced_settings_children_are_hidden_until_enabled(self):
        advanced_items = self.schema["advanced_settings"]["items"]

        for key, meta in advanced_items.items():
            if key == "enabled":
                self.assertNotIn("condition", meta)
            else:
                self.assertEqual(meta.get("condition"), {"enabled": True})

    def test_file_size_limit_is_hidden_from_native_config_schema(self):
        self.assertNotIn("max_file_size_mb", self.schema["quickaction"]["items"])
        self.assertIn("max_file_size_mb", self.schema["advanced_settings"]["items"])
        self.assertIn("max_file_size_mb", self.schema)

    def test_new_ui_settings_are_hidden_from_native_config_schema(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        for section in ("quickaction", "quickcommand"):
            self.assertTrue(self.schema[section]["items"]["admin_only"]["invisible"])
            self.assertNotIn("invisible", self.schema[section]["items"]["enabled"])
            self.assertNotIn("invisible", self.schema[section]["items"]["rules"])
            self.assertTrue(self.schema[section]["items"]["channel_scope"]["invisible"])
        self.assertTrue(self.schema["quickaction"]["items"]["allowed_paths"]["invisible"])
        self.assertTrue(
            self.schema["quickcommand"]["items"][
                "sync_with_quickaction_channel_scope"
            ]["invisible"]
        )
        self.assertNotIn("invisible", self.schema["advanced_settings"])
        self.assertNotIn("invisible", self.schema["advanced_settings"]["items"]["enabled"])
        self.assertNotIn(
            "invisible",
            self.schema["advanced_settings"]["items"]["sleep_wake"],
        )

        self.assertIn("els.modeEnabled.checked = enabled", html)
        self.assertIn("state.config[mode].rules =", html)
        self.assertIn("advanced.advanced_settings_enabled = els.modeEnabled.checked", html)
        self.assertIn('checkField("仅管理员可用"', html)
        self.assertIn('pathPickerField("文件动作白名单路径"', html)
        self.assertIn(
            'channelScopeField(`${mode === "quickcommand" ? "QuickCommand" : "QuickAction"} 渠道范围`',
            html,
        )
        self.assertIn('checkField("与 QuickAction 渠道范围保持一致"', html)

    def test_confirm_and_command_details_are_hidden_from_native_config_schema(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        for section in ("quickaction", "quickcommand"):
            confirm = self.schema[section]["items"]["rules"]["templates"]["rule"][
                "items"
            ]["confirm"]
            self.assertTrue(confirm["invisible"])
            for item in confirm["items"].values():
                self.assertTrue(item["invisible"])
            mode_confirm = self.schema[section]["items"]["confirm"]
            self.assertTrue(mode_confirm["invisible"])
            for item in mode_confirm["items"].values():
                self.assertTrue(item["invisible"])

        command = self.schema["quickcommand"]["items"]["rules"]["templates"]["rule"][
            "items"
        ]["action"]["items"]["command"]
        self.assertTrue(command["invisible"])
        commands = self.schema["quickcommand"]["items"]["commands"]
        self.assertTrue(commands["invisible"])
        self.assertEqual(commands["default"], {})
        self.assertEqual(commands["items"], {})

        self.assertIn('confirmSettingsField(confirm, mode)', html)
        self.assertIn('textAreaField("执行命令"', html)

    def test_rule_advanced_feature_switches_are_hidden_in_advanced_settings(self):
        advanced_items = self.schema["advanced_settings"]["items"]

        for key, description in (
            (
                "quickaction_rule_confirm_enabled",
                "允许 QuickAction 规则独立二次确认",
            ),
            (
                "quickaction_rule_channel_scope_enabled",
                "允许 QuickAction 规则单独渠道范围",
            ),
            (
                "quickcommand_rule_confirm_enabled",
                "允许 QuickCommand 规则独立二次确认",
            ),
            (
                "quickcommand_rule_channel_scope_enabled",
                "允许 QuickCommand 规则单独渠道范围",
            ),
        ):
            self.assertIn(key, advanced_items)
            self.assertEqual(advanced_items[key]["type"], "bool")
            self.assertFalse(advanced_items[key]["default"])
            self.assertEqual(advanced_items[key]["description"], description)
            self.assertEqual(advanced_items[key]["condition"], {"enabled": True})
            self.assertTrue(advanced_items[key]["invisible"])

    def test_independent_sleep_settings_are_hidden_in_advanced_settings(self):
        sleep_items = self.schema["advanced_settings"]["items"]["sleep_wake"]["items"]

        self.assertTrue(sleep_items["wake_all_keywords"]["invisible"])
        self.assertEqual(sleep_items["sleep_match_mode"]["default"], "exact")
        self.assertEqual(
            sleep_items["sleep_match_mode"]["options"],
            ["contains", "exact", "prefix", "regex"],
        )
        self.assertTrue(sleep_items["sleep_match_mode"]["invisible"])
        self.assertEqual(sleep_items["status_keywords"]["default"], ["休眠状态"])
        self.assertTrue(sleep_items["persist_sleep_state"]["default"])
        self.assertTrue(sleep_items["persist_sleep_state"]["invisible"])
        self.assertTrue(sleep_items["allow_global_sleep"]["default"])
        self.assertTrue(sleep_items["allow_global_sleep"]["invisible"])
        self.assertFalse(sleep_items["allow_mode_sleep"]["default"])
        self.assertTrue(sleep_items["allow_mode_sleep"]["invisible"])
        self.assertFalse(sleep_items["allow_rule_sleep"]["default"])
        self.assertTrue(sleep_items["allow_rule_sleep"]["invisible"])
        self.assertEqual(sleep_items["default_sleep_seconds"]["default"], 3600)
        self.assertTrue(sleep_items["notice"]["invisible"])
        self.assertIn("提示模板", sleep_items["notice"]["hint"])

    def test_channel_scope_fields_are_conditionally_visible(self):
        channel_scopes = [
            self.schema["quickaction"]["items"]["channel_scope"],
            self.schema["quickcommand"]["items"]["channel_scope"],
        ]

        for channel_scope in channel_scopes:
            items = channel_scope["items"]
            self.assertNotIn("channels", items)
            self.assertEqual(items["mode"]["labels"], ["全局", "包含", "排除", "自定义平台名"])
            self.assertEqual(items["include_channels"]["default"], [])
            self.assertEqual(items["include_channels"]["options"], ["qq", "web", "client", "other"])
            self.assertEqual(items["include_channels"]["labels"], ["QQ", "网页", "客户端", "其他"])
            self.assertEqual(items["include_channels"]["condition"], {"mode": "include"})
            self.assertEqual(items["exclude_channels"]["default"], [])
            self.assertEqual(items["exclude_channels"]["labels"], ["QQ", "网页", "客户端", "其他"])
            self.assertEqual(items["exclude_channels"]["condition"], {"mode": "exclude"})
            self.assertEqual(items["platform_names"]["condition"], {"mode": "custom"})

        self.assertEqual(
            self.schema["quickcommand"]["items"]["channel_scope"]["condition"],
            {"enabled": True, "sync_with_quickaction_channel_scope": False},
        )

    def test_quickcommand_has_sync_switch_but_no_copy_switch(self):
        quickcommand_items = self.schema["quickcommand"]["items"]

        self.assertIn("sync_with_quickaction_channel_scope", quickcommand_items)
        sync_meta = quickcommand_items["sync_with_quickaction_channel_scope"]
        self.assertEqual(sync_meta["type"], "bool")
        self.assertEqual(sync_meta["default"], True)
        self.assertEqual(sync_meta["condition"], {"enabled": True})
        self.assertIn("QuickAction", sync_meta["description"])
        self.assertIn("隐藏 QuickCommand 渠道范围设置", sync_meta["hint"])

        for key in quickcommand_items:
            self.assertNotIn("copy", key.lower())
            self.assertNotIn("quickation", key.lower())

    def test_quickcommand_shell_session_mode_is_hidden_compat_field(self):
        ssh_mode = self.schema["quickcommand"]["items"]["ssh_mode"]

        self.assertTrue(ssh_mode["invisible"])
        self.assertEqual(ssh_mode["description"], "Shell 会话模式（兼容字段）")
        self.assertEqual(ssh_mode["items"]["timeout"]["default"], 1000)
        self.assertEqual(ssh_mode["items"]["trigger_keywords"]["default"], ["ssh"])
        self.assertEqual(ssh_mode["items"]["exit_keywords"]["default"], ["exit", "退出"])

    def test_quickcommand_has_no_default_predefined_commands(self):
        quickcommand_items = self.schema["quickcommand"]["items"]

        self.assertEqual(quickcommand_items["rules"]["default"], [])
        self.assertTrue(quickcommand_items["commands"]["invisible"])
        self.assertEqual(quickcommand_items["commands"]["default"], {})
        self.assertEqual(quickcommand_items["commands"]["items"], {})
        serialized = json.dumps(self.schema["quickcommand"], ensure_ascii=False)
        self.assertNotIn("close_weixin", serialized)
        self.assertNotIn("restart_codex", serialized)

    def test_rule_lists_use_template_editor_and_expose_columns(self):
        expected_name_labels = {
            "quickaction": ("action_name", "动作名称"),
            "quickcommand": ("command_name", "命令名称"),
        }
        for section in ("quickaction", "quickcommand"):
            rules = self.schema[section]["items"]["rules"]
            self.assertEqual(rules["type"], "template_list")
            self.assertNotIn("item_type", rules)
            if section == "quickaction":
                self.assertTrue(rules["default"][0]["enabled"])
                self.assertEqual(rules["default"][0]["__template_key"], "rule")
                self.assertFalse(rules["default"][0]["use_channel_scope"])
            else:
                self.assertEqual(rules["default"], [])
            self.assertIn("规则列表", rules["description"])

            items = rules["templates"]["rule"]["items"]
            name_key, name_label = expected_name_labels[section]
            self.assertTrue(rules["templates"]["rule"]["hide_hint_in_list"])
            self.assertEqual(rules["templates"]["rule"]["display_item"], name_key)
            item_keys = list(items)
            self.assertEqual(item_keys.index("enabled"), item_keys.index(name_key) + 1)
            self.assertEqual(items["enabled"]["description"], "启用状态")
            self.assertEqual(items["enabled"]["default"], True)
            self.assertIn(name_key, items)
            self.assertNotIn("name", items)
            self.assertEqual(items[name_key]["description"], name_label)
            self.assertEqual(items["trigger_keywords"]["description"], "触发关键词")
            self.assertEqual(items["match_mode"]["description"], "匹配模式")
            self.assertEqual(
                items["match_mode"]["options"],
                ["contains", "exact", "prefix", "regex"],
            )
            self.assertEqual(
                items["match_mode"]["labels"],
                ["包含", "完全匹配", "前缀匹配", "正则"],
            )
            self.assertEqual(items["use_channel_scope"]["type"], "bool")
            self.assertFalse(items["use_channel_scope"]["default"])
            self.assertEqual(
                items["use_channel_scope"]["description"],
                "单独渠道范围",
            )
            self.assertEqual(
                items["use_channel_scope"]["condition"],
                {"__allow_rule_channel_scope": True},
            )
            self.assertTrue(items["use_channel_scope"]["invisible"])
            self.assertEqual(
                items["channel_scope"]["condition"],
                {"__allow_rule_channel_scope": True, "use_channel_scope": True},
            )
            self.assertTrue(items["channel_scope"]["invisible"])
            action = items["action"]
            self.assertEqual(action["type"], "object")
            self.assertEqual(list(action["items"])[0], "type")
            self.assertEqual(action["items"]["type"]["description"], "动作类型")
            if section == "quickaction":
                self.assertEqual(
                    action["items"]["type"]["options"],
                    [
                        "screenshot_fullscreen",
                        "screenshot_window",
                        "list_windows",
                        "read_file",
                        "tail_file",
                        "send_file",
                        "close_process",
                    ],
                )
                self.assertNotIn("command_id", action["items"])
                self.assertEqual(action["items"]["selector"]["type"], "object")
                self.assertEqual(action["items"]["selector"]["default"], {})
                self.assertEqual(action["items"]["selector"]["items"], {})
            else:
                self.assertEqual(rules["default"], [])
                self.assertEqual(action["items"]["type"]["default"], "run_command")
                self.assertEqual(action["items"]["type"]["options"], ["run_command"])
                self.assertEqual(action["items"]["type"]["labels"], ["执行命令"])
                self.assertEqual(action["items"]["shell"]["type"], "string")
                self.assertEqual(action["items"]["command"]["type"], "text")
                self.assertEqual(action["items"]["timeout"]["type"], "int")
                self.assertNotIn("command_id", action["items"])

    def test_rule_advanced_fields_are_gated(self):
        for section in ("quickaction", "quickcommand"):
            items = self.schema[section]["items"]["rules"]["templates"]["rule"]["items"]

            self.assertEqual(
                items["confirm"]["condition"],
                {"__allow_rule_confirm": True},
            )
            self.assertTrue(items["confirm"]["invisible"])
            self.assertTrue(items["__allow_rule_confirm"]["invisible"])
            self.assertTrue(items["__allow_rule_channel_scope"]["invisible"])
            default_rules = self.schema[section]["items"]["rules"]["default"]
            if default_rules:
                self.assertFalse(default_rules[0]["__allow_rule_confirm"])
                self.assertFalse(default_rules[0]["__allow_rule_channel_scope"])

if __name__ == "__main__":
    unittest.main()
