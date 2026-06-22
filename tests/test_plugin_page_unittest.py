from pathlib import Path
import unittest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "astrbot_plugin_local_action"
METADATA_YAML = PROJECT_ROOT / "astrbot_plugin_local_action" / "metadata.yaml"


class PluginPageTests(unittest.TestCase):
    def test_settings_plugin_page_is_exposed_by_pages_directory(self):
        metadata = yaml.safe_load(METADATA_YAML.read_text(encoding="utf-8"))
        page_names = [page["name"] for page in metadata.get("pages", [])]

        self.assertEqual(page_names, [])
        self.assertTrue((PLUGIN_ROOT / "pages" / "settings" / "index.html").exists())

    def test_settings_page_uses_plugin_bridge_and_full_rules_api(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('/api/plugin/page/bridge-sdk.js', html)
        self.assertIn('apiGet("config")', html)
        self.assertIn('apiPost("rules/full"', html)
        self.assertIn('apiPost("rules/enabled"', html)
        self.assertIn('apiPost("settings/advanced"', html)
        self.assertIn('apiPost("settings/risk-ack"', html)
        self.assertIn('id="modeSettings"', html)
        self.assertIn("function renderModeSettings()", html)
        self.assertIn('textField("执行成功返回提示"', html)
        self.assertIn('checkField("启用二次确认"', html)
        self.assertIn('checkField("仅管理员可用"', html)
        self.assertIn('textField("确认语"', html)
        self.assertIn('numberField("确认超时秒数"', html)
        self.assertIn("function renderConfirmDetailFields(row, confirm, mode)", html)
        self.assertIn("renderConfirmDetailFields(row, confirm, mode);", html)
        self.assertIn("notice_template: modeNoticeTemplate(mode)", html)
        self.assertIn("admin_only: modeAdminOnly(mode)", html)
        self.assertIn("channel_scope: cleanClientChannelScope(modeChannelScope(mode))", html)
        self.assertIn("sync_with_quickaction_channel_scope", html)
        self.assertIn("confirm: cleanClientConfirm(modeConfirm(mode))", html)
        self.assertIn("function modeNoticeTemplate", html)
        self.assertIn("function modeConfirm", html)
        self.assertIn("function modeAdminOnly", html)
        self.assertIn("function modeSyncWithQuickActionChannelScope", html)
        self.assertIn("function modeSshMode", html)
        self.assertIn("function cleanClientSshMode", html)
        self.assertIn("conf.sync_with_quickaction_channel_scope = true;", html)
        self.assertIn("function modeChannelScope", html)
        self.assertIn("function channelScopeField", html)
        self.assertIn("function cleanClientConfirm", html)
        self.assertIn("function cleanClientChannelScope", html)
        self.assertIn("enabledStatePayload", html)
        self.assertIn("localaction:settings:expanded:v1", html)
        self.assertIn("screenshot_fullscreen", html)
        self.assertIn("run_command", html)
        self.assertNotIn("run_predefined_command", html)
        self.assertIn("notifyLayoutChanged();", html)

    def test_settings_page_hides_mode_actions_when_mode_is_disabled(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("[hidden] { display: none !important; }", html)
        self.assertIn('els.rules.hidden = state.mode === "advanced" || !enabled;', html)
        self.assertIn('els.rules.innerHTML = "";', html)
        self.assertIn("els.addRuleBtn.hidden = isAdvanced || !enabled;", html)
        self.assertIn("modeConfig().enabled = els.modeEnabled.checked;\n      render();", html)

    def test_new_rules_default_to_contains_match_mode(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        add_rule_block = html[html.index("function addRule()") : html.index("function deleteRule")]
        self.assertIn('match_mode: "contains"', add_rule_block)
        self.assertNotIn('match_mode: "exact"', add_rule_block)
        self.assertIn('action: { type: "" }', html)
        self.assertNotIn('const type = mode === "quickcommand" ? "run_predefined_command" : "screenshot_fullscreen";', html)

    def test_new_rule_scrolls_expanded_card_into_view(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("scrollRuleIntoView(0);", html)
        self.assertIn("showRuleAddIndicator(0);", html)
        self.assertLess(html.index("showRuleAddIndicator(0);"), html.index("scrollRuleIntoView(0);"))
        self.assertIn("function showRuleAddIndicator(index)", html)
        self.assertIn('if (card) showRuleMoveIndicator(ruleMoveIndicatorRect(card), -1, "+");', html)
        self.assertIn("function scrollRuleIntoView(index)", html)
        self.assertIn('els.rules.querySelector(`.rule[data-index="${index}"]`)', html)
        self.assertIn('rule.scrollIntoView({ behavior: "smooth", block: "center" });', html)

    def test_settings_rule_form_field_order_and_action_label(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        field_order = [
            html.index('form.appendChild(textField(mode === "quickcommand" ? "命令名称" : "动作名称"'),
            html.index('form.appendChild(keywordListField("触发关键词"'),
            html.index('form.appendChild(selectField("匹配模式"'),
            html.index("form.appendChild(actionTypeField"),
        ]
        self.assertEqual(field_order, sorted(field_order))
        self.assertIn('}, "", true));', html)
        self.assertIn('baseField("执行动作", "", true)', html)
        self.assertIn('keywordListField("触发关键词", rule.trigger_keywords', html)
        self.assertIn('}, "每行一个关键词；保存时会清理空行"));', html)
        self.assertNotIn("每行一个关键词；保存时会清理空行。", html)
        self.assertIn('font-size: 11px;', html)
        self.assertIn('hintEl.textContent = `(${hint})`;', html)
        self.assertIn("labelLine.appendChild(hintEl);", html)
        self.assertNotIn('const hintEl = document.createElement("div");', html)
        self.assertNotIn("limit 控制最多返回多少条。", html)
        self.assertNotIn('baseField("type"', html)
        self.assertNotIn("支持直接输入，输入时会模糊匹配已知类型", html)

    def test_quickcommand_uses_custom_command_fields(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('if (mode !== "quickcommand") {', html)
        self.assertIn('action.type = "run_command";', html)
        self.assertIn('textAreaField("执行命令"', html)
        self.assertIn('shellField(action, scheduleRuleSave)', html)
        self.assertIn("执行固定本地命令", html)
        self.assertNotIn("固定本地命令，不要拼接用户输入", html)
        self.assertNotIn("固定本地命令，不要拼接用户输入。", html)
        self.assertIn("命令执行超过该秒数会被终止", html)
        self.assertNotIn("命令执行超过该秒数会被终止。", html)
        self.assertNotIn("支持手动输入，也可选择本机已检测到的执行器", html)
        self.assertIn('numberField("超时秒数"', html)
        self.assertIn("availableShells: []", html)
        self.assertIn("data.available_shells", html)
        self.assertIn("function shellOptions", html)
        self.assertIn('["pwsh", "powershell", "cmd", "bash", "sh", "wsl"]', html)
        self.assertIn("function comboField", html)
        self.assertIn('wrap.className = "type-wrap";', html)
        self.assertIn('menu.className = "type-menu type-menu-portal";', html)
        self.assertIn('option.className = "type-option";', html)
        self.assertIn('dropdown.setAttribute("aria-label", `展开${label}选项`);', html)
        self.assertNotIn("document.createElement(\"datalist\")", html)
        self.assertNotIn("commandIdField", html)
        self.assertNotIn("QuickCommand commands 中的键名", html)

    def test_quickcommand_ssh_mode_settings_are_below_channel_sync(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        sync_index = html.index('checkField("与 QuickAction 渠道范围保持一致"')
        ssh_index = html.index("sshModeSettingsField(modeSshMode(), mode)")
        self.assertLess(sync_index, ssh_index)
        self.assertIn('checkField("Shell 会话模式"', html)
        self.assertIn('row.className = "shell-session-settings";', html)
        self.assertIn('details.className = "shell-session-details";', html)
        self.assertIn('toggleField.classList.add("shell-session-toggle");', html)
        self.assertIn("renderSshModeDetailFields(details, sshMode, mode);", html)
        self.assertIn(".shell-session-settings", html)
        self.assertIn(".shell-session-details", html)
        self.assertIn(".shell-session-detail", html)
        self.assertIn('keywordListField("触发关键词", sshMode.trigger_keywords', html)
        self.assertIn('keywordListField("退出关键词", sshMode.exit_keywords', html)
        self.assertIn('selectField("匹配模式", sshMode.match_mode || "exact"', html)
        self.assertIn("shellField(shell, () =>", html)
        self.assertIn('numberField("超时秒数", sshMode.timeout || 1000', html)
        detail_order = [
            html.index('keywordListField("触发关键词", sshMode.trigger_keywords'),
            html.index('keywordListField("退出关键词", sshMode.exit_keywords'),
            html.index('selectField("匹配模式", sshMode.match_mode || "exact"'),
            html.index("shellField(shell, () =>"),
            html.index('numberField("超时秒数", sshMode.timeout || 1000'),
        ]
        self.assertEqual(detail_order, sorted(detail_order))
        self.assertIn(
            'timeoutField.classList.add("confirm-timeout", "shell-session-detail");',
            html,
        )
        self.assertNotIn('ssh-mode-detail', html)
        self.assertIn("ssh_mode: cleanClientSshMode(modeSshMode())", html)
        self.assertIn('trigger_keywords: parseKeywords(current.trigger_keywords)', html)
        self.assertIn('exit_keywords: parseKeywords(current.exit_keywords)', html)
        self.assertIn('match_mode: cleanMatchMode(current.match_mode, "exact")', html)
        self.assertIn('sshMode.trigger_keywords = ["ssh"];', html)
        self.assertIn('sshMode.exit_keywords = ["exit", "退出"];', html)

    def test_settings_rule_summary_warns_when_keywords_are_empty(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(".rule-meta .missing-keywords", html)
        self.assertIn("color: var(--danger);", html)
        self.assertIn('const hasKeywords = keywords.trim().length > 0;', html)
        self.assertIn(
            'const keywordSummary = hasKeywords ? shorten(keywords, 48) : "无触发关键词，暂不生效。";',
            html,
        )
        self.assertIn(
            'class="${hasKeywords ? "" : "missing-keywords"}"',
            html,
        )
        self.assertNotIn('shorten(keywords || "无触发关键词", 48)', html)

    def test_file_path_hint_explains_empty_allowed_paths_is_disabled(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "文件路径；allowed_paths 留空时白名单不生效，填写后必须位于白名单内",
            html,
        )
        self.assertIn("allowed_paths 留空时白名单不生效", html)
        self.assertNotIn("文件路径，必须位于 allowed_paths 白名单内。", html)
        self.assertNotIn("文件必须在 allowed_paths 白名单内。", html)

    def test_trigger_keywords_use_single_line_add_and_row_actions(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function keywordListField(label, value, onChange, hint = \"\", options = {})", html)
        self.assertIn('input.type = "text";', html)
        self.assertIn('addButton.className = "keyword-confirm";', html)
        self.assertIn('addButton.textContent = "添加";', html)
        self.assertIn('if (event.key !== "Enter") return;', html)
        self.assertIn('if (!items.length && raw.trim() !== raw) target.value = "";', html)
        self.assertIn('commitKeywords([...keywords, ...items]);', html)
        self.assertIn('editButton.textContent = editingIndex === index ? "确认" : "编辑";', html)
        self.assertIn('deleteButton.textContent = "删除";', html)
        self.assertLess(
            html.index("actions.appendChild(editButton);"),
            html.index("actions.appendChild(deleteButton);"),
        )
        self.assertIn(".keyword-input-wrap input", html)
        self.assertIn(".keyword-confirm", html)
        self.assertIn(".keyword-input-wrap:focus-within", html)
        self.assertIn(".keyword-input-wrap input:focus", html)
        self.assertIn(".keyword-row.editing {", html)
        self.assertIn(".keyword-edit-input:focus", html)
        self.assertIn("box-shadow: none;", html)
        self.assertIn("min-width: 54px;", html)
        keyword_row_editing_css = html[
            html.index(".keyword-row.editing {") : html.index(".keyword-text")
        ]
        self.assertIn("border-color: var(--primary);", keyword_row_editing_css)
        self.assertIn("box-shadow: 0 0 0 2px", keyword_row_editing_css)
        keyword_edit_css = html[
            html.index(".keyword-edit-input {") : html.index(".keyword-actions")
        ]
        self.assertIn("border: 0;", keyword_edit_css)
        self.assertIn("background: transparent;", keyword_edit_css)
        self.assertIn("box-shadow: none;", keyword_edit_css)
        keyword_confirm_css = html[
            html.index(".keyword-confirm {") : html.index(".keyword-confirm:hover")
        ]
        self.assertNotIn("position: absolute;", keyword_confirm_css)
        self.assertNotIn("top: 1px;", keyword_confirm_css)
        self.assertNotIn("right: 1px;", keyword_confirm_css)
        self.assertNotIn("bottom: 1px;", keyword_confirm_css)
        self.assertIn(".keyword-list:empty", html)
        self.assertNotIn("min-height: 38px;", html)
        self.assertIn("const cancelEdit = () => {", html)
        self.assertIn('document.addEventListener("pointerdown"', html)
        self.assertIn('const editingRow = list.querySelector(".keyword-row.editing");', html)
        self.assertIn("if (!editingRow || editingRow.contains(target)) return;", html)
        self.assertIn("cancelEdit();", html)
        self.assertIn("new MutationObserver", html)
        self.assertIn("abortController.abort();", html)

    def test_mode_confirm_controls_are_below_notice_template(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        order = [
            html.index('textField("执行成功返回提示"'),
            html.index("confirmSettingsField(confirm, mode)"),
            html.index('checkField("仅管理员可用"'),
            html.index("channelScopeField("),
        ]
        self.assertEqual(order, sorted(order))
        confirm_order = [
            html.index('checkField("启用二次确认"'),
            html.index("function renderConfirmDetailFields(row, confirm, mode)"),
            html.index('textField("确认语"'),
            html.index('numberField("确认超时秒数"'),
        ]
        self.assertEqual(confirm_order, sorted(confirm_order))
        self.assertIn("row.querySelectorAll(\".confirm-detail\").forEach((field) => field.remove());", html)
        self.assertIn('confirmTextField.classList.add("confirm-detail");', html)
        self.assertIn('timeoutField.classList.add("confirm-timeout", "confirm-detail");', html)
        confirm_change_block = html[
            html.index('row.appendChild(checkField("启用二次确认"') : html.index(
                "function renderConfirmDetailFields(row, confirm, mode)"
            )
        ]
        self.assertIn("renderConfirmDetailFields(row, confirm, mode);", confirm_change_block)
        self.assertNotIn("renderModeSettings();", confirm_change_block)
        self.assertIn(
            "grid-template-columns: minmax(150px, 220px) minmax(150px, 260px) minmax(120px, 150px);",
            html,
        )
        self.assertIn("align-items: start;", html)
        self.assertNotIn("align-items: end;", html)
        self.assertNotIn(".confirm-settings-row.disabled {\n      grid-template-columns: minmax(150px, 220px);", html)

    def test_advanced_sleep_keywords_use_keyword_list_editor(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        for label, field in [
            ("临时休眠关键词", "sleep.sleep_keywords"),
            ("永久休眠关键词", "sleep.permanent_sleep_keywords"),
            ("唤醒关键词", "sleep.wake_keywords"),
            ("状态查询关键词", "sleep.status_keywords"),
        ]:
            self.assertIn(
                f'keywordListField("{label}", {field}',
                html,
            )
            self.assertNotIn(
                f'textAreaField("{label}"',
                html,
            )
        self.assertNotIn('keywordListField("全部唤醒关键词"', html)
        self.assertIn(
            'selectField("休眠/唤醒关键词匹配模式", sleep.sleep_match_mode || "exact"',
            html,
        )
        self.assertIn(
            "对临时休眠、永久休眠、唤醒关键词生效；状态查询固定完全匹配",
            html,
        )
        self.assertIn('sleep_match_mode: "exact"', html)
        self.assertIn('status_keywords: ["休眠状态"]', html)
        self.assertNotIn('status_keywords: ["休眠状态", "LocalAction状态"]', html)
        self.assertIn("persist_sleep_state: true", html)
        self.assertNotIn('checkField("持久化休眠状态"', html)
        self.assertNotIn('checkField("允许全局休眠"', html)

    def test_action_type_field_is_editable_dropdown(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('input.setAttribute("autocomplete", "off");', html)
        self.assertIn('dropdown.className = "type-dropdown";', html)
        self.assertNotIn('dropdown.addEventListener("mouseenter", openOptions);', html)
        self.assertIn('dropdown.addEventListener("pointerdown", openFromDropdown);', html)
        self.assertIn('dropdown.addEventListener("click", openFromDropdown);', html)
        self.assertIn("event.stopPropagation();", html)
        self.assertIn('const openOptions = () => drawOptions(true);', html)
        self.assertIn('menu.className = "type-menu type-menu-portal";', html)
        self.assertIn("document.body.appendChild(menu)", html)
        self.assertIn("positionTypeMenu(wrap, menu)", html)
        self.assertIn("function positionTypeMenu(anchor, menu)", html)
        self.assertIn('!target.closest(".type-wrap") && !target.closest(".type-menu")', html)
        self.assertIn('document.querySelectorAll(".type-menu-portal")', html)
        self.assertIn('TYPE_DEFS.filter(([value, label, desc])', html)
        self.assertIn('input.addEventListener("input"', html)

    def test_rule_move_buttons_support_hold_drag_and_swipe_restore(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('const DRAG_HOLD_MS = 280;', html)
        self.assertIn('const RESTORE_HINT_TEXT = "继续滑动以恢复原位";', html)
        self.assertIn('const RESTORE_ACTIVE_TEXT = "松开恢复原位";', html)
        self.assertIn("const RESTORE_THRESHOLD_EXTRA_PX = 32;", html)
        self.assertIn("const RESTORE_THRESHOLD_MIN_PX = 96;", html)
        self.assertIn("const RESTORE_THRESHOLD_MAX_RATIO = 0.75;", html)
        self.assertIn("const RULE_MOVE_ANIMATION_MS = 220;", html)
        self.assertIn("const RULE_MOVE_INDICATOR_MS = 900;", html)
        self.assertIn('<div class="rule-restore-hint">${RESTORE_HINT_TEXT}</div>', html)
        self.assertIn("function bindRuleDragHandle(card, rule, index, direction)", html)
        self.assertIn('handle.addEventListener("pointerdown"', html)
        self.assertIn('moveRule(index, direction);', html)
        self.assertIn("const previousPositions = captureRulePositions(rules);", html)
        self.assertIn("animateRuleMove(previousPositions, item, delta);", html)
        self.assertIn("function captureRulePositions(rules = getRules())", html)
        self.assertIn("function animateRuleMove(previousPositions, movedRule, direction)", html)
        self.assertIn('card.classList.add("rule-moving")', html)
        self.assertIn('card.classList.remove("rule-moving")', html)
        self.assertIn(".rule.rule-moving", html)
        self.assertIn(".rule-move-indicator", html)
        indicator_css = html[
            html.index(".rule-move-indicator {") : html.index(".rule-move-indicator.down")
        ]
        self.assertNotIn("border:", indicator_css)
        self.assertNotIn("border-radius", indicator_css)
        self.assertNotIn("background:", indicator_css)
        self.assertNotIn("box-shadow", indicator_css)
        self.assertIn("@keyframes ruleMoveIndicatorFade", html)
        self.assertIn("function showRuleMoveIndicator(ruleRect, direction, symbol = null)", html)
        self.assertIn('const indicatorKind = symbol === "+" ? "add" : (direction < 0 ? "up" : "down");', html)
        self.assertIn('indicator.className = `rule-move-indicator ${indicatorKind}`;', html)
        self.assertIn('indicator.textContent = symbol || (direction < 0 ? "↑" : "↓");', html)
        self.assertIn(".rule-move-indicator.add", html)
        self.assertIn("if (rule === movedRule) movedRect = ruleMoveIndicatorRect(card);", html)
        self.assertIn("showRuleMoveIndicator(movedRect, direction);", html)
        self.assertIn("function ruleMoveIndicatorRect(card)", html)
        self.assertIn('const head = card.querySelector(".rule-head");', html)
        self.assertIn("window.setTimeout(() => indicator.remove(), RULE_MOVE_INDICATOR_MS);", html)
        self.assertLess(
            html.index("if (next < 0 || next >= rules.length) return;"),
            html.index("const previousPositions = captureRulePositions(rules);"),
        )
        self.assertIn('drag.restoreActive = restoreActive;', html)
        self.assertIn("restoreThreshold: measureRestoreThreshold", html)
        self.assertIn("const restoreActive = absX >= drag.restoreThreshold;", html)
        self.assertIn('card.classList.toggle("restore-active", restoreActive)', html)
        self.assertIn("drag.hint.textContent = restoreActive ? RESTORE_ACTIVE_TEXT : RESTORE_HINT_TEXT;", html)
        self.assertIn("function measureRestoreThreshold(hint, width)", html)
        self.assertIn("RESTORE_HINT_TEXT", html)
        self.assertIn("RESTORE_THRESHOLD_EXTRA_PX", html)
        self.assertIn(".rule-drag-placeholder", html)
        self.assertIn("createRuleDragPlaceholder(drag);", html)
        self.assertIn("function createRuleDragPlaceholder(drag)", html)
        self.assertIn('placeholder.className = "rule-drag-placeholder";', html)
        self.assertIn("placeholder.style.height = `${drag.height}px`;", html)
        self.assertIn('drag.card.style.position = "absolute";', html)
        self.assertIn("function updateRuleDragPlaceholder(drag)", html)
        self.assertIn('const cards = Array.from(els.rules.querySelectorAll(".rule")).filter((card) => card !== drag.card);', html)
        self.assertIn("const midpoint = rect.top + rect.height / 2;", html)
        self.assertIn("drag.targetIndex = clampInsertIndex(targetIndex, cards.length);", html)
        self.assertIn("updateRuleDragPlaceholder(drag);", html)
        self.assertIn("els.rules.insertBefore(drag.placeholder, before);", html)
        self.assertIn("drag.card.style.transform = `translate3d(0, ${deltaY}px, 0)`;", html)
        self.assertNotIn("directedDeltaY", html)
        self.assertNotIn("allowedY", html)
        self.assertIn("commitDraggedRule(drag)", html)
        self.assertIn("restoreDraggedRule(drag)", html)
        self.assertIn("let moveIndicator = null;", html)
        self.assertIn("moveIndicator = commitDraggedRule(drag);", html)
        self.assertIn("if (moveIndicator) showDraggedRuleMoveIndicator(moveIndicator);", html)
        self.assertIn("return next === current ? null : { rule: drag.rule, direction: next < current ? -1 : 1 };", html)
        self.assertIn("function showDraggedRuleMoveIndicator(moveIndicator)", html)
        self.assertIn('els.rules.querySelector(`.rule[data-index="${index}"]`)', html)
        self.assertIn("showRuleMoveIndicator(ruleMoveIndicatorRect(card), moveIndicator.direction);", html)
        self.assertIn("function clampInsertIndex(index, length)", html)
        self.assertIn("function clearRuleDragLayout(drag)", html)
        self.assertIn("drag.placeholder.remove();", html)
        self.assertIn('drag.card.style.position = "";', html)
        self.assertIn("drag.handle.dataset.dragConsumed = \"1\"", html)
        self.assertIn("touch-action: none;", html)
        self.assertIn("cubic-bezier(.2, .8, .2, 1)", html)

    def test_settings_page_does_not_render_back_button(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('id="backBtn"', html)
        self.assertNotIn('class="back-button"', html)
        self.assertNotIn('href="/#/extension#installed"', html)
        self.assertNotIn('target="_top"', html)
        self.assertNotIn('class="back-arrow"', html)
        self.assertNotIn('>←</button>', html)
        self.assertNotIn('class="icon back-button"', html)
        self.assertNotIn('INSTALLED_PLUGINS_TARGET = "/#/extension#installed"', html)
        self.assertNotIn("window.location.href = targetUrl;", html)
        self.assertNotIn("function goBack()", html)
        self.assertNotIn("els.backBtn", html)
        self.assertNotIn('kind: "localaction:navigate"', html)
        self.assertNotIn('pluginName: "astrbot_plugin_local_action"', html)
        self.assertNotIn("postMessage(message", html)
        self.assertNotIn("/#/extension/astrbot_plugin_local_action#installed", html)

    def test_settings_page_keeps_rendering_when_expanded_storage_is_blocked(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function saveExpanded()", html)
        self.assertIn("localStorage.setItem(STORE_KEY", html)
        self.assertIn("catch {\n        // Sandboxed plugin pages may block storage", html)
        self.assertIn('window.dispatchEvent(new Event("resize"))', html)

    def test_settings_page_enabled_save_toast_includes_state(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        modebar_index = html.index('id="modebar"')
        toast_index = html.index('id="toast"')
        mode_settings_index = html.index('id="modeSettings"')
        self.assertLess(modebar_index, toast_index)
        self.assertLess(toast_index, mode_settings_index)
        self.assertIn('saveEnabledStates(() =>', html)
        self.assertIn('els.modeEnabled.checked)', html)
        self.assertIn('event.target.checked)', html)
        self.assertIn(".toast-state.off { color: #9099a6; }", html)
        self.assertIn("function showStateSavedToast(label, enabled)", html)
        self.assertIn("els.toast.append(`${label}：`);", html)
        self.assertIn('stateText.className = `toast-state ${enabled ? "on" : "off"}`;', html)
        self.assertIn('stateText.textContent = enabled ? "开" : "关";', html)
        self.assertIn('els.toast.append(stateText, " 已保存");', html)
        self.assertIn('showStateSavedToast("启用状态", enabled);', html)
        self.assertIn('return { kind: "modeState", mode, label: "二次确认", enabled: Boolean(options.confirmState), currentState: () => Boolean(options.confirmState) };', html)
        self.assertIn("showModeStateSavedToast(toast.mode, toast.label, toast.enabled, toast.currentState);", html)
        self.assertIn("function showModeStateSavedToast(mode, label, enabled, currentState = null)", html)
        self.assertIn('if (typeof current === "boolean" && current !== enabled) {', html)
        self.assertIn("showStateSavedToast(label, current);", html)
        self.assertIn('scheduleAutoSave(mode, switchSaveOptions("仅管理员可用", value));', html)
        self.assertNotIn('switchSaveOptions("允许 QuickAction 规则独立二次确认"', html)
        self.assertNotIn('switchSaveOptions("允许 QuickCommand 规则独立二次确认"', html)
        self.assertNotIn('switchSaveOptions("允许 QuickAction 规则单独渠道范围"', html)
        self.assertNotIn('switchSaveOptions("允许 QuickCommand 规则单独渠道范围"', html)
        self.assertIn('scheduleAutoSave("advanced", switchSaveOptions("启用休眠/唤醒控制", value));', html)
        self.assertIn('return { kind: "modeState", mode, label: options.stateLabel, enabled: Boolean(options.enabledState) };', html)
        self.assertIn('return { kind: "advancedState", label: options.stateLabel, enabled: Boolean(options.enabledState), currentState: () => Boolean(options.enabledState) };', html)
        self.assertIn("showAdvancedStateSavedToast(toast.label, toast.enabled, toast.currentState);", html)
        self.assertIn("function showAdvancedStateSavedToast(label, enabled, currentState = null)", html)
        self.assertIn("function modeStateValue(mode, label)", html)
        self.assertIn('if (label === "仅管理员可用") return modeAdminOnly(mode);', html)
        self.assertIn("function advancedStateValue(label)", html)
        self.assertIn('class="switch-state"', html)
        self.assertIn('wrap.querySelector(".switch-state")', html)
        self.assertNotIn('wrap.querySelector("span:last-child")', html)
        self.assertNotIn('showToast("启用状态已保存", "ok")', html)

    def test_settings_page_autosaves_rule_and_advanced_edits(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("const AUTO_SAVE_DELAY_MS = 650;", html)
        self.assertIn("autoSaveTimers: {}", html)
        self.assertIn("autoSaveSeqs: { quickaction: 0, quickcommand: 0, advanced: 0 }", html)
        self.assertIn("autoSaveRunning: { quickaction: false, quickcommand: false, advanced: false }", html)
        self.assertIn("autoSavePending: { quickaction: null, quickcommand: null, advanced: null }", html)
        self.assertIn("function scheduleAutoSave(targetMode = state.mode, options = {})", html)
        self.assertIn("const run = () => queueAutoSave(targetMode, options);", html)
        self.assertIn("function queueAutoSave(targetMode, options = {})", html)
        self.assertIn("state.autoSavePending[targetMode] = mergeAutoSaveOptions(state.autoSavePending[targetMode], options);", html)
        self.assertIn("if (state.autoSaveRunning[targetMode]) return;", html)
        self.assertIn("async function drainAutoSaveQueue(targetMode)", html)
        self.assertIn("let finalToast = null;", html)
        self.assertIn("while (state.autoSavePending[targetMode])", html)
        self.assertIn("toast = await saveRulesForMode(targetMode, { ...options, auto: true });", html)
        self.assertIn("if (!state.autoSavePending[targetMode] && finalToast) showAutoSaveToast(finalToast);", html)
        self.assertIn("function mergeAutoSaveOptions(previous, next = {})", html)
        self.assertIn("scheduleAutoSave(mode, { immediate: true, confirmState: value });", html)
        self.assertLess(
            html.index('text.textContent = input.checked ? "开启" : "关闭";'),
            html.index("onChange(input.checked);"),
        )
        self.assertIn('scheduleAutoSave("advanced"', html)
        self.assertIn("scheduleRuleSave({ immediate: true });", html)
        self.assertIn("scheduleAutoSave(mode, { immediate: true });", html)
        self.assertNotIn('switchSaveOptions("允许 QuickAction 规则单独渠道范围"', html)
        self.assertIn("function switchSaveOptions(label, enabled)", html)
        self.assertIn("return { immediate: true, stateLabel: label, enabledState: enabled };", html)
        self.assertIn("function saveRulesForMode(mode, options = {})", html)
        self.assertIn('showToast(isAuto ? "正在自动保存..." : "正在保存...");', html)
        self.assertIn("if (isAuto) return modeAutoSaveToast(mode, options);", html)
        self.assertIn('showToast("已保存", "ok");', html)
        self.assertIn("function showAutoSaveToast(toast)", html)
        self.assertIn('showToast(toast.message || "自动保存成功", "ok");', html)
        self.assertIn("await saveAdvancedSettings({ ...options, auto: true });", html)
        self.assertIn("if (!state.autoSavePending[mode]) {\n            markPersistedRulesForMode(mode);", html)
        self.assertNotIn("if (!state.autoSavePending[mode]) {\n            state.config = data.config || state.config;", html)
        self.assertIn("} else if (!state.autoSavePending.advanced) {\n          state.config = data.config || state.config;", html)
        self.assertNotIn("const hasEnabledState = Object.prototype.hasOwnProperty.call(options, \"enabledState\");", html)
        self.assertNotIn("saveAdvancedSettings({ auto: true, enabledState: options.enabledState });", html)
        self.assertNotIn('showStateSavedToast("启用状态", Boolean(options.enabledState));', html)
        self.assertIn('showStateSavedToast("启用状态", enabled);', html)
        self.assertNotIn("showEnabledSavedToast", html)
        self.assertIn("markPersistedRulesForMode(mode);", html)
        self.assertIn("function clearAutoSaveTimers()", html)
        self.assertIn("clearAutoSaveTimers();", html)
        self.assertIn("state.autoSavePending = { quickaction: null, quickcommand: null, advanced: null };", html)

    def test_channel_scope_mode_uses_buttons_instead_of_native_select(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function modeButtonField", html)
        self.assertIn('group.className = "segmented-options";', html)
        self.assertIn("let currentValue = value;", html)
        self.assertIn('button.dataset.value = optionValue;', html)
        self.assertIn('const active = item.dataset.value === nextValue;', html)
        self.assertIn('item.classList.toggle("active", active);', html)
        self.assertIn('item.setAttribute("aria-checked", active ? "true" : "false");', html)
        self.assertIn('button.className = `segment-option ${active ? "active" : ""}`;', html)
        self.assertIn("const selectOption = (event) => {", html)
        self.assertIn("event.preventDefault();\n            event.stopPropagation();", html)
        self.assertIn("if (optionValue === currentValue) return;", html)
        self.assertIn("currentValue = optionValue;", html)
        self.assertIn("syncActiveOption(optionValue);", html)
        self.assertIn('button.addEventListener("pointerdown", selectOption);', html)
        self.assertIn('button.addEventListener("click", selectOption);', html)
        self.assertIn('grid.appendChild(modeButtonField("范围模式"', html)
        self.assertNotIn('grid.appendChild(selectField("范围模式"', html)

    def test_channel_scope_actions_keep_layout_stable_when_hidden(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(".channel-scope-actions.hidden", html)
        self.assertIn("visibility: hidden;", html)
        self.assertIn('actions.classList.toggle("hidden", !hasSelectableMode);', html)
        self.assertIn("selectAllButton.disabled = selectAllButton.disabled || !hasSelectableMode;", html)
        self.assertIn("titleEl.appendChild(actions);", html)
        self.assertNotIn("if (hasSelectableMode) {\n        actions.appendChild(selectAllButton);", html)

    def test_channel_scope_custom_platform_input_is_discarded_on_scope_mode_switch(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("commitPendingInputs: new Set(),", html)
        self.assertIn("function commitPendingInputs()", html)
        self.assertIn("commitPendingInputs();\n      state.mode = mode;", html)
        self.assertIn(
            'grid.appendChild(modeButtonField("范围模式", scope.mode, CHANNEL_SCOPE_MODES, (value) => {\n'
            "        commitPendingInputs();\n"
            "        scope.mode = value;\n"
            "        onChange({ immediate: true });\n"
            "        rerenderModeSettingsSoon();",
            html,
        )
        self.assertIn("function rerenderModeSettingsSoon()", html)
        self.assertIn("requestAnimationFrame(renderModeSettings);", html)
        self.assertNotIn("let commitCustomPlatformInput = () => false;", html)
        self.assertNotIn("commitCustomPlatformInput();", html)
        self.assertIn(
            "if (options.commitPendingOnUnmount) state.commitPendingInputs.add(commitPendingInput);",
            html,
        )
        custom_platform_field = html[
            html.index('keywordListField("自定义平台名"') : html.index(
                '}, "每行一个平台名；保存时会清理空行")'
            )
        ]
        self.assertNotIn("commitPendingOnUnmount", custom_platform_field)
        self.assertNotIn("registerCommitPending", custom_platform_field)

    def test_channel_scope_auto_config_merges_log_matched_channels(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('autoButton.textContent = undoSnapshot ? "撤回" : "自动配置";', html)
        self.assertIn("const hasSelectableMode = channelScopeHasSelectableMode(scope);", html)
        self.assertIn("const undoSnapshot = hasSelectableMode ? state.channelScopeUndo[mode] : null;", html)
        self.assertIn('? "恢复自动配置前的渠道范围"', html)
        self.assertIn(': "检测 AstrBot 可选平台，并根据日志对话记录自动勾选渠道";', html)
        self.assertIn('const data = await apiGet("platform-scope");', html)
        self.assertIn('selectAllButton.textContent = "全选";', html)
        self.assertIn('clearButton.textContent = "清空";', html)
        self.assertIn("if (!hasSelectableMode) return;", html)
        self.assertIn('actions.classList.toggle("hidden", !hasSelectableMode);', html)
        self.assertIn('actions.appendChild(selectAllButton);', html)
        self.assertIn('actions.appendChild(clearButton);', html)
        self.assertIn('actions.appendChild(autoButton);', html)
        self.assertIn("titleEl.appendChild(actions);", html)
        self.assertIn("const addedOptions = mergePlatformScopeOptions(data);", html)
        self.assertIn("const snapshot = snapshotChannelScope(scope);", html)
        self.assertIn("state.channelScopeUndo[mode] = snapshot;", html)
        self.assertIn("restoreChannelScopeFromUndo(scope, mode);", html)
        self.assertIn('showToast("已撤回自动配置", "ok");', html)
        self.assertIn("function applyLogChannelScope(scope, platformScope)", html)
        self.assertIn('scope.mode = "include";', html)
        self.assertIn('const selected = new Set(parseKeywords(scope[key]));', html)
        self.assertIn("if (!normalized || selected.has(normalized)) return;", html)
        self.assertIn("...channelOptions.filter((value) => selected.has(value)),", html)
        self.assertIn("if (addedChannels || addedOptions) {", html)
        self.assertIn("onChange({ immediate: true });", html)
        self.assertIn("function mergePlatformScopeOptions(platformScope)", html)
        self.assertIn("current.options.forEach(addOption);", html)
        self.assertIn("platformScope.options.forEach((item) => {", html)
        self.assertIn("if (!value || seenValues.has(value)) return false;", html)
        self.assertIn("mergedOptions.push({ ...item, value, label: item.label || value });", html)
        self.assertIn("function snapshotChannelScope(scope)", html)
        self.assertIn("function selectAllChannelScope(scope)", html)
        self.assertIn("function clearChannelScope(scope)", html)
        self.assertIn("function channelScopeHasSelectableMode(scope)", html)
        self.assertIn('return scope.mode === "include" || scope.mode === "exclude";', html)
        self.assertIn("clearChannelScopeUndo(mode);", html)
        self.assertIn('if (mode !== "quickcommand" || !syncWithQuickActionChannelScope) {', html)
        self.assertIn('channelScopeField(`${mode === "quickcommand" ? "QuickCommand" : "QuickAction"} 渠道范围`', html)
        self.assertIn("}, mode));", html)

    def test_settings_selector_field_embeds_window_picker(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function windowPickerField(value, onSelect, onCopyFallback)", html)
        self.assertIn("function selectorForWindow(item)", html)
        self.assertIn("if (label === \"selector\")", html)
        self.assertIn(".selector-label-line", html)
        self.assertIn("min-height: 36px;", html)
        self.assertIn("padding: 4px 0;", html)
        self.assertIn("height: 36px;", html)
        self.assertIn("padding: 0 16px;", html)
        self.assertIn("font-size: 14px;", html)
        self.assertIn('field.querySelector(".label-line").classList.add("selector-label-line");', html)
        self.assertIn('selectorButton.textContent = "选择窗口";', html)
        self.assertIn('selectorButton.className = "selector-picker-button";', html)
        self.assertIn("field.querySelector(\".label-line\").appendChild(selectorButton);", html)
        self.assertIn("picker.hidden = true;", html)
        self.assertIn("const opening = picker.hidden;", html)
        self.assertIn('selectorButton.textContent = opening ? "收起窗口" : "选择窗口";', html)
        self.assertIn('if (opening && picker.dataset.loaded !== "1") {', html)
        self.assertIn('picker.dataset.loaded = "1";', html)
        self.assertIn("picker.loadWindows();", html)
        self.assertIn('class="window-picker-head"', html)
        self.assertIn('class="window-query"', html)
        self.assertIn('class="window-refresh"', html)
        self.assertIn('apiGet("windows", {', html)
        self.assertIn("q: query.value.trim(),", html)
        self.assertIn("limit: 100,", html)
        self.assertIn('data-action="select"', html)
        self.assertIn('data-action="copy"', html)
        self.assertIn('item.is_foreground ? "前台" : "窗口"', html)
        self.assertIn('onSelect(selector);', html)
        self.assertIn('row.addEventListener("dblclick", (event) => {', html)
        self.assertIn('if (event.target.closest(".window-row-actions")) return;', html)
        self.assertIn("chooseWindow(item);", html)
        self.assertIn('navigator.clipboard.writeText(text)', html)
        self.assertIn('onCopyFallback(text);', html)
        self.assertIn('input.focus();', html)
        self.assertIn('input.select();', html)
        self.assertIn('input.setSelectionRange(0, input.value.length);', html)
        self.assertIn('return document.execCommand("copy");', html)
        self.assertIn('setStatus("选择器已复制到剪贴板。", "ok");', html)
        self.assertIn('setStatus("已选中选择器文本，并已复制到剪贴板。", "ok");', html)
        self.assertIn('setStatus("已选中选择器文本，请手动复制。", "error");', html)
        self.assertIn("wrap.loadWindows = loadWindows;", html)
        self.assertNotIn("loadWindows();\n      return wrap;", html)
        self.assertIn('if (isObject(item.selector)) return structuredCloneSafe(item.selector);', html)
        self.assertNotIn("screenshotSelected", html)
        self.assertNotIn("closeSelectedProcess", html)
        self.assertNotIn("loadForeground", html)

    def test_enabled_state_autosave_skips_unsaved_new_rules(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "persistedRules: { quickaction: new WeakSet(), quickcommand: new WeakSet() }",
            html,
        )
        self.assertIn("markPersistedRules();", html)
        self.assertIn("function markPersistedRules()", html)
        self.assertIn(
            ".filter(({ rule }) => state.persistedRules[state.mode].has(rule))",
            html,
        )
        self.assertIn("state.persistedRules[mode].add(rule);", html)

    def test_settings_page_has_advanced_settings_tab(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('grid-template-columns: repeat(3, minmax(120px, 1fr));', html)
        self.assertIn('data-mode="advanced"', html)
        self.assertIn(">高级设置</button>", html)
        self.assertIn('id="advancedPanel"', html)
        self.assertIn("function renderAdvancedSettings()", html)
        self.assertIn("advancedSettingsFromConfig()", html)
        self.assertIn("saveAdvancedSettings", html)
        self.assertIn('apiPost("settings/advanced"', html)
        self.assertIn("advanced_settings_enabled", html)
        self.assertIn("max_file_size_mb", html)
        self.assertIn("fileSizeLimitField", html)
        self.assertIn("size-limit-control", html)
        self.assertIn('["KB", "MB", "GB"]', html)
        self.assertIn("normalizeFileSizeMb", html)
        self.assertIn('Object.prototype.hasOwnProperty.call(state.config, "max_file_size_mb")', html)
        self.assertIn('Object.prototype.hasOwnProperty.call(nested, "max_file_size_mb")', html)
        self.assertIn("为空、-、负数则不限制；为 0 则阻止所有文件", html)
        self.assertIn('pathPickerField("文件动作白名单路径"', html)
        self.assertIn('apiGet("file-picker", { type })', html)
        self.assertIn("quickaction_allowed_paths: quickactionAllowedPaths()", html)
        self.assertIn("function quickactionAllowedPaths(value)", html)
        self.assertIn("选择文件夹", html)
        self.assertNotIn('choosePath("file"', html)
        self.assertIn('choosePath("directory", directoryButton)', html)
        self.assertIn("留空时白名单不生效；填写后文件动作的 path 必须位于白名单内", html)
        self.assertIn("quickaction_rule_confirm_enabled", html)
        self.assertIn("quickcommand_rule_channel_scope_enabled", html)
        self.assertNotIn('checkField("允许 QuickAction 规则独立二次确认"', html)
        self.assertNotIn('checkField("允许 QuickCommand 规则独立二次确认"', html)
        self.assertNotIn('checkField("允许 QuickAction 规则单独渠道范围"', html)
        self.assertNotIn('checkField("允许 QuickCommand 规则单独渠道范围"', html)
        self.assertIn("sleep_wake", html)
        self.assertIn("default_sleep_seconds: 3600", html)
        self.assertNotIn('checkField("允许模式休眠"', html)
        self.assertNotIn('checkField("允许规则休眠"', html)
        self.assertIn("renderAdvancedSettings();", html)
        self.assertIn("els.modebar.hidden = false;", html)
        self.assertIn('? "高级设置"', html)
        self.assertIn("? Boolean(conf.advanced_settings_enabled)", html)
        self.assertIn("saveAdvancedEnabledState", html)
        self.assertNotIn('checkField("启用高级设置"', html)
        self.assertIn("els.rules.hidden = state.mode === \"advanced\" || !enabled;", html)

    def test_settings_page_shows_first_open_risk_modal(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="riskModal"', html)
        self.assertIn("LocalAction 风险提示", html)
        self.assertIn("settings_risk_notice_acknowledged", html)
        self.assertIn("function showRiskModalIfNeeded(data)", html)
        self.assertIn('els.riskModal.classList.add("open");', html)
        self.assertIn("function acknowledgeRiskModal()", html)
        self.assertIn('apiPost("settings/risk-ack", {})', html)
        self.assertIn("QuickCommand 可能执行本机命令", html)

    def test_rule_delete_button_requires_inline_second_click_confirmation(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('pendingDeleteKey: ""', html)
        self.assertIn("function requestDeleteRule(rule, index)", html)
        self.assertIn("if (state.pendingDeleteKey === key) {\n        animateDeleteRule(rule, index);", html)
        self.assertIn("state.pendingDeleteKey = key;", html)
        self.assertIn("const RULE_DELETE_ANIMATION_MS = 160;", html)
        self.assertIn("const RULE_DELETE_REFLOW_DELAY_MS = 80;", html)
        self.assertIn("function animateDeleteRule(rule, index)", html)
        self.assertIn("const previousPositions = captureRulePositions(rules);", html)
        self.assertIn('card.classList.add("deleting");', html)
        self.assertIn(
            "window.setTimeout(\n"
            "        () => deleteRule(index, rule, previousPositions),\n"
            "        RULE_DELETE_ANIMATION_MS + RULE_DELETE_REFLOW_DELAY_MS,\n"
            "      );",
            html,
        )
        self.assertIn("function animateRuleReflow(previousPositions)", html)
        self.assertIn("animateRuleReflow(previousPositions);", html)
        self.assertIn(".rule.deleting", html)
        self.assertIn("@keyframes ruleDeleteSlideOut", html)
        self.assertIn("translate3d(-110%, 0, 0)", html)
        self.assertIn("function deleteButtonHtml(rule, index)", html)
        self.assertIn('class="delete-rule delete-confirm"', html)
        self.assertIn('<span class="delete-mark">删除</span>', html)
        self.assertIn("function deleteKey(rule, index)", html)
        self.assertIn("function clearPendingDelete()", html)
        self.assertIn('if (state.pendingDeleteKey && !target.closest(".delete-rule")) {', html)
        self.assertIn(
            "clearPendingDelete();\n        render();",
            html,
        )
        self.assertIn("button.delete-confirm", html)
        self.assertIn("@keyframes slideInFromRight", html)
        self.assertIn(
            'card.querySelector(".delete-rule").addEventListener("click", () => requestDeleteRule(rule, index));',
            html,
        )

    def test_settings_page_preserves_rule_expansion_by_rule_after_delete_or_move(self):
        html = (PLUGIN_ROOT / "pages" / "settings" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function captureExpandedStates(rules)", html)
        self.assertIn("function restoreExpandedStates(rules, expandedByRule)", html)
        self.assertIn("function isRuleExpanded(rule, index)", html)
        self.assertIn("function deleteRule(index, rule = null, previousPositions = null)", html)
        self.assertIn("const targetIndex = rule ? rules.indexOf(rule) : index;", html)
        self.assertIn(
            "const expandedByRule = captureExpandedStates(rules);\n"
            "      rules.splice(targetIndex, 1);\n"
            "      clearPendingDelete();\n"
            "      restoreExpandedStates(rules, expandedByRule);",
            html,
        )
        self.assertIn(
            "restoreExpandedStates(rules, expandedByRule);\n"
            "      render();\n"
            "      animateRuleReflow(previousPositions);",
            html,
        )
        self.assertIn(
            "const expandedByRule = captureExpandedStates(rules);\n"
            "      const [item] = rules.splice(index, 1);\n"
            "      rules.splice(next, 0, item);\n"
            "      restoreExpandedStates(rules, expandedByRule);",
            html,
        )
        self.assertIn("values[ruleKey(rule, index)] = expanded;", html)
        self.assertIn('values[String(index)] = expanded;', html)

    def test_removed_legacy_plugin_pages_stay_removed(self):
        self.assertFalse((PLUGIN_ROOT / "pages" / "window-picker").exists())
        self.assertFalse((PLUGIN_ROOT / "pages" / "rule-table").exists())
        self.assertFalse((PLUGIN_ROOT / "pages" / "quickcommand-scope").exists())


if __name__ == "__main__":
    unittest.main()
