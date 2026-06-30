from __future__ import annotations

DEFAULT_NOTICE_TEMPLATE = "已由本地插件 LocalAction 执行动作：{action_name}，未调用大模型。"
DEFAULT_QUICKCOMMAND_NOTICE_TEMPLATE = (
    "已由本地插件 LocalAction 执行命令：{command_name}，未调用大模型。"
)

DEFAULT_CONFIG = {
    "advanced_settings_enabled": False,
    "max_file_size_mb": 50,
    "quickaction_rule_confirm_enabled": False,
    "quickaction_rule_channel_scope_enabled": False,
    "quickcommand_rule_confirm_enabled": False,
    "quickcommand_rule_channel_scope_enabled": False,
    "sleep_wake": {
        "enabled": True,
        "sleep_match_mode": "exact",
        "sleep_keywords": ["休眠"],
        "permanent_sleep_keywords": ["永久休眠"],
        "wake_keywords": ["唤醒"],
        "wake_all_keywords": ["全部唤醒", "唤醒全部"],
        "status_keywords": ["休眠状态"],
        "default_sleep_seconds": 3600,
        "persist_sleep_state": True,
        "allow_global_sleep": True,
        "allow_mode_sleep": False,
        "allow_rule_sleep": False,
        "admin_only": True,
        "notice": {
            "sleep_global": "LocalAction 已休眠全部 Local Action 拦截 {seconds} 秒。",
            "sleep_global_forever": "LocalAction 已永久休眠全部 Local Action 拦截，直到手动唤醒。",
            "wake_global": "LocalAction 已唤醒全部 Local Action 拦截。",
            "sleep_target": "LocalAction 已休眠：{target_name}，持续 {seconds} 秒。",
            "sleep_target_forever": "LocalAction 已永久休眠：{target_name}，直到手动唤醒。",
            "wake_target": "LocalAction 已唤醒：{target_name}。",
            "wake_all": "LocalAction 已清除全部休眠状态，所有 Local Action 拦截恢复运行。",
            "not_found": "LocalAction 未找到可休眠/唤醒的目标：{target_name}。",
            "status_title": "LocalAction 当前状态：",
        },
    },
    "quickaction": {
        "enabled": True,
        "admin_only": True,
        "notice_template": DEFAULT_NOTICE_TEMPLATE,
        "channel_scope": {
            "mode": "global",
            "include_channels": [],
            "exclude_channels": [],
            "platform_names": [],
        },
        "confirm": {
            "enabled": False,
            "confirm_text": "确认",
            "timeout_seconds": 30,
        },
        "allowed_paths": [],
        "rules": [
            {
                "__template_key": "rule",
                "__allow_rule_confirm": False,
                "__allow_rule_channel_scope": False,
                "enabled": True,
                "action_name": "屏幕截图",
                "trigger_keywords": ["屏幕截图"],
                "match_mode": "contains",
                "use_channel_scope": False,
                "channel_scope": {
                    "mode": "global",
                    "include_channels": [],
                    "exclude_channels": [],
                    "platform_names": [],
                },
                "action": {"type": "screenshot_fullscreen"},
            },
        ],
    },
    "quickcommand": {
        "enabled": False,
        "admin_only": True,
        "notice_template": DEFAULT_QUICKCOMMAND_NOTICE_TEMPLATE,
        "sync_with_quickaction_channel_scope": True,
        "channel_scope": {
            "mode": "include",
            "include_channels": [],
            "exclude_channels": [],
            "platform_names": [],
        },
        "confirm": {
            "enabled": True,
            "confirm_text": "确认",
            "timeout_seconds": 30,
        },
        "commands": {},
        "ssh_mode": {
            "enabled": False,
            "trigger_keywords": ["ssh"],
            "exit_keywords": ["exit", "退出"],
            "match_mode": "exact",
            "shell": "pwsh",
            "timeout": 1000,
        },
        "rules": [],
    },
}
