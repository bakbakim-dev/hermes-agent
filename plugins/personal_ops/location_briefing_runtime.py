from __future__ import annotations

from . import legacy_shared as _legacy_shared

globals().update({
    name: value
    for name, value in _legacy_shared.__dict__.items()
    if not name.startswith("__")
})

# This module was mechanically extracted from temp_personal_ops_tools.py.
# The compatibility wrapper injects cross-domain legacy globals after import.

def _runtime_build_arrive_briefing(tasks: List[Dict[str, Any]], projects_map: Dict[str, str]) -> str:
    local_now = datetime.now(timezone.utc).astimezone(_runtime_local_tz())
    time_str = local_now.strftime('%I:%M %p').lstrip('0')

    personal_tasks = []
    for t in tasks:
        proj_id = t.get("project_id")
        proj_name = projects_map.get(proj_id, "").lower()
        if "work" in proj_name or "business" in proj_name:
            continue
        personal_tasks.append(t)

    overdue = []
    today = []
    for t in personal_tasks:
        due_info = t.get("due") or {}
        due_date = due_info.get("date", "")
        if due_date and due_date < local_now.strftime('%Y-%m-%d'):
            overdue.append(t)
        else:
            today.append(t)

    def _format_todoist_due_status(task: Dict[str, Any]) -> str:
        due_info = task.get("due") or {}
        due_val = due_info.get("datetime") or due_info.get("date") or due_info.get("string", "")
        due_dt = _operator_parse_task_due(task)
        if due_dt is None:
            return ""
        delta = due_dt.astimezone(_runtime_local_tz()) - local_now
        seconds = int(delta.total_seconds())
        if seconds < 0:
            seconds = abs(seconds)
            if seconds < 60:
                return "started <1m ago"
            minutes = seconds // 60
            if minutes < 60:
                return f"started {minutes}m ago"
            hours = minutes // 60
            return f"started {hours}h {minutes % 60:02d}m ago"
        if seconds < 60:
            return "starts in <1m"
        minutes = seconds // 60
        if minutes < 60:
            return f"starts in {minutes}m"
        hours = minutes // 60
        return f"starts in {hours}h {minutes % 60:02d}m"

    lines = [
        f"🏡 <b>Welcome Home!</b>",
        f"I received your arrival signal at {time_str}. Here is your custom evening digest alongside the <b>Hermes Dock</b>:",
        "",
    ]

    if overdue:
        lines.append(f"\u23f0 You have {len(overdue)} overdue task{'s' if len(overdue) != 1 else ''} that need{'s' if len(overdue) == 1 else ''} attention:")
        for t in overdue[:5]:
            t_id = t.get("id")
            content = t.get("content", "").strip()
            escaped_content = _escape_html(content)
            due_info = t.get("due") or {}
            due_val = due_info.get('string', due_info.get('date', ''))
            due_str = f" (due {due_val})" if due_val else ""
            escaped_due_str = _escape_html(due_str)
            if t_id:
                lines.append(f"  \u2022 <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{escaped_due_str}")
            else:
                lines.append(f"  \u2022 {escaped_content}{escaped_due_str}")
        lines.append("")

    if today:
        lines.append(f"\U0001f4cb On your plate for today ({len(today)} task{'s' if len(today) != 1 else ''}):")
        for t in today[:7]:
            t_id = t.get("id")
            content = t.get("content", "").strip()
            escaped_content = _escape_html(content)
            due_info = t.get("due") or {}
            due_val = due_info.get('string', due_info.get('datetime', due_info.get('date', '')))
            due_str = f" ({due_val})" if due_val else ""
            due_status = _format_todoist_due_status(t)
            if due_status:
                due_str += f" [{due_status}]"
            escaped_due_str = _escape_html(due_str)
            if t_id:
                lines.append(f"  \u2022 <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{escaped_due_str}")
            else:
                lines.append(f"  \u2022 {escaped_content}{escaped_due_str}")
    elif not overdue:
        lines.append("\u2705 No personal tasks due today \u2014 enjoy the free evening!")

    if personal_tasks:
        lines.append(f"\n\U0001f449 Pick one small action that fits being home now, or leave the list alone if this is family/recovery time.")

    lines.append(f"\n\U0001f552 {time_str}")
    return "\n".join(lines)


def _runtime_build_leave_briefing(tasks: List[Dict[str, Any]]) -> str:
    local_now = datetime.now(timezone.utc).astimezone(_runtime_local_tz())
    time_str = local_now.strftime('%I:%M %p').lstrip('0')

    errand_tasks = []
    for t in tasks:
        labels = [str(l).lower() for l in (t.get("labels") or [])]
        if "errands" in labels or "errand" in labels:
            errand_tasks.append(t)

    lines = [
        f"I received an away/leaving signal at {time_str}.",
        "I am only surfacing tasks that plausibly fit being out.",
        "",
    ]

    if errand_tasks:
        lines.append(f"\U0001f4dd You have {len(errand_tasks)} errand{'s' if len(errand_tasks) != 1 else ''} you could tackle while you're out:")
        for t in errand_tasks[:10]:
            t_id = t.get("id")
            content = t.get("content", "").strip()
            escaped_content = _escape_html(content)
            due_info = t.get("due") or {}
            due_val = due_info.get('string', due_info.get('date', ''))
            due_str = f" (due {due_val})" if due_val else ""
            escaped_due_str = _escape_html(due_str)
            if t_id:
                lines.append(f"  \u2022 <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{escaped_due_str}")
            else:
                lines.append(f"  \u2022 {escaped_content}{escaped_due_str}")
        lines.append("\nIf one errand naturally fits the trip, do it. If not, ignore this until you are back.")
    else:
        lines.append("No errands on the list \u2014 enjoy being out! \U0001f324\ufe0f")

    lines.append(f"\n\U0001f552 {time_str}")
    return "\n".join(lines)


def _handle_location_update(args: Dict[str, Any]) -> None:
    location = args.get("location", "").strip().lower()
    if not location:
        return
    now = datetime.now(timezone.utc).isoformat()
    state = _read_json(PRESENCE_STATE_PATH, {})
    old_location = state.get("location", "").strip().lower()

    state["location"] = location
    state["last_location_update"] = now
    state["confidence"] = 1.0
    state["source"] = args.get("source", "telegram-bot")
    state["label"] = f"Location update: {location}"
    state["timestamp"] = now
    _write_json(PRESENCE_STATE_PATH, state)

    # Trigger briefings on transitions
    time_since_last_update = 999999.0
    if state.get("last_location_update"):
        try:
            last_ts = datetime.fromisoformat(state["last_location_update"])
            now_ts = datetime.fromisoformat(now)
            time_since_last_update = (now_ts - last_ts).total_seconds()
        except Exception:
            pass

    should_trigger_arrival = False
    if location in {"home", "desk"}:
        if old_location == "away" or old_location in {"", "unknown"}:
            should_trigger_arrival = True
        elif old_location == location and time_since_last_update > 1800:
            should_trigger_arrival = True
        elif old_location == "desk" and location == "home" and time_since_last_update > 1800:
            should_trigger_arrival = True

    if should_trigger_arrival:
        try:
            tasks = _focus_guard_read_todoist_tasks(filter="today | overdue")
            projects_map = {}
            with _http_client() as client:
                resp = client.get(f"{TODOIST_BASE}/projects", headers=_todoist_headers())
                if resp.status_code == 200:
                    results = resp.json().get("results") or []
                    for p in results:
                        projects_map[p["id"]] = p["name"]
            message = _runtime_build_arrive_briefing(tasks, projects_map)
            dock_buttons = _build_hermes_dock(location)
            try:
                top_tasks = _get_top_high_priority_tasks(tasks, 3)
                for t in top_tasks:
                    dock_buttons.append({
                        "text": f"✅ {t.get('content')[:20]}...",
                        "callback_data": f"po:task_complete:{t.get('id')}"
                    })
            except Exception:
                pass
            _safe_send_telegram_message(message, force=True, parse_mode="HTML", buttons=dock_buttons)
        except Exception as e:
            pass
    elif old_location in {"home", "desk"} and location == "away":
        try:
            tasks = _focus_guard_read_todoist_tasks()
            message = _runtime_build_leave_briefing(tasks)
            dock_buttons = _build_hermes_dock(location)
            try:
                top_tasks = _get_top_high_priority_tasks(tasks, 3)
                for t in top_tasks:
                    dock_buttons.append({
                        "text": f"✅ {t.get('content')[:20]}...",
                        "callback_data": f"po:task_complete:{t.get('id')}"
                    })
            except Exception:
                pass
            _safe_send_telegram_message(message, force=True, parse_mode="HTML", buttons=dock_buttons)
        except Exception as e:
            pass

def handle_location_slash_command(raw_args: str) -> str:
    location = raw_args.strip()
    if not location:
        return "Usage: /location <state> (e.g. /location away, /location focus, /location desk)"

    _handle_location_update({"location": location, "source": "telegram-bot"})
    cleanup_res = _run_auto_cleanup_routines()
    logs = cleanup_res.get("logs", [])

    msg = f"📍 Location updated to: {location}"
    if logs:
        msg += "\n\n🧹 Auto-Cleanup triggered:\n" + "\n".join([f"• {l}" for l in logs])

    return msg



def handle_briefing_slash_command(command: str, args_str: str) -> str:
    from datetime import datetime, date
    tz = _runtime_local_tz()
    local_now = datetime.now(tz)
    today_date = local_now.date()
    tomorrow_date = today_date + timedelta(days=1)

    # Read all tasks
    try:
        all_tasks = _focus_guard_read_todoist_tasks()
    except Exception as e:
        return f"❌ Failed to fetch Todoist tasks: {e}"

    cmd = command.strip().lower().replace("/", "")

    if cmd == "show_hidden_tomorrow":
        hidden_tasks = []
        for t in all_tasks:
            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            if not due_date_str:
                continue
            try:
                date_part = due_date_str.split("T")[0]
                task_due_date = date.fromisoformat(date_part)
                if task_due_date == tomorrow_date:
                    lbls = [str(l).lower() for l in t.get("labels") or []]
                    role = _classify_task_role(t)
                    is_sub = t.get("parent_id") or t.get("parentId")
                    if role in ("reference", "checklist_item", "exclude_workload", "hermes_hidden") or is_sub or any(l in {"exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate"} for l in lbls):
                        hidden_tasks.append(t)
            except Exception:
                pass

        if not hidden_tasks:
            return "🔍 <b>Hidden/Excluded Tasks for Tomorrow:</b>\n\nNo hidden or excluded items found for tomorrow!"

        lines = ["🔍 <b>Hidden/Excluded Tasks for Tomorrow:</b>", "These items are excluded from your active workload count:", ""]
        for idx, t in enumerate(hidden_tasks, 1):
            escaped_content = _escape_html(t.get("content", "").strip())
            t_id = t.get("id")
            lbls = [l for l in t.get("labels") or []]
            lbl_str = f" [@{', @'.join(lbls)}]" if lbls else ""
            if t_id:
                lines.append(f"  {idx}. <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{lbl_str}")
            else:
                lines.append(f"  {idx}. {escaped_content}{lbl_str}")
        return "\n".join(lines)

    elif cmd == "show_task_debt":
        debt_tasks = []
        stale_tasks = []
        for t in all_tasks:
            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            if not due_date_str:
                continue
            try:
                date_part = due_date_str.split("T")[0]
                task_due_date = date.fromisoformat(date_part)
                if task_due_date < today_date:
                    overdue_days = (today_date - task_due_date).days
                    priority = int(t.get("priority") or 1)
                    if overdue_days >= 7 and priority < 4:
                        stale_tasks.append((t, overdue_days))
                    else:
                        debt_tasks.append((t, overdue_days))
            except Exception:
                pass

        lines = []
        if debt_tasks:
            lines.append("⏳ <b>Active Overdue Task Debt:</b>")
            for idx, (t, days) in enumerate(debt_tasks, 1):
                escaped_content = _escape_html(t.get("content", "").strip())
                t_id = t.get("id")
                days_str = f"({days} days overdue)"
                if t_id:
                    lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a> {days_str}")
                else:
                    lines.append(f"  • {escaped_content} {days_str}")
            lines.append("")
        else:
            lines.append("⏳ <b>Active Overdue Task Debt:</b>\nNo active overdue task debt! Excellent.")
            lines.append("")

        if stale_tasks:
            lines.append("🗄️ <b>Stale Backlog (Decayed Overdue):</b>")
            lines.append("These low-priority items have been overdue for 7+ days and are quarantined:")
            for idx, (t, days) in enumerate(stale_tasks, 1):
                escaped_content = _escape_html(t.get("content", "").strip())
                t_id = t.get("id")
                days_str = f"({days} days overdue)"
                if t_id:
                    lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a> {days_str}")
                else:
                    lines.append(f"  • {escaped_content} {days_str}")
        else:
            lines.append("🗄️ <b>Stale Backlog:</b>\nNo stale backlog items found.")

        return "\n".join(lines)

    elif cmd == "why_suppressed":
        hidden_counts = {
            "reference": 0,
            "checklist": 0,
            "routine": 0,
            "exclude_workload": 0,
            "stale": 0
        }

        for t in all_tasks:
            labels = [str(l).lower() for l in t.get("labels") or []]
            role = _classify_task_role(t)
            is_sub = t.get("parent_id") or t.get("parentId")

            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            is_overdue = False
            overdue_days = 0
            if due_date_str:
                try:
                    date_part = due_date_str.split("T")[0]
                    task_due_date = date.fromisoformat(date_part)
                    if task_due_date < today_date:
                        is_overdue = True
                        overdue_days = (today_date - task_due_date).days
                except Exception:
                    pass

            if is_overdue and overdue_days >= 7 and int(t.get("priority") or 1) < 4:
                hidden_counts["stale"] += 1
            elif "reference" in labels:
                hidden_counts["reference"] += 1
            elif "checklist_item" in labels or is_sub:
                hidden_counts["checklist"] += 1
            elif "routine" in labels:
                hidden_counts["routine"] += 1
            elif "exclude_workload" in labels:
                hidden_counts["exclude_workload"] += 1

        total = sum(hidden_counts.values())

        report = (
            f"🛡️ <b>Why Suppressed Explanation</b>\n\n"
            f"I filtered out <b>{total} total items</b> from your active briefing counts to protect your focus and keep your workspace clean:\n\n"
            f"• <b>{hidden_counts['reference']} Reference Notes</b> (rules, principles, or templates)\n"
            f"• <b>{hidden_counts['checklist']} Subtasks/Checklist items</b> (nested under parent actions)\n"
            f"• <b>{hidden_counts['routine']} Routines/Habits</b> (standard daily/weekly repeats)\n"
            f"• <b>{hidden_counts['exclude_workload']} Excluded Workload</b> (explicitly marked to bypass count)\n"
            f"• <b>{hidden_counts['stale']} Decayed Overdue Items</b> (overdue 7+ days without priority)\n\n"
            f"<i>By isolating these layers, Hermes ensures you are presented with a calm, highly-actionable tomorrow preview with zero noise!</i>"
        )
        return report

    elif cmd == "health_score":
        active_count = len(all_tasks)
        tomorrow_count = 0
        debt_count = 0
        stale_count = 0
        reference_count = 0
        high_priority_count = 0
        inbox_leakage_count = 0
        unscheduled_count = 0

        from collections import defaultdict
        name_groups = defaultdict(list)

        for t in all_tasks:
            content = str(t.get("content") or "").strip()
            content_clean = content.lower()
            name_groups[content_clean].append(t)

            labels = [str(l).lower() for l in t.get("labels") or []]
            priority = int(t.get("priority") or 1)
            project_id = str(t.get("project_id") or "").strip()

            is_ref = "reference" in labels
            is_family = "family_anchor" in labels
            is_fitness = "fitness_anchor" in labels

            if priority >= 3:
                high_priority_count += 1

            if not project_id:
                inbox_leakage_count += 1

            if is_ref:
                reference_count += 1

            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            if due_date_str:
                try:
                    date_part = due_date_str.split("T")[0]
                    task_due_date = date.fromisoformat(date_part)
                    if task_due_date == tomorrow_date:
                        if not is_ref and not is_family and not is_fitness:
                            tomorrow_count += 1
                    elif task_due_date < today_date:
                        overdue_days = (today_date - task_due_date).days
                        if overdue_days >= 7 and priority < 4:
                            stale_count += 1
                        else:
                            debt_count += 1
                except Exception:
                    pass
            else:
                if not is_ref:
                    unscheduled_count += 1

        duplicate_groups = [g for name, g in name_groups.items() if len(g) > 1]
        duplicate_candidates_count = sum(len(g) for g in duplicate_groups)

        deductions = 0
        deductions += min(15, debt_count * 1)
        deductions += min(20, stale_count * 2)
        deductions += min(15, reference_count * 2)
        deductions += min(15, len(duplicate_groups) * 3)

        priority_inflation = max(0, high_priority_count - 10)
        deductions += min(15, priority_inflation * 1)
        deductions += min(10, inbox_leakage_count * 2)
        deductions += min(10, unscheduled_count * 1)

        score = max(0, 100 - deductions)

        issues = []
        if stale_count >= 5:
            issues.append("stale backlog")
        if priority_inflation >= 5:
            issues.append("priority inflation")
        if inbox_leakage_count >= 5:
            issues.append("inbox leakage")

        main_issue = " + ".join(issues) if issues else "priority inflation + stale backlog"

        report = (
            f"📊 <b>Todoist Workspace Clarity: {score}/100</b>\n\n"
            f"• Active Tasks: {active_count}\n"
            f"• True Scheduled Tomorrow: {tomorrow_count}\n"
            f"• Overdue Task Debt: {debt_count}\n"
            f"• Quiet Backlog (Stale): {stale_count}\n"
            f"• Reference Tasks in Active List: {reference_count}\n"
            f"• Duplicate Candidates: {duplicate_candidates_count}\n"
            f"• High-Priority Tasks: {high_priority_count}\n"
            f"• Inbox Leakage: {inbox_leakage_count}\n\n"
            f"Main Issue: <b>{main_issue.capitalize()}</b>.\n"
            f"Recommended Step: A gentle 15-minute cleanup sweep, not more planning."
        )
        return report

    elif cmd == "entropy_check":
        stale_list = []
        duplicate_list = []
        no_project_list = []
        unscheduled_list = []
        postponed_list = []

        from collections import defaultdict
        name_groups = defaultdict(list)

        operator_state = _operator_read_state()
        due_shifts = operator_state.get("task_due_shifts", {})

        for t in all_tasks:
            content = str(t.get("content") or "").strip()
            content_clean = content.lower()
            name_groups[content_clean].append(t)

            project_id = str(t.get("project_id") or "").strip()
            t_id = t.get("id")

            if t_id and t_id in due_shifts and due_shifts[t_id].get("shifts", 0) >= 3:
                postponed_list.append((t, due_shifts[t_id]["shifts"]))

            if not project_id:
                no_project_list.append(t)

            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            if due_date_str:
                try:
                    date_part = due_date_str.split("T")[0]
                    task_due_date = date.fromisoformat(date_part)
                    if task_due_date < today_date:
                        overdue_days = (today_date - task_due_date).days
                        priority = int(t.get("priority") or 1)
                        if overdue_days >= 7 and priority < 4:
                            stale_list.append((t, overdue_days))
                except Exception:
                    pass
            else:
                if "reference" not in [l.lower() for l in t.get("labels") or []]:
                    unscheduled_list.append(t)

        for name, group in name_groups.items():
            if len(group) > 1:
                duplicate_list.extend(group)

        lines = ["🧹 <b>Weekly Workspace Simplicity Sweep</b>", "A gentle review to keep your lists fresh, clean, and simple:", ""]

        if duplicate_list:
            lines.append("<b>• Possible Duplicates:</b>")
            for t in duplicate_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped} (ID: {t.get('id')})")
            if len(duplicate_list) > 5:
                lines.append(f"  ... and {len(duplicate_list) - 5} more duplicate(s)")
            lines.append("")

        if stale_list:
            lines.append("<b>• Quiet Backlog (Overdue 7+ days):</b>")
            for t, days in stale_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped} ({days} days overdue)")
            if len(stale_list) > 5:
                lines.append(f"  ... and {len(stale_list) - 5} more stale task(s)")
            lines.append("")

        if postponed_list:
            lines.append("<b>• Tasks that Keep Moving (3+ reschedules):</b>")
            for t, shifts in postponed_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped} (postponed {shifts} times)")
            if len(postponed_list) > 5:
                lines.append(f"  ... and {len(postponed_list) - 5} more postponed task(s)")
            lines.append("")

        if no_project_list:
            lines.append("<b>• Unfiled Tasks (Inbox):</b>")
            for t in no_project_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped}")
            if len(no_project_list) > 5:
                lines.append(f"  ... and {len(no_project_list) - 5} more inbox item(s)")
            lines.append("")

        if unscheduled_list:
            lines.append("<b>• Tasks Waiting for a Time (No Due Date):</b>")
            for t in unscheduled_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped}")
            if len(unscheduled_list) > 5:
                lines.append(f"  ... and {len(unscheduled_list) - 5} more unscheduled item(s)")
            lines.append("")

        if len(lines) <= 3:
            lines.append("✨ <b>Everything is perfectly clear! Your workspace is beautifully organized.</b>")

        return "\n".join(lines)

    return f"Unknown command: /{cmd}"


def _auto_cleanup_stale_tasks(tasks: List[Dict[str, Any]]) -> List[str]:
    logs = []
    now = datetime.now(timezone.utc)
    for t in tasks:
        # Check for carry_until_done metadata
        metadata_str = t.get("description", "")
        if "carry_until_done" in metadata_str or "stale" in metadata_str:
            created = t.get("created_at")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if (now - dt).days >= 3 and t.get("due"):
                        # Demote task
                        with _http_client() as client:
                            url = f"{TODOIST_BASE}/tasks/{t['id']}"
                            labels = t.get("labels", [])
                            if "stale" not in labels:
                                labels.append("stale")
                            # Removing due date and adding label
                            payload = {"due_string": "no date", "labels": labels}
                            client.post(url, headers=_todoist_headers(), json=payload)
                        logs.append(f"Demoted stale task: {t.get('content')}")
                except Exception:
                    pass
    return logs

def _auto_cleanup_location_away(tasks: List[Dict[str, Any]]) -> List[str]:
    logs = []
    state = _read_json(PRESENCE_STATE_PATH, {})
    if state.get("location") != "away":
        return logs

    for t in tasks:
        # Here we look for skip_if_away rule or metadata
        if "skip_if_away" in t.get("description", "") and t.get("due"):
            with _http_client() as client:
                url = f"{TODOIST_BASE}/tasks/{t['id']}/close"
                client.post(url, headers=_todoist_headers())
            logs.append(f"Skipped task due to away location: {t.get('content')}")
    return logs

def _auto_cleanup_friday_purge(tasks: List[Dict[str, Any]]) -> List[str]:
    logs = []
    now = datetime.now(_runtime_local_tz())
    if now.weekday() == 4 and now.hour >= 17:
        for t in tasks:
            # Check inbox, no due date
            if not t.get("due") and not t.get("project_id"): # inbox
                # Assume parking lot is a specific project or just add label
                with _http_client() as client:
                    url = f"{TODOIST_BASE}/tasks/{t['id']}"
                    labels = t.get("labels", [])
                    if "parking_lot" not in labels:
                        labels.append("parking_lot")
                    client.post(url, headers=_todoist_headers(), json={"labels": labels})
                logs.append(f"Friday purge applied to: {t.get('content')}")
    return logs

def _auto_cleanup_quiet_hours(tasks: List[Dict[str, Any]]) -> List[str]:
    logs = []
    now = datetime.now(_runtime_local_tz())
    if now.hour >= 18:
        for t in tasks:
            # Check if business task due today
            if t.get("due") and ("business" in t.get("labels", []) or "work" in t.get("labels", [])):
                due_date = t["due"].get("date")
                if due_date and due_date.startswith(now.strftime("%Y-%m-%d")):
                    with _http_client() as client:
                        url = f"{TODOIST_BASE}/tasks/{t['id']}"
                        client.post(url, headers=_todoist_headers(), json={"due_string": "tomorrow morning"})
                    logs.append(f"Quiet hours deferral for: {t.get('content')}")
    return logs

def _run_auto_cleanup_routines() -> Dict[str, Any]:
    logs = []
    try:
        tasks = _focus_guard_read_todoist_tasks()
        logs.extend(_auto_cleanup_stale_tasks(tasks))
        logs.extend(_auto_cleanup_location_away(tasks))
        logs.extend(_auto_cleanup_friday_purge(tasks))
        logs.extend(_auto_cleanup_quiet_hours(tasks))
        logs.extend(_run_system_cleanliness_audit())
    except Exception as e:
        logs.append(f"Error running cleanup routines: {e}")
    return {"status": "success", "logs": logs}

_DAILY_THEMES = {
    0: "Strategic Planning & Clean Slate",
    1: "Deep Work Focus",
    2: "Deep Work Focus",
    3: "Deep Work Focus",
    4: "Clean Up & Friday Purge",
    5: "Rest, Recharge & Personal Habits",
    6: "Rest, Recharge & Personal Habits",
}


def _escape_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_send_telegram_message(text: str, **kwargs: Any) -> Dict[str, Any]:
    import inspect
    try:
        sig = inspect.signature(_focus_guard_send_telegram_message)
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if has_var_keyword:
            return _focus_guard_send_telegram_message(text, **kwargs)
        valid_kwargs = {}
        for k, v in kwargs.items():
            if k in sig.parameters:
                valid_kwargs[k] = v
        return _focus_guard_send_telegram_message(text, **valid_kwargs)
    except Exception:
        return _focus_guard_send_telegram_message(text)


def _get_projects_map() -> Dict[str, str]:
    projects_map = {}
    try:
        with _http_client() as client:
            resp = client.get(f"{TODOIST_BASE}/projects", headers=_todoist_headers())
            if resp.status_code == 200:
                results = resp.json().get("results") or []
                for p in results:
                    projects_map[p["id"]] = p["name"]
    except Exception:
        pass
    return projects_map

def _get_top_high_priority_tasks(tasks: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    # Filter out completed or invalid tasks
    active = [t for t in tasks if not t.get("completed") and t.get("id") and t.get("content")]
    # Sort descending by priority (Todoist priority: 4 is highest, 1 is lowest)
    active.sort(key=lambda t: int(t.get("priority", 1)), reverse=True)
    return active[:limit]


def _build_hermes_dock(location: str, local_now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    if local_now is None:
        local_now = datetime.now(timezone.utc).astimezone(_runtime_local_tz())

    hour = local_now.hour
    location = str(location or "").strip().lower()

    # Fetch projects map to find specific project links
    projects_map = _get_projects_map()

    work_proj_id = None
    personal_proj_id = None
    for pid, name in projects_map.items():
        name_lower = name.lower()
        if not work_proj_id and ("work" in name_lower or "business" in name_lower):
            work_proj_id = pid
        if not personal_proj_id and "personal" in name_lower:
            personal_proj_id = pid

    # Decide context
    is_work_hours = (9 <= hour < 17)

    buttons = []
    if location == "desk" or (location != "away" and is_work_hours):
        # Desk / Work context
        work_url = f"https://todoist.com/app/project/{work_proj_id}" if work_proj_id else "https://todoist.com/app/today"
        buttons.append({"text": "💼 Work App", "url": work_url})
        buttons.append({"text": "💼 Work (Watch)", "callback_data": f"po:show_list:work:{work_proj_id or 'none'}"})
        buttons.append({"text": "📥 Inbox App", "url": "https://todoist.com/app/inbox"})
        buttons.append({"text": "📥 Inbox (Watch)", "callback_data": "po:show_list:inbox"})
    elif location == "away":
        # Away context
        buttons.append({"text": "🏃 Errands App", "url": "https://todoist.com/app/label/errands"})
        buttons.append({"text": "🏃 Errands (Watch)", "callback_data": "po:show_list:errands"})
        buttons.append({"text": "📅 Today App", "url": "https://todoist.com/app/today"})
        buttons.append({"text": "📅 Today (Watch)", "callback_data": "po:show_list:today"})
    else:
        # Home / Evening context
        personal_url = f"https://todoist.com/app/project/{personal_proj_id}" if personal_proj_id else "https://todoist.com/app/today"
        buttons.append({"text": "⚓ Review Anchors", "callback_data": "po:review_anchors"})
        buttons.append({"text": "📅 Today (Watch)", "callback_data": "po:show_list:today"})
        buttons.append({"text": "🏠 Personal App", "url": personal_url})
        buttons.append({"text": "📥 Inbox App", "url": "https://todoist.com/app/inbox"})

    return buttons


def _parse_todoist_datetime(dt_str: str) -> datetime:
    if not dt_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    cleaned = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _get_recent_completions() -> List[Dict[str, Any]]:
    completed = []
    try:
        completed_activity_result = safe_call("completed_activity", "mcp_todoist_find_activity", {"objectType": "task", "eventType": "completed", "limit": 50})
        if completed_activity_result:
            completed = _todoist_activity_items(completed_activity_result)
    except Exception:
        pass

    if not completed:
        try:
            token = _env("TODOIST_API_TOKEN")
            if token:
                headers = {"Authorization": f"Bearer {token}"}
                with _http_client() as client:
                    resp = client.get("https://api.todoist.com/sync/v9/completed/get_all", headers=headers)
                    if resp.status_code == 200:
                        items = resp.json().get("items") or []
                        for item in items:
                            completed.append({
                                "task_id": item.get("task_id"),
                                "project_id": item.get("project_id"),
                                "content": item.get("content"),
                                "completed_at": item.get("completed_at"),
                            })
        except Exception:
            pass

    return completed


def _run_system_cleanliness_audit(now: Optional[datetime] = None) -> List[str]:
    logs = []
    if now is None:
        now = datetime.now(timezone.utc).astimezone(_runtime_local_tz())

    state = _operator_read_state()
    last_inbox_zero = state.get("last_inbox_zero_nudge_at")
    last_stale_project = state.get("last_stale_project_audit_at")

    inbox_audit_due = True
    project_audit_due = True

    if last_inbox_zero:
        try:
            last_inbox_dt = datetime.fromisoformat(last_inbox_zero)
            if (now - last_inbox_dt).total_seconds() < 24 * 3600:
                inbox_audit_due = False
        except Exception:
            pass

    if last_stale_project:
        try:
            last_proj_dt = datetime.fromisoformat(last_stale_project)
            if (now - last_proj_dt).total_seconds() < 24 * 3600:
                project_audit_due = False
        except Exception:
            pass

    if not inbox_audit_due and not project_audit_due:
        return logs

    try:
        tasks = _focus_guard_read_todoist_tasks()
    except Exception as e:
        logs.append(f"Audit failed to read Todoist tasks: {e}")
        return logs

    projects_map = _get_projects_map()
    inbox_project_id = None
    for pid, name in projects_map.items():
        if name.lower() == "inbox":
            inbox_project_id = pid
            break

    # 1. Inbox Zero Nudges
    if inbox_audit_due and inbox_project_id:
        lingering = []
        for t in tasks:
            if t.get("project_id") == inbox_project_id:
                created_at_str = t.get("created_at")
                if created_at_str:
                    created_at = _parse_todoist_datetime(created_at_str)
                    age_seconds = (now - created_at).total_seconds()
                    if age_seconds > 48 * 3600:
                        days = int(age_seconds / 86400)
                        lingering.append((t, days))

        if lingering:
            msg_lines = [
                "\U0001f4e5 <b>Inbox Cleanliness Nudge</b>",
                "You have tasks lingering in your Inbox for over 48 hours:",
            ]
            for idx, (t, days) in enumerate(lingering[:3], 1):
                t_id = t.get("id")
                escaped_content = _escape_html(t.get("content", ""))
                if t_id:
                    msg_lines.append(f"  {idx}️⃣ <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a> (added {days} days ago)")
                else:
                    msg_lines.append(f"  {idx}️⃣ {escaped_content} (added {days} days ago)")
            if len(lingering) > 3:
                for t, days in lingering[3:5]:
                    t_id = t.get("id")
                    escaped_content = _escape_html(t.get("content", ""))
                    if t_id:
                        msg_lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a> (added {days} days ago)")
                    else:
                        msg_lines.append(f"  • {escaped_content} (added {days} days ago)")
            msg_lines.append("\nConsider moving them to appropriate projects or processing them now!")

            sweep_buttons = []
            for idx, (t, _) in enumerate(lingering[:3], 1):
                t_id = t.get("id")
                if t_id:
                    sweep_buttons.append([
                        {"text": f"✅ {idx}", "callback_data": f"po:task_complete:{t_id}"},
                        {"text": f"📅 {idx}", "callback_data": f"po:task_defer:{t_id}"},
                        {"text": f"🗑️ {idx}", "callback_data": f"po:task_delete:{t_id}"}
                    ])

            try:
                _safe_send_telegram_message("\n".join(msg_lines), force=True, parse_mode="HTML", buttons=sweep_buttons)
                state["last_inbox_zero_nudge_at"] = now.isoformat()
                _operator_write_state(state)
                logs.append("Sent Inbox Zero audit nudge.")
            except Exception as e:
                logs.append(f"Failed to send Inbox Zero nudge: {e}")

    # 2. Stale Project Audits
    if project_audit_due:
        proj_tasks = {}
        for t in tasks:
            pid = t.get("project_id")
            if pid:
                proj_tasks.setdefault(pid, []).append(t)

        completions = _get_recent_completions()

        proj_completions = {}
        for c in completions:
            pid = c.get("project_id")
            if pid:
                proj_completions.setdefault(pid, []).append(c)

        stale_projects = []
        for pid, name in projects_map.items():
            if name.lower() == "inbox":
                continue
            active = proj_tasks.get(pid, [])
            if not active:
                continue

            oldest_age_days = 0
            for t in active:
                created_at_str = t.get("created_at")
                if created_at_str:
                    created_at = _parse_todoist_datetime(created_at_str)
                    age_days = (now - created_at).total_seconds() / 86400
                    if age_days > oldest_age_days:
                        oldest_age_days = age_days

            if oldest_age_days > 14:
                has_recent_completion = False
                for c in proj_completions.get(pid, []):
                    comp_at_str = c.get("completed_at")
                    if comp_at_str:
                        comp_at = _parse_todoist_datetime(comp_at_str)
                        if (now - comp_at).total_seconds() < 14 * 24 * 3600:
                            has_recent_completion = True
                            break
                if not has_recent_completion:
                    stale_projects.append((pid, name, int(oldest_age_days)))

        if stale_projects:
            msg_lines = [
                "\U0001f5c2\ufe0f <b>Stale Project Audit Alert</b>",
                "The following projects have active tasks but have seen no completion activity in over 14 days:",
            ]
            for pid, name, days in stale_projects[:5]:
                escaped_name = _escape_html(name)
                msg_lines.append(f"  \u2022 <a href=\"https://todoist.com/app/project/{pid}\">{escaped_name}</a> (oldest task is {days} days old)")
            msg_lines.append("\nConsider reviewing these projects to keep your workspace fresh and lightweight!")

            project_buttons = []
            for pid, name, _ in stale_projects[:5]:
                project_buttons.append({
                    "text": f"📁 {name}",
                    "callback_data": f"po:show_list:project:{pid}"
                })

            try:
                _safe_send_telegram_message("\n".join(msg_lines), force=True, parse_mode="HTML", buttons=project_buttons)
                state["last_stale_project_audit_at"] = now.isoformat()
                _operator_write_state(state)
                logs.append("Sent Stale Project audit nudge.")
            except Exception as e:
                logs.append(f"Failed to send Stale Project audit: {e}")

    return logs


def _build_mood_recommendation(mood_state: Dict[str, Any], local_now: datetime) -> str:
    mood_label = str((mood_state.get("last_mood") or {}).get("label") or "").lower()
    hour = local_now.hour

    is_morning = (5 <= hour < 12)
    is_low_energy = mood_label in {"low_energy", "frustrated", "confused", "tired", "stressed"}

    if is_low_energy:
        label_url = "https://todoist.com/app/label/low_energy"
        return f"\n\n\u2616 <b>Mood Match:</b> Feeling low on battery? No pressure. Let's make progress easy by starting a task under the <b><a href=\"{label_url}\">@low_energy</a></b> label."
    elif is_morning or mood_label in {"focused", "motivated", "productive"}:
        label_url = "https://todoist.com/app/label/deep_work"
        return f"\n\n\u2616 <b>Mood Match:</b> A fresh window is open. Ready for deep focus? Tackling a task with the <b><a href=\"{label_url}\">@deep_work</a></b> label is a great momentum builder."

    return ""
