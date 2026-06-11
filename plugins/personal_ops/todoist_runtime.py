from __future__ import annotations

from . import legacy_shared as _legacy_shared

globals().update({
    name: value
    for name, value in _legacy_shared.__dict__.items()
    if not name.startswith("__")
})

# This module was mechanically extracted from temp_personal_ops_tools.py.
# The compatibility wrapper injects cross-domain legacy globals after import.

def _todoist_headers() -> Dict[str, str]:
    token = _env_first("TODOIST_API_TOKEN", "TODOIST_API_KEY")
    if not token:
        raise ValueError("TODOIST_API_TOKEN or TODOIST_API_KEY is not configured in ~/.hermes/.env")
    return {"Authorization": f"Bearer {token}"}


def _clickup_headers() -> Dict[str, str]:
    token = _env("CLICKUP_API_TOKEN")
    if not token:
        raise ValueError("CLICKUP_API_TOKEN is not configured in ~/.hermes/.env")
    return {"Authorization": token, "Content-Type": "application/json"}


def _clickup_allowed_space_id() -> str:
    value = str(_env("CLICKUP_ALLOWED_SPACE_ID") or "").strip()
    if not value:
        raise ValueError("CLICKUP_ALLOWED_SPACE_ID is required")
    return value


def _clickup_allowed_folder_name() -> str:
    return str(_env("CLICKUP_ALLOWED_FOLDER_NAME") or "my stuff").strip()


def _resolve_clickup_boundary(client: Any) -> Dict[str, Any]:
    space_id = _clickup_allowed_space_id()
    folder_name = _clickup_allowed_folder_name().lower()

    folder_resp = client.get(f"{CLICKUP_BASE}/space/{space_id}/folder", headers=_clickup_headers())
    folder_resp.raise_for_status()
    folders = (folder_resp.json() or {}).get("folders") or []
    matches = [folder for folder in folders if str(folder.get("name") or "").strip().lower() == folder_name]
    if not matches:
        raise ValueError(f"Allowed ClickUp folder '{_clickup_allowed_folder_name()}' was not found in space {space_id}")
    if len(matches) > 1:
        raise ValueError(f"Multiple ClickUp folders matched '{_clickup_allowed_folder_name()}'; refusing to guess")

    folder = matches[0]
    folder_id = str(folder.get("id") or "").strip()
    list_resp = client.get(f"{CLICKUP_BASE}/folder/{folder_id}/list", headers=_clickup_headers())
    list_resp.raise_for_status()
    lists = (list_resp.json() or {}).get("lists") or []
    if not lists:
        raise ValueError(f"Allowed ClickUp folder '{folder.get('name')}' has no lists")

    clean_lists = [{"id": str(item.get("id")), "name": item.get("name")} for item in lists if item.get("id") is not None]
    return {
        "space_id": space_id,
        "folder": {"id": folder_id, "name": folder.get("name")},
        "lists": clean_lists,
        "list_ids": {item["id"] for item in clean_lists},
    }


def _public_clickup_boundary(boundary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not boundary:
        return boundary
    return {
        "space_id": boundary.get("space_id"),
        "folder": boundary.get("folder"),
        "lists": boundary.get("lists", []),
        "list_ids": sorted(boundary.get("list_ids", [])),
    }


def _twilio_auth() -> tuple[str, str, str]:
    sid = _env_first("PERSONAL_TWILIO_ACCOUNT_SID", "TWILIO_ACCOUNT_SID")
    token = _env_first("PERSONAL_TWILIO_AUTH_TOKEN", "TWILIO_AUTH_TOKEN")
    from_number = _env_first("PERSONAL_TWILIO_PHONE_NUMBER", "TWILIO_PHONE_NUMBER")
    if not sid or not token or not from_number:
        raise ValueError(
            "PERSONAL_TWILIO_ACCOUNT_SID/PERSONAL_TWILIO_AUTH_TOKEN/PERSONAL_TWILIO_PHONE_NUMBER "
            "or TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_PHONE_NUMBER must be configured in ~/.hermes/.env"
        )
    return sid, token, from_number


def _execute_todoist(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = payload.get("action")
    with _http_client() as client:
        if action == "add_task":
            body = {
                k: v
                for k, v in payload.items()
                if k
                in {
                    "content",
                    "description",
                    "project_id",
                    "section_id",
                    "labels",
                    "priority",
                    "due_string",
                    "due_datetime",
                }
                and v not in (None, "", [])
            }
            resp = client.post(f"{TODOIST_BASE}/tasks", headers=_todoist_headers(), json=body)
            resp.raise_for_status()
            return {"success": True, "action": action, "task": resp.json()}
        if action == "close_task":
            task_id = str(payload.get("task_id") or "").strip()
            if "id=" in task_id:
                task_id = task_id.split("id=")[-1]
            elif "/" in task_id:
                task_id = task_id.rstrip("/").split("/")[-1]
            if not task_id:
                raise ValueError("task_id is required")
            resp = client.post(f"{TODOIST_BASE}/tasks/{task_id}/close", headers=_todoist_headers())
            resp.raise_for_status()
            state = _adaptive_companion_read_state()
            state = _adaptive_companion_record_task_completion(
                state=state,
                task_id=task_id,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            latest = list(state.get("recent_interventions") or [])
            latest_item = dict(latest[-1] or {}) if latest else {}
            state = _adaptive_companion_refresh_insight_lenses(
                state=state,
                trigger={
                    "task_label": latest_item.get("task_label"),
                    "evidence": latest_item.get("message") or "",
                    "kind": latest_item.get("trigger") or "completion",
                },
                pattern=latest_item.get("pattern") or {"label": "momentum_present"},
                focus_state={"status": "needs_focus", "task_count": 0, "suspicious_tasks": []},
                now_hour=_adaptive_companion_now_local_hour(),
            )
            _adaptive_companion_write_state(state)
            return {"success": True, "action": action, "task_id": task_id}
        if action == "reopen_task":
            task_id = str(payload.get("task_id") or "").strip()
            if "id=" in task_id:
                task_id = task_id.split("id=")[-1]
            elif "/" in task_id:
                task_id = task_id.rstrip("/").split("/")[-1]
            if not task_id:
                raise ValueError("task_id is required")
            resp = client.post(f"{TODOIST_BASE}/tasks/{task_id}/reopen", headers=_todoist_headers())
            resp.raise_for_status()
            return {"success": True, "action": action, "task_id": task_id}
        if action == "update_task":
            task_id = str(payload.get("task_id") or "").strip()
            if "id=" in task_id:
                task_id = task_id.split("id=")[-1]
            elif "/" in task_id:
                task_id = task_id.rstrip("/").split("/")[-1]
            if not task_id:
                raise ValueError("task_id is required for update_task")
            body = {
                k: v
                for k, v in payload.items()
                if k
                in {
                    "content",
                    "description",
                    "due_string",
                    "due_date",
                    "due_datetime",
                    "labels",
                    "priority",
                }
                and v not in (None, "", [])
            }
            resp = client.post(f"{TODOIST_BASE}/tasks/{task_id}", headers=_todoist_headers(), json=body)
            resp.raise_for_status()
            return {"success": True, "action": action, "task_id": task_id, "task": resp.json()}
    raise ValueError(f"Unsupported Todoist approval action: {action}")


def _enrich_and_sort_todoist_hierarchy(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not tasks:
        return []

    task_map = {t.get("id"): t for t in tasks if t.get("id")}

    for t in tasks:
        parent_id = t.get("parent_id") or t.get("parentId")
        if parent_id and parent_id in task_map:
            t["is_subtask"] = True
            parent_task = task_map[parent_id]
            t["parent_content"] = str(parent_task.get("content") or parent_task.get("name") or parent_task.get("title") or "").strip()
            t["indentation_level"] = 1
        else:
            t["is_subtask"] = False
            t["parent_content"] = None
            t["indentation_level"] = 0

    roots = []
    children_map = {}

    for t in tasks:
        parent_id = t.get("parent_id") or t.get("parentId")
        if parent_id and parent_id in task_map:
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(t)
        else:
            roots.append(t)

    for pid in children_map:
        children_map[pid].sort(key=lambda x: (x.get("child_order") or 0, x.get("id") or ""))

    sorted_tasks = []
    seen = set()

    def traverse(task, depth):
        tid = task.get("id")
        if not tid or tid in seen:
            return
        seen.add(tid)
        task["indentation_level"] = depth
        sorted_tasks.append(task)

        if tid in children_map:
            for child in children_map[tid]:
                traverse(child, depth + 1)

    for root in roots:
        traverse(root, 0)

    for t in tasks:
        tid = t.get("id")
        if tid and tid not in seen:
            t["indentation_level"] = 0
            sorted_tasks.append(t)

    return sorted_tasks


def _render_hierarchical_markdown_list(tasks: List[Dict[str, Any]]) -> str:
    if not tasks:
        return "No tasks found."

    lines = []
    for t in tasks:
        level = t.get("indentation_level", 0)
        indent = "    " * level
        title = str(t.get("content") or t.get("name") or "").strip()
        t_id = t.get("id")

        lines.append(f"{indent}*   {title}")
        if t_id:
            lines.append(f"{indent}    Link: https://app.todoist.com/app/task/{t_id}")

    return "\n".join(lines)


def _todoist_native_call(args: Dict[str, Any]) -> Dict[str, Any]:
    action = str(args.get("action") or "list_tasks").strip().lower()
    with _http_client() as client:
        if action == "status":
            token = _env_first("TODOIST_API_TOKEN", "TODOIST_API_KEY")
            return {
                "success": True,
                "configured": bool(token),
                "token_masked": _mask(token),
                "connector": "native_api",
                "stable_primary": _todoist_connector_mode() in {"native", "native_primary", "api", "api_primary"},
                "auth_model": "personal_api_token",
            }
        if action in {"list_tasks", "search_tasks"}:
            params: Dict[str, Any] = {}
            if args.get("filter"):
                params["filter"] = args.get("filter")
            elif args.get("project_id"):
                params["project_id"] = args.get("project_id")
            elif args.get("section_id"):
                params["section_id"] = args.get("section_id")
            elif args.get("label"):
                params["label"] = args.get("label")
            tasks = _todoist_native_fetch_tasks(client, params, args.get("limit"))

            filter_str = str(args.get("filter") or "").strip().lower()
            if filter_str:
                from datetime import datetime, timedelta
                today_str = _operator_local_date()
                try:
                    today_dt = datetime.fromisoformat(today_str)
                    tomorrow_str = (today_dt + timedelta(days=1)).date().isoformat()
                except Exception:
                    tomorrow_str = ""

                filtered_tasks = []
                for t in tasks:
                    labels = [str(l).lower() for l in t.get("labels") or []]
                    excluded_labels = {
                        "exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate",
                        "someday", "maybe", "someday_maybe", "someday-maybe", "someday/maybe"
                    }
                    if any(l in excluded_labels for l in labels):
                        continue

                    due = t.get("due")
                    if isinstance(due, dict) and due.get("date"):
                        date_part = str(due["date"]).split("T")[0]
                        is_recurring = due.get("is_recurring") is True

                        # Skip overdue recurring routines to avoid past routine carryover clutter
                        if is_recurring and date_part < today_str:
                            continue

                        if "today" in filter_str and "overdue" in filter_str:
                            if date_part <= today_str:
                                filtered_tasks.append(t)
                        elif "today" in filter_str:
                            if date_part == today_str:
                                filtered_tasks.append(t)
                        elif "overdue" in filter_str:
                            if date_part < today_str:
                                filtered_tasks.append(t)
                        elif "tomorrow" in filter_str:
                            if tomorrow_str and date_part == tomorrow_str:
                                filtered_tasks.append(t)
                        else:
                            filtered_tasks.append(t)
                    else:
                        if not any(k in filter_str for k in ["today", "overdue", "tomorrow"]):
                            filtered_tasks.append(t)
                tasks = filtered_tasks

            query = str(args.get("query") or "").strip().lower()
            match_mode = "all"
            if query:
                ranked = _rank_records(
                    query=query,
                    records=tasks,
                    field_getter=lambda task: {
                        "title": task.get("content", ""),
                        "body": task.get("description", ""),
                        "tags": task.get("labels", []),
                        "state": task.get("section_id") or task.get("project_id") or "",
                        "recency_hint": task.get("due", {}),
                    },
                )
                tasks = [{**item["record"], "_why_matched": item["why_matched"], "_score": item["score"]} for item in ranked]
                match_mode = _match_mode_for_query(query)
                top_matches = [_compact_record_match(item, "content", "description") for item in ranked[:5]]
                summary = _summarize_record_matches(query, ranked, "content")
            else:
                tasks = _enrich_and_sort_todoist_hierarchy(tasks)
                top_matches = []
                summary = f"Found {len(tasks)} Todoist task(s)."
            _append_event("todoist_read", {"action": action, "count": len(tasks), "query": query, "match_mode": match_mode, "connector": "native"})
            formatted_list = _render_hierarchical_markdown_list(tasks)
            return {"success": True, "action": action, "count": len(tasks), "match_mode": match_mode, "summary": summary, "top_matches": top_matches, "tasks": tasks, "formatted_list": formatted_list}
        if action == "add_task":
            content = str(args.get("content") or "").strip()
            if not content:
                return json.loads(_tool_error("content is required for add_task"))
            return json.loads(_create_approval(
                tool_name="personal_todoist",
                action=action,
                summary=f"add Todoist task '{content[:80]}'",
                reason="This creates a real task in your Todoist workspace.",
                benefit="Hermes can add the task for you without manual entry.",
                payload=args,
            ))
        if action in {"close_task", "reopen_task"}:
            task_id = str(args.get("task_id") or "").strip()
            if not task_id:
                return json.loads(_tool_error("task_id is required"))
            verb = "close" if action == "close_task" else "reopen"
            return json.loads(_create_approval(
                tool_name="personal_todoist",
                action=action,
                summary=f"{verb} Todoist task {task_id}",
                reason="This changes the completion state of a real Todoist task.",
                benefit="Hermes can keep your task system in sync with chat decisions.",
                payload=args,
            ))
        if action == "update_task":
            task_id = str(args.get("task_id") or "").strip()
            if not task_id:
                return json.loads(_tool_error("task_id is required for update_task"))
            return json.loads(_create_approval(
                tool_name="personal_todoist",
                action=action,
                summary=f"update Todoist task {task_id}",
                reason="This updates the due date, labels, or content of a real Todoist task.",
                benefit="Hermes can keep your tasks accurately scheduled and synchronized.",
                payload=args,
            ))
    return json.loads(_tool_error(f"Unsupported Todoist action: {action}"))


def _todoist_native_fetch_tasks(client: Any, params: Dict[str, Any], requested_limit: Any = None) -> List[Dict[str, Any]]:
    base_params = dict(params or {})
    try:
        max_total = int(requested_limit) if requested_limit is not None else 500
    except Exception:
        max_total = 500
    max_total = max(1, min(max_total, 1000))
    page_limit = min(max_total, 100)
    tasks: List[Dict[str, Any]] = []
    cursor = str(base_params.pop("cursor", "") or "").strip()
    seen_cursors = set()
    for _ in range(20):
        page_params = dict(base_params)
        page_params["limit"] = min(page_limit, max_total - len(tasks))
        if cursor:
            page_params["cursor"] = cursor
        resp = client.get(f"{TODOIST_BASE}/tasks", headers=_todoist_headers(), params=page_params)
        resp.raise_for_status()
        payload = resp.json() or {}
        if isinstance(payload, list):
            page_tasks = payload
            next_cursor = ""
        else:
            page_tasks = payload.get("results") or payload.get("tasks") or []
            next_cursor = (
                payload.get("next_cursor")
                or payload.get("nextCursor")
                or ((payload.get("pagination") or {}).get("next_cursor"))
                or ((payload.get("pagination") or {}).get("nextCursor"))
                or ""
            )
        # Filter out reference, hidden, and checklist tasks from the active listings
        page_tasks_filtered = []
        for t in page_tasks:
            lbls = [str(l).lower() for l in t.get("labels") or []]
            if any(l in {"exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate"} for l in lbls):
                continue
            page_tasks_filtered.append(t)
        tasks.extend(page_tasks_filtered)
        if len(tasks) >= max_total:
            break
        cursor = str(next_cursor or "").strip()
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
    return tasks[:max_total]


def _todoist_connector_mode() -> str:
    raw = (os.getenv("TODOIST_CONNECTOR_MODE") or _env("TODOIST_CONNECTOR_MODE") or "native_primary").strip().lower()
    aliases = {
        "native": "native_primary",
        "api": "native_primary",
        "api_primary": "native_primary",
        "token": "native_primary",
        "token_primary": "native_primary",
        "mcp": "mcp_primary",
    }
    return aliases.get(raw, raw or "native_primary")


def _todoist_native_intelligence(args: Dict[str, Any], *, primary_error: Optional[str] = None) -> Dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 10), 50))
    filter_query = str(args.get("filter") or "today | overdue").strip()
    project_id = str(args.get("project_id") or args.get("projectId") or "").strip()
    list_args = {"action": "list_tasks", "filter": filter_query, "limit": limit}
    if project_id:
        list_args["project_id"] = project_id
    native = _todoist_native_call(list_args)
    tasks = list(native.get("tasks") or [])[:limit]
    summary = _todoist_intelligence_summary(tasks=tasks, completed=[], updated=[], project_health=None).replace(
        "Todoist MCP intelligence",
        "Todoist API-token intelligence",
    )
    if primary_error:
        summary = f"Todoist hosted MCP unavailable; stable API-token path is serving tasks. {summary}"
    return {
        "success": True,
        "action": "intelligence",
        "connector": "native_api",
        "auth_model": "personal_api_token",
        "fallback_used": bool(primary_error),
        "primary_error": primary_error,
        "filter": filter_query,
        "project_id": project_id or None,
        "summary": summary,
        "active_tasks": {
            "count": len(tasks),
            "tasks": tasks,
            "raw": native,
        },
        "activity": {
            "completed_count": 0,
            "updated_count": 0,
            "completed": [],
            "updated": [],
            "raw_completed": {"success": False, "reason": "native_api_path_does_not_query_activity"},
            "raw_updated": {"success": False, "reason": "native_api_path_does_not_query_activity"},
        },
        "productivity": {"success": False, "reason": "native_api_path_does_not_query_productivity"},
        "overview": {"success": False, "reason": "native_api_path_does_not_query_overview"},
        "project_health": None,
        "recommendations": [
            f"Pick one visible task and finish it first: {_todoist_task_title(tasks[0]) or tasks[0].get('id')}."
        ] if tasks else [],
        "errors": {"mcp": primary_error} if primary_error else {},
    }


def _todoist_mcp_tool_candidates(action: str) -> List[str]:
    names = {
        "list_tasks": ["mcp_todoist_find_tasks", "mcp_todoist_find_tasks_by_date", "mcp_todoist_get_tasks", "mcp_todoist_list_tasks", "mcp_todoist_search_tasks", "mcp_todoist_tasks"],
        "search_tasks": ["mcp_todoist_find_tasks", "mcp_todoist_search_tasks", "mcp_todoist_get_tasks", "mcp_todoist_list_tasks", "mcp_todoist_tasks"],
        "add_task": ["mcp_todoist_add_tasks", "mcp_todoist_create_task", "mcp_todoist_add_task"],
        "close_task": ["mcp_todoist_complete_tasks", "mcp_todoist_complete_task", "mcp_todoist_close_task"],
        "reopen_task": ["mcp_todoist_uncomplete_tasks", "mcp_todoist_reopen_task", "mcp_todoist_uncomplete_task"],
    }
    return names.get(action, [])


def _todoist_mcp_available() -> bool:
    try:
        from tools.registry import registry
    except Exception:
        return False
    try:
        has_tool = any(
            registry.get_entry(tool_name) is not None
            for action in ["list_tasks", "search_tasks", "add_task", "close_task", "reopen_task"]
            for tool_name in _todoist_mcp_tool_candidates(action)
        )
        if not has_tool:
            from tools.mcp_tool import discover_mcp_tools
            discover_mcp_tools()
    except Exception:
        pass
    for action in ["list_tasks", "search_tasks", "add_task", "close_task", "reopen_task"]:
        for tool_name in _todoist_mcp_tool_candidates(action):
            if registry.get_entry(tool_name) is not None:
                return True
    return False


def _todoist_priority_to_mcp(value: Any) -> str:
    mapping = {4: "p1", 3: "p2", 2: "p3", 1: "p4"}
    try:
        return mapping.get(int(value), "p4")
    except Exception:
        text = str(value or "").strip().lower()
        return text if text in {"p1", "p2", "p3", "p4"} else "p4"


def _todoist_mcp_payload(action: str, payload: Dict[str, Any], tool_name: str = "") -> Dict[str, Any]:
    result = {k: v for k, v in payload.items() if v not in (None, "", [])}
    if tool_name == "mcp_todoist_find_tasks_by_date":
        return {
            "startDate": "today",
            "overdueOption": "include-overdue",
            "limit": int(result.get("limit") or 50),
        }
    if action in {"list_tasks", "search_tasks"}:
        mcp_payload: Dict[str, Any] = {"limit": int(result.get("limit") or 50)}
        if result.get("filter"):
            mcp_payload["filter"] = result["filter"]
        elif result.get("query"):
            mcp_payload["searchText"] = result["query"]
        else:
            mcp_payload["filter"] = "today | overdue"
        return mcp_payload
    if action == "add_task":
        task: Dict[str, Any] = {"content": result.get("content") or result.get("task") or result.get("title")}
        if result.get("description"):
            task["description"] = result["description"]
        if result.get("due_string") or result.get("dueString") or result.get("due"):
            task["dueString"] = result.get("due_string") or result.get("dueString") or result.get("due")
        if result.get("priority"):
            task["priority"] = _todoist_priority_to_mcp(result["priority"])
        if result.get("labels"):
            task["labels"] = result["labels"]
        if result.get("project_id") or result.get("projectId"):
            task["projectId"] = result.get("project_id") or result.get("projectId")
        if result.get("section_id") or result.get("sectionId"):
            task["sectionId"] = result.get("section_id") or result.get("sectionId")
        if result.get("parent_id") or result.get("parentId"):
            task["parentId"] = result.get("parent_id") or result.get("parentId")
        return {"tasks": [task]}
    if action in {"close_task", "reopen_task"}:
        task_id = result.get("task_id") or result.get("id")
        return {"ids": [task_id]} if task_id else {"ids": []}
    return result


def _todoist_mcp_call(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from tools.registry import registry
    except Exception as exc:
        raise RuntimeError(f"MCP registry unavailable: {exc}") from exc
    try:
        if not any(registry.get_entry(tool_name) is not None for tool_name in _todoist_mcp_tool_candidates(action)):
            from tools.mcp_tool import discover_mcp_tools
            discover_mcp_tools()
    except Exception:
        pass
    last_error: Optional[str] = None
    for tool_name in _todoist_mcp_tool_candidates(action):
        if registry.get_entry(tool_name) is None:
            continue
        raw = registry.dispatch(tool_name, _todoist_mcp_payload(action, payload, tool_name))
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw_result": raw}
        if isinstance(parsed, dict) and parsed.get("error"):
            last_error = str(parsed.get("error"))
            continue
        if not isinstance(parsed, dict):
            parsed = {"result": parsed}
        structured = parsed.get("structuredContent")
        if isinstance(structured, dict):
            if isinstance(structured.get("tasks"), list):
                parsed.setdefault("tasks", structured["tasks"])
                parsed.setdefault("count", len(structured["tasks"]))
            if structured.get("totalCount") is not None:
                parsed.setdefault("total_count", structured.get("totalCount"))
            if structured.get("hasMore") is not None:
                parsed.setdefault("has_more", structured.get("hasMore"))
            if structured.get("nextCursor"):
                parsed.setdefault("next_cursor", structured.get("nextCursor"))
        if parsed.get("count") is not None and not parsed.get("summary"):
            parsed["summary"] = f"Todoist MCP returned {parsed['count']} task(s)."
        parsed.setdefault("success", True)
        parsed.setdefault("action", action)
        parsed["mcp_tool"] = tool_name
        return parsed
    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError(f"No registered Todoist MCP tool found for action {action}")


def _todoist_mcp_tool_call(tool_name: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from tools.registry import registry
    except Exception as exc:
        raise RuntimeError(f"MCP registry unavailable: {exc}") from exc
    try:
        if registry.get_entry(tool_name) is None:
            from tools.mcp_tool import discover_mcp_tools
            discover_mcp_tools()
    except Exception:
        pass
    if registry.get_entry(tool_name) is None:
        raise RuntimeError(f"No registered MCP tool found: {tool_name}")
    raw = registry.dispatch(tool_name, payload or {})
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {"raw_result": raw}
    if not isinstance(parsed, dict):
        parsed = {"result": parsed}
    if parsed.get("error"):
        raise RuntimeError(str(parsed.get("error")))
    parsed.setdefault("success", True)
    parsed["mcp_tool"] = tool_name
    return parsed


def _todoist_extract_structured_list(result: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    value = result.get(key)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        value = structured.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        for fallback_key in ["tasks", "projects", "activity", "events", "items"]:
            value = structured.get(fallback_key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _todoist_activity_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ["activity", "events", "items", "logs"]:
        items = _todoist_extract_structured_list(result, key)
        if items:
            return items
    return []


def _todoist_task_title(task: Dict[str, Any]) -> str:
    return str(task.get("content") or task.get("name") or task.get("title") or "").strip()


def _todoist_intelligence_summary(*, tasks: List[Dict[str, Any]], completed: List[Dict[str, Any]], updated: List[Dict[str, Any]], project_health: Optional[Dict[str, Any]]) -> str:
    top = [_todoist_task_title(task) for task in tasks[:3] if _todoist_task_title(task)]
    parts = [
        f"Todoist MCP intelligence: {len(tasks)} active today/overdue task(s), {len(completed)} recent completion event(s), {len(updated)} recent update event(s)."
    ]
    if top:
        parts.append("Highest-friction visible tasks: " + "; ".join(top) + ".")
    if project_health:
        health_text = ""
        structured = project_health.get("structuredContent")
        if isinstance(structured, dict):
            health_text = str(structured.get("healthStatus") or structured.get("status") or structured.get("summary") or "").strip()
        if not health_text:
            health_text = str(project_health.get("summary") or project_health.get("result") or "").strip()
        if health_text:
            parts.append(f"Project health signal: {health_text[:220]}.")
    if not completed and tasks:
        parts.append("No recent completion signal was found; prefer one concrete completion over another reminder.")
    return " ".join(parts)


def _todoist_mcp_intelligence(args: Dict[str, Any]) -> Dict[str, Any]:
    if not _todoist_mcp_available():
        raise RuntimeError("Todoist MCP is not available")
    limit = max(1, min(int(args.get("limit") or 10), 50))
    filter_query = str(args.get("filter") or "today | overdue").strip()
    project_id = str(args.get("project_id") or args.get("projectId") or "").strip()
    errors: Dict[str, str] = {}

    def safe_call(label: str, tool_name: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            return _todoist_mcp_tool_call(tool_name, payload)
        except Exception as exc:
            errors[label] = str(exc)
            return {"success": False, "error": str(exc), "mcp_tool": tool_name}

    active_tasks_result = safe_call("active_tasks", "mcp_todoist_find_tasks", {"filter": filter_query, "limit": limit})
    completed_activity_result = safe_call("completed_activity", "mcp_todoist_find_activity", {"objectType": "task", "eventType": "completed", "limit": limit})
    updated_activity_result = safe_call("updated_activity", "mcp_todoist_find_activity", {"objectType": "task", "eventType": "updated", "limit": limit})
    productivity_result = safe_call("productivity_stats", "mcp_todoist_get_productivity_stats", {})
    overview_result = safe_call("overview", "mcp_todoist_get_overview", {"projectId": project_id} if project_id else {})
    project_health_result = None
    if project_id:
        project_health_result = safe_call("project_health", "mcp_todoist_get_project_health", {"projectId": project_id, "includeContext": bool(args.get("include_context"))})

    tasks = _todoist_extract_structured_list(active_tasks_result, "tasks")
    completed = _todoist_activity_items(completed_activity_result)
    updated = _todoist_activity_items(updated_activity_result)
    recommendations: List[str] = []
    if tasks:
        recommendations.append(f"Pick one visible task and finish it first: {_todoist_task_title(tasks[0]) or tasks[0].get('id')}.")
    if len(tasks) >= 8:
        recommendations.append("The active list is large; reschedule, delete, or merge at least three low-value tasks before adding new ones.")
    if not completed and tasks:
        recommendations.append("No completion activity came back from MCP; use the next nudge to drive a finish, not another planning pass.")
    if updated and not completed:
        recommendations.append("There is update activity without completion activity; watch for task-shuffling disguised as progress.")
    if project_id and project_health_result and project_health_result.get("success"):
        recommendations.append("Use the project health result to choose the next unblock, not just the highest-priority task.")

    return {
        "success": True,
        "action": "intelligence",
        "connector": "mcp",
        "fallback_used": False,
        "filter": filter_query,
        "project_id": project_id or None,
        "summary": _todoist_intelligence_summary(
            tasks=tasks,
            completed=completed,
            updated=updated,
            project_health=project_health_result,
        ),
        "active_tasks": {
            "count": len(tasks),
            "tasks": tasks,
            "raw": active_tasks_result,
        },
        "activity": {
            "completed_count": len(completed),
            "updated_count": len(updated),
            "completed": completed,
            "updated": updated,
            "raw_completed": completed_activity_result,
            "raw_updated": updated_activity_result,
        },
        "productivity": productivity_result,
        "overview": overview_result,
        "project_health": project_health_result,
        "recommendations": recommendations,
        "errors": errors,
    }


def _todoist_intelligence(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = _todoist_connector_mode()
    if mode == "mcp_primary":
        try:
            return _todoist_mcp_intelligence(args)
        except Exception as exc:
            if _env("TODOIST_MCP_REQUIRED").strip().lower() in {"1", "true", "yes", "on"}:
                raise
            return _todoist_native_intelligence(args, primary_error=str(exc))
    try:
        return _todoist_native_intelligence(args)
    except Exception as exc:
        # Keeps old unit tests and diagnostic shells usable when they provide a
        # mocked MCP path but no local Todoist token. In production the API
        # token path should succeed and hosted MCP should remain optional.
        try:
            mcp_result = _todoist_mcp_intelligence(args)
            mcp_result["fallback_used"] = True
            mcp_result["primary_error"] = str(exc)
            return mcp_result
        except Exception:
            raise exc


_TASK_VERBS = {
    "add", "archive", "ask", "book", "buy", "call", "cancel", "check", "choose", "clean", "close",
    "confirm", "create", "decide", "delete", "draft", "email", "finish", "find", "fix", "follow",
    "get", "make", "message", "move", "open", "order", "pay", "pick", "plan", "prepare", "publish",
    "read", "repair", "reply", "reschedule", "review", "schedule", "send", "set", "ship", "split",
    "start", "submit", "test", "update", "write",
}


def _operator_read_state() -> Dict[str, Any]:
    state = _read_json(OPERATOR_STATE_PATH, {})
    return state if isinstance(state, dict) else {}


def _operator_write_state(state: Dict[str, Any]) -> None:
    _write_json(OPERATOR_STATE_PATH, state)


def _operator_memory_default_state() -> Dict[str, Any]:
    return {
        "memories": [],
        "rules": [],
        "task_metadata": {},
        "approval_bundles": [],
    }


def _operator_memory_read_state() -> Dict[str, Any]:
    data = _read_json(OPERATOR_MEMORY_PATH, _operator_memory_default_state())
    if not isinstance(data, dict):
        return _operator_memory_default_state()
    state = _operator_memory_default_state()
    state.update(data)
    if not isinstance(state.get("memories"), list):
        state["memories"] = []
    if not isinstance(state.get("rules"), list):
        state["rules"] = []
    if not isinstance(state.get("task_metadata"), dict):
        state["task_metadata"] = {}
    if not isinstance(state.get("approval_bundles"), list):
        state["approval_bundles"] = []
    return state


def _operator_memory_write_state(state: Dict[str, Any]) -> None:
    _write_json(OPERATOR_MEMORY_PATH, state)


def _self_improve_proposals_read() -> Dict[str, Any]:
    data = _read_json(SELF_IMPROVE_PROPOSALS_PATH, {"proposals": []})
    if not isinstance(data, dict):
        return {"proposals": []}
    proposals = list(data.get("proposals") or [])
    return {"proposals": [item for item in proposals if isinstance(item, dict)]}


def _self_improve_proposals_write(data: Dict[str, Any]) -> None:
    _write_json(SELF_IMPROVE_PROPOSALS_PATH, data)


def _self_improve_pipelines_read() -> Dict[str, Any]:
    data = _read_json(SELF_IMPROVE_PIPELINES_PATH, {"pipelines": []})
    if not isinstance(data, dict):
        return {"pipelines": []}
    pipelines = list(data.get("pipelines") or [])
    return {"pipelines": [item for item in pipelines if isinstance(item, dict)]}


def _self_improve_pipelines_write(data: Dict[str, Any]) -> None:
    _write_json(SELF_IMPROVE_PIPELINES_PATH, data)


def _todoist_rules_read_state() -> Dict[str, Any]:
    data = _read_json(TODOIST_RULES_PATH, {"task_metadata": {}, "rules": []})
    if not isinstance(data, dict):
        return {"task_metadata": {}, "rules": []}
    metadata = data.get("task_metadata") if isinstance(data.get("task_metadata"), dict) else {}
    rules = list(data.get("rules") or [])
    return {"task_metadata": metadata, "rules": [item for item in rules if isinstance(item, dict)]}


def _todoist_rules_write_state(data: Dict[str, Any]) -> None:
    _write_json(TODOIST_RULES_PATH, data)


def _operator_local_date(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(_runtime_local_tz()).date().isoformat()


def _operator_parse_task_due(task: Dict[str, Any]) -> Optional[datetime]:
    due = task.get("due") if isinstance(task.get("due"), dict) else None
    value = (
        task.get("dueDate")
        or task.get("deadlineDate")
        or (due or {}).get("datetime")
        or (due or {}).get("date")
    )
    if not value:
        return None
    text = str(value)
    try:
        if len(text) == 10:
            return datetime.fromisoformat(text).replace(tzinfo=_runtime_local_tz()).astimezone(timezone.utc)
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _operator_task_id(task: Dict[str, Any]) -> str:
    return str(task.get("id") or task.get("task_id") or "").strip()


def _operator_task_description(task: Dict[str, Any]) -> str:
    return str(task.get("description") or task.get("note") or "").strip()


def _operator_task_project(task: Dict[str, Any]) -> str:
    return str(task.get("project") or task.get("projectName") or task.get("projectId") or task.get("project_id") or "").strip()


def _operator_task_priority(task: Dict[str, Any]) -> int:
    value = task.get("priority")
    if isinstance(value, str) and value.lower().startswith("p"):
        try:
            return max(1, 5 - int(value[1:]))
        except Exception:
            return 1
    try:
        return int(value or 1)
    except Exception:
        return 1


def _operator_task_labels(task: Dict[str, Any]) -> List[str]:
    labels = task.get("labels") or []
    return [str(item).lower() for item in labels if str(item).strip()] if isinstance(labels, list) else []


def _operator_task_shape(task: Dict[str, Any]) -> Dict[str, Any]:
    title = _todoist_task_title(task)
    desc = _operator_task_description(task)
    lowered = title.lower().strip()
    words = [w.strip(":-_/,.()[]{}").lower() for w in title.split() if w.strip(":-_/,.()[]{}")]
    issues: List[str] = []
    repair_options: List[str] = []
    if not title:
        issues.append("empty_title")
    if not words or words[0] not in _TASK_VERBS:
        issues.append("no_clear_verb")
    if len(words) <= 2:
        issues.append("too_short_or_category_like")
    vague_terms = ["admin", "cleanup", "stuff", "things", "misc", "soon", "asap", "do as soon as possible", "todo", "follow up", "website", "social media", "taxes", "subscriptions"]
    if any(term in lowered for term in vague_terms):
        issues.append("vague_or_junk_drawer_title")
    hidden_lines = [line for line in desc.splitlines() if line.strip().startswith(("-", "*", "1.", "2.", "3."))]
    if len(hidden_lines) >= 2:
        issues.append("description_hides_subtasks")
    if any(sep in lowered for sep in [" and ", " / ", ",", "&"]):
        issues.append("possibly_multiple_actions")
    if "reference" in _operator_task_labels(task):
        issues.append("reference_material_mixed_with_tasks")
    score = max(0.05, 1.0 - (0.16 * len(issues)))
    if "do as soon as possible" in lowered or "admin" in lowered:
        repair_options.extend(["Move one named admin item forward", "Split this into the next visible action", "Delete or park it if it is not actionable today"])
    if not repair_options:
        repair_options.append("Rewrite as: verb + object + finish condition")
    return {
        "task_id": _operator_task_id(task),
        "title": title,
        "shape_score": round(score, 2),
        "issues": issues,
        "recommended_fix": repair_options[0],
        "repair_options": repair_options[:4],
    }


def _operator_update_avoidance_memory(state: Dict[str, Any], tasks: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    memory = dict(state.get("sticky_tasks") or {})
    today = _operator_local_date(now)
    for task in tasks:
        task_id = _operator_task_id(task)
        if not task_id:
            continue
        due = _operator_parse_task_due(task)
        is_overdue = bool(due and due.astimezone(_runtime_local_tz()).date().isoformat() < today)
        rec = dict(memory.get(task_id) or {})
        rec.setdefault("task_id", task_id)
        rec.setdefault("first_seen", now.isoformat())
        rec["last_seen"] = now.isoformat()
        rec["title"] = _todoist_task_title(task)
        rec["project"] = _operator_task_project(task)
        rec["times_seen"] = int(rec.get("times_seen") or 0) + 1
        rec["times_overdue"] = int(rec.get("times_overdue") or 0) + (1 if is_overdue else 0)
        shape = _operator_task_shape(task)
        rec["shape_score"] = shape["shape_score"]
        raw = min(1.0, (rec["times_seen"] * 0.08) + (rec["times_overdue"] * 0.16) + ((1.0 - shape["shape_score"]) * 0.35))
        rec["avoidance_score"] = round(raw, 2)
        if "description_hides_subtasks" in shape["issues"] or shape["shape_score"] < 0.55:
            rec["suspected_blocker"] = "unclear_next_action"
            rec["recommended_strategy"] = "task_repair"
        elif rec["times_overdue"] >= 2:
            rec["suspected_blocker"] = "admin_friction"
            rec["recommended_strategy"] = "direct_10_minute_action"
        else:
            rec["suspected_blocker"] = "unknown"
            rec["recommended_strategy"] = "operator_check"
        memory[task_id] = rec
    active_ids = {_operator_task_id(task) for task in tasks}
    for task_id, rec in list(memory.items()):
        if task_id not in active_ids and rec.get("completed") is not True:
            rec["last_absent"] = now.isoformat()
            rec["completed"] = True
            memory[task_id] = rec
    state["sticky_tasks"] = dict(sorted(memory.items(), key=lambda item: float((item[1] or {}).get("avoidance_score") or 0), reverse=True)[:80])
    return state


def _operator_analyze_noise(tasks: List[Dict[str, Any]], shapes: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    local_today = now.astimezone(_runtime_local_tz()).date()
    overdue = 0
    old_overdue = 0
    recurring = 0
    reference = 0
    high_priority = 0
    for task in tasks:
        due = _operator_parse_task_due(task)
        if due and due.astimezone(_runtime_local_tz()).date() < local_today:
            overdue += 1
            if (local_today - due.astimezone(_runtime_local_tz()).date()).days >= 3:
                old_overdue += 1
        if task.get("recurring") or (isinstance(task.get("due"), dict) and task["due"].get("is_recurring")):
            recurring += 1
        if "reference" in _operator_task_labels(task):
            reference += 1
        if _operator_task_priority(task) >= 4 or str(task.get("priority")).lower() == "p1":
            high_priority += 1
    vague = len([shape for shape in shapes if shape["shape_score"] < 0.65])
    hidden = len([shape for shape in shapes if "description_hides_subtasks" in shape["issues"]])
    score = min(1.0, (overdue * 0.07) + (old_overdue * 0.10) + (vague * 0.08) + (hidden * 0.08) + (reference * 0.04) + max(0, len(tasks) - 10) * 0.03)
    if score >= 0.75:
        status = "noisy"
    elif score >= 0.45:
        status = "getting_noisy"
    elif score >= 0.2:
        status = "moderate"
    else:
        status = "clean"
    sources: List[str] = []
    if overdue:
        sources.append("old_overdue_tasks" if old_overdue else "overdue_tasks")
    if vague:
        sources.append("vague_tasks")
    if hidden:
        sources.append("hidden_subtasks")
    if recurring >= 5:
        sources.append("recurring_task_load")
    if reference:
        sources.append("reference_tasks_in_active_view")
    return {
        "todoist_noise_score": round(score, 2),
        "status": status,
        "main_sources": sources,
        "counts": {
            "task_count": len(tasks),
            "overdue": overdue,
            "old_overdue": old_overdue,
            "recurring": recurring,
            "vague": vague,
            "hidden_subtasks": hidden,
            "reference": reference,
            "high_priority": high_priority,
        },
        "recommended_cleanup": [
            "Repair or delete stale overdue tasks",
            "Split hidden subtasks into visible actions",
            "Move reference material out of active task views",
        ][: max(1, min(3, len(sources) or 1))],
    }


def _todoist_lint_normalized_title(title: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in str(title or ""))
    return " ".join(cleaned.split())


def _todoist_lint_is_recurring(task: Dict[str, Any]) -> bool:
    due = task.get("due") if isinstance(task.get("due"), dict) else {}
    return bool(
        task.get("recurring")
        or task.get("isRecurring")
        or task.get("is_recurring")
        or (due or {}).get("is_recurring")
        or (due or {}).get("isRecurring")
    )


def _todoist_lint_hidden_lines(task: Dict[str, Any]) -> List[str]:
    desc = _operator_task_description(task)
    lines: List[str] = []
    for raw in desc.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if line.startswith(("-", "*")):
            lines.append(line.lstrip("-* ").strip())
        elif len(line) > 2 and line[0].isdigit() and line[1] in {".", ")"}:
            lines.append(line[2:].strip())
        elif lowered.startswith(("next:", "todo:", "then:", "also:")):
            lines.append(line.split(":", 1)[1].strip() if ":" in line else line)
    return [line for line in lines if line]


def _todoist_lint_task_evidence(task: Dict[str, Any]) -> str:
    parts = [f"task_id={_operator_task_id(task) or 'unknown'}", f"title={_todoist_task_title(task) or 'untitled'}"]
    project = _operator_task_project(task)
    if project:
        parts.append(f"project={project}")
    due = task.get("due") if isinstance(task.get("due"), dict) else {}
    due_text = str(task.get("dueDate") or (due or {}).get("date") or "").strip()
    if due_text:
        parts.append(f"due={due_text}")
    if _todoist_lint_is_recurring(task):
        parts.append("recurring=true")
    labels = _operator_task_labels(task)
    if labels:
        parts.append(f"labels={','.join(labels[:5])}")
    return ", ".join(parts)


def _todoist_lint_repair_id(kind: str, task_ids: List[str], suggested_title: str) -> str:
    payload = {"kind": kind, "task_ids": task_ids, "suggested_title": suggested_title}
    return "repair_" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def _todoist_lint_make_proposal(
    *,
    kind: str,
    task_ids: List[str],
    problem: str,
    evidence: List[str],
    suggested_title: str,
    suggested_description: str,
    due_date_change: str,
    risk: str,
    approval_needed: bool = True,
) -> Dict[str, Any]:
    clean_task_ids = [str(task_id) for task_id in task_ids if str(task_id).strip()]
    proposal = {
        "kind": kind,
        "task_ids": clean_task_ids,
        "problem": problem,
        "evidence": [str(item) for item in evidence if str(item).strip()],
        "suggested_title": suggested_title,
        "suggested_description": suggested_description,
        "due_date_change": due_date_change,
        "risk": risk,
        "approval_needed": bool(approval_needed),
        "actions": ["approve", "edit", "skip", "explain"],
    }
    proposal["id"] = _todoist_lint_repair_id(kind, clean_task_ids, suggested_title)
    return proposal


def _todoist_lint_title_is_incomplete(title: str) -> bool:
    words = [word.strip(":-_/,.()[]{}").lower() for word in str(title or "").split() if word.strip(":-_/,.()[]{}")]
    if not words:
        return False
    trailing = {"within", "for", "to", "from", "about", "with", "before", "after", "by"}
    return words[-1] in trailing or str(title or "").strip().endswith(("-", "/", ":", ","))


def _todoist_lint_vague_repair_title(task: Dict[str, Any]) -> str:
    title = _todoist_task_title(task)
    lowered = title.lower()
    if "laundry" in lowered:
        return "Move laundry forward: start, switch, fold, or mark no laundry needed"
    if "tax" in lowered:
        return "Find tax amount, deadline, and next payment step"
    if "subscription" in lowered or "cost" in lowered:
        return "Choose one subscription or cost to keep, cancel, or renegotiate"
    if "family" in lowered or "handoff" in lowered:
        return "Ask what needs help and take one concrete home task"
    if "read" in lowered:
        return f"Turn '{title}' into one action or move it to reference"
    return f"Rewrite '{title or 'this task'}' as verb + object + finish condition"


def _todoist_lint_task_proposals(task: Dict[str, Any], shape: Dict[str, Any], *, duplicate_task_ids: set[str]) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    task_id = _operator_task_id(task)
    title = _todoist_task_title(task)
    lowered = title.lower()
    hidden_lines = _todoist_lint_hidden_lines(task)
    labels = _operator_task_labels(task)
    evidence_base = [_todoist_lint_task_evidence(task)]

    if "do as soon as possible" in lowered or ("vague_or_junk_drawer_title" in shape.get("issues", []) and len(hidden_lines) >= 2):
        first_line = hidden_lines[0] if hidden_lines else "Choose the first concrete item"
        proposals.append(_todoist_lint_make_proposal(
            kind="junk_drawer_task",
            task_ids=[task_id],
            problem="This task is a junk drawer: it bundles multiple unrelated actions under a vague title.",
            evidence=evidence_base + [f"hidden_item={line}" for line in hidden_lines[:5]],
            suggested_title=first_line,
            suggested_description="Split each bullet into its own Todoist task with a visible finish condition. Do not keep this as one overdue catch-all item.",
            due_date_change="Replace the catch-all due date with realistic due dates on the split tasks.",
            risk="needs_user_choice",
        ))

    if len(hidden_lines) >= 3 and not any(item.get("kind") == "junk_drawer_task" for item in proposals):
        proposals.append(_todoist_lint_make_proposal(
            kind="hidden_subtask_bundle",
            task_ids=[task_id],
            problem="The description hides several subtasks, so Hermes can only nag the bundle instead of helping with the real next action.",
            evidence=evidence_base + [f"hidden_item={line}" for line in hidden_lines[:5]],
            suggested_title=hidden_lines[0],
            suggested_description="Extract the hidden lines into separate visible tasks, then keep only the next immediate action in Today.",
            due_date_change="Move only the first actionable item to Today; schedule the rest on realistic days.",
            risk="low_internal_draft",
        ))

    reference_like = "reference" in labels or ("identity statement" in lowered) or ("final program rules" in lowered)
    if reference_like:
        proposals.append(_todoist_lint_make_proposal(
            kind="reference_as_task",
            task_ids=[task_id],
            problem="This looks like reference material mixed into the active task list.",
            evidence=evidence_base + [f"shape_issues={','.join(shape.get('issues') or [])}"],
            suggested_title=f"Move '{title}' to reference review",
            suggested_description="Keep the material in notes or a low-frequency review task unless it produces one concrete next action today.",
            due_date_change="Remove from Today or schedule as a weekly/monthly review if it is still useful.",
            risk="low_internal_draft",
        ))

    if _todoist_lint_title_is_incomplete(title):
        proposals.append(_todoist_lint_make_proposal(
            kind="incomplete_title",
            task_ids=[task_id],
            problem="The title appears cut off or missing a concrete finish condition.",
            evidence=evidence_base + [f"title_ends_with={title.split()[-1] if title.split() else ''}"],
            suggested_title=_todoist_lint_vague_repair_title(task),
            suggested_description="First capture the missing amount, date, person, or finish condition. Then rewrite the task as one executable action.",
            due_date_change="Keep or set a due date only after the missing finish condition is known.",
            risk="missing_information",
        ))

    if (
        shape.get("shape_score", 1) < 0.7
        and task_id not in duplicate_task_ids
        and not any(item.get("kind") in {"junk_drawer_task", "reference_as_task", "incomplete_title"} for item in proposals)
    ):
        proposals.append(_todoist_lint_make_proposal(
            kind="vague_task",
            task_ids=[task_id],
            problem="The task is too vague or category-like for a useful nudge.",
            evidence=evidence_base + [f"shape_score={shape.get('shape_score')}", f"shape_issues={','.join(shape.get('issues') or [])}"],
            suggested_title=_todoist_lint_vague_repair_title(task),
            suggested_description="Rewrite it as a visible next action with a verb, object, and done condition.",
            due_date_change="Keep in Today only if the rewritten action can be done today.",
            risk="low_internal_draft",
        ))

    due = _operator_parse_task_due(task)
    if _todoist_lint_is_recurring(task) and due:
        local_today = datetime.now(timezone.utc).astimezone(_runtime_local_tz()).date()
        due_date = due.astimezone(_runtime_local_tz()).date()
        if due_date < local_today:
            proposals.append(_todoist_lint_make_proposal(
                kind="overdue_recurring_drift",
                task_ids=[task_id],
                problem="A recurring task is overdue, which can create a guilt loop instead of a useful routine.",
                evidence=evidence_base + [f"overdue_days={(local_today - due_date).days}"],
                suggested_title=title,
                suggested_description="Decide whether the recurrence is still useful. If yes, complete or reschedule the current instance cleanly. If not, pause or lower the frequency.",
                due_date_change="Review recurrence cadence before carrying it forward again.",
                risk="recurrence_change_requires_review",
            ))

    return proposals


def _todoist_lint_tasks(tasks: List[Dict[str, Any]], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    shapes = [_operator_task_shape(task) for task in tasks]
    proposals: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    duplicate_task_ids: set[str] = set()
    recurring_groups: Dict[str, List[Dict[str, Any]]] = {}
    for task in tasks:
        title = _todoist_task_title(task)
        normalized = _todoist_lint_normalized_title(title)
        if normalized and _todoist_lint_is_recurring(task):
            recurring_groups.setdefault(normalized, []).append(task)
    for group in recurring_groups.values():
        if len(group) < 2:
            continue
        task_ids = [_operator_task_id(task) for task in group]
        duplicate_task_ids.update(task_id for task_id in task_ids if task_id)
        title = _todoist_task_title(group[0])
        proposal = _todoist_lint_make_proposal(
            kind="duplicate_recurring_task",
            task_ids=task_ids,
            problem="Multiple recurring tasks have the same title, so Hermes may treat duplicates as separate obligations.",
            evidence=[_todoist_lint_task_evidence(task) for task in group],
            suggested_title=title,
            suggested_description="Keep the best recurring version, merge any useful description text, and retire the duplicate after review.",
            due_date_change="Keep one recurring schedule; remove or pause the duplicate only after approval.",
            risk="needs_user_choice",
        )
        proposals.append(proposal)
        seen_ids.add(proposal["id"])

    for task, shape in zip(tasks, shapes):
        for proposal in _todoist_lint_task_proposals(task, shape, duplicate_task_ids=duplicate_task_ids):
            if proposal["id"] in seen_ids:
                continue
            seen_ids.add(proposal["id"])
            proposals.append(proposal)

    by_kind: Dict[str, int] = {}
    for proposal in proposals:
        kind = str(proposal.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    noise = _operator_analyze_noise(tasks, shapes, now)
    return {
        "shapes": shapes,
        "anti_noise": noise,
        "proposals": proposals,
        "counts": {
            "tasks_scanned": len(tasks),
            "proposals": len(proposals),
            "by_kind": by_kind,
            "vague_or_low_shape": len([shape for shape in shapes if float(shape.get("shape_score") or 1) < 0.7]),
            "duplicates": by_kind.get("duplicate_recurring_task", 0),
        },
    }


def _todoist_lint_report_message(report: Dict[str, Any], request_id: Optional[str] = None) -> str:
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    proposals = list(report.get("proposals") or [])
    lines = [
        "Todoist repair report",
        report.get("summary") or f"Found {counts.get('proposals', len(proposals))} repair proposal(s).",
    ]
    for index, proposal in enumerate(proposals[:6], start=1):
        lines.append(f"{index}. {proposal.get('kind')}: {proposal.get('problem')}")
        lines.append(f"   Suggested: {proposal.get('suggested_title')}")
        evidence = list(proposal.get("evidence") or [])
        if evidence:
            lines.append(f"   Evidence: {evidence[0]}")
    if not proposals:
        lines.append("No repair proposals were supported by evidence right now.")
    if request_id:
        lines.extend([
            f"Request ID: {request_id}",
            f"Approve: personal_security(action='approve_request', request_id='{request_id}')",
            f"Deny: personal_security(action='deny_request', request_id='{request_id}')",
        ])
    return "\n".join(lines)


def _runtime_todoist_lint_report(args: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    filter_query = str(args.get("filter") or "today | overdue").strip()
    limit = max(1, min(int(args.get("limit") or 50), 50))
    source: Dict[str, Any] = {"connector": "mcp", "fallback_used": False, "filter": filter_query}
    try:
        intel = _todoist_intelligence({"filter": filter_query, "limit": limit, "project_id": args.get("project_id") or ""})
        tasks = list(((intel.get("active_tasks") or {}).get("tasks")) or [])
        source["connector"] = str(intel.get("connector") or "mcp")
        source["fallback_used"] = bool(intel.get("fallback_used"))
    except Exception as exc:
        native = _todoist_native_call({"action": "list_tasks", "filter": filter_query})
        tasks = list(native.get("tasks") or [])
        source = {"connector": "native", "fallback_used": True, "filter": filter_query, "primary_error": str(exc)}

    lint = _todoist_lint_tasks(tasks, now=now)
    proposals = list(lint.get("proposals") or [])
    report = {
        "success": True,
        "action": "todoist_lint_report",
        "generated_at": now.isoformat(),
        "summary": (
            f"Todoist repair report found {len(proposals)} proposal(s) across "
            f"{len(tasks)} active task(s)."
        ),
        "source": source,
        "counts": lint["counts"],
        "proposals": proposals,
        "task_shapes": lint["shapes"][:limit],
        "anti_noise": lint["anti_noise"],
        "approval_policy": "This report is draft-only. Todoist edits, deletes, duplicate retirement, recurrence changes, and bulk changes require separate explicit approval.",
    }
    report["telegram_message"] = _todoist_lint_report_message(report)

    create_approval = bool(args.get("create_approval", False))
    if create_approval and proposals:
        response = json.loads(_create_approval(
            tool_name="personal_runtime",
            action="apply_todoist_repair_report",
            summary="approve Todoist repair queue draft",
            reason="Hermes found task-system issues and should record the repair queue for review without editing Todoist invisibly.",
            benefit="You get a concrete repair queue with evidence, suggested titles, risks, and one-tap choices before any task changes happen.",
            payload={"action": "todoist_repair_apply", "report": report},
        ))
        request_id = str(response.get("request_id") or "")
        report["telegram_message"] = _todoist_lint_report_message(report, request_id=request_id)
        response = {**response, "action": "todoist_lint_report", "report": report, "telegram_message": report["telegram_message"]}
    else:
        response = {**report, "approval_required": False}

    if bool(args.get("send_telegram", False)):
        now_hour = datetime.now(timezone.utc).astimezone(_runtime_local_tz()).hour
        if bool(args.get("force_send", False)) or _telegram_messages_allowed_now(now_hour):
            _focus_guard_send_telegram_message(report["telegram_message"])
            response["sent"] = True
            response["send_reason"] = "sent"
        else:
            response["sent"] = False
            response["send_reason"] = "outside_hours"
    else:
        response["sent"] = False
        response["send_reason"] = "telegram_disabled"
    _append_event("todoist_lint_report", {"proposal_count": len(proposals), "task_count": len(tasks), "connector": source.get("connector")})
    return response


def _runtime_todoist_repair_apply(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    report = dict(payload.get("report") or {})
    record = {
        "status": "approved_draft_only",
        "approved_at": now.isoformat(),
        "applied": False,
        "reason": "Approval recorded the repair queue only; no Todoist task was edited, deleted, merged, or rescheduled.",
        "report": report,
    }
    _write_json(TODOIST_REPAIR_QUEUE_PATH, record)
    _append_event(
        "todoist_repair_queue_approved",
        {
            "proposal_count": int(((report.get("counts") or {}).get("proposals")) or len(report.get("proposals") or [])),
            "applied": False,
        },
    )
    return {
        "success": True,
        "action": "todoist_repair_apply",
        "applied": False,
        "queue_path": str(TODOIST_REPAIR_QUEUE_PATH),
        "summary": "Todoist repair queue was approved for review and saved. No Todoist edits were made.",
        "report": report,
    }
