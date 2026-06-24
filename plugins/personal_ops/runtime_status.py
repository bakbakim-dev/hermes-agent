from __future__ import annotations

from . import legacy_shared as _legacy_shared

globals().update({
    name: value
    for name, value in _legacy_shared.__dict__.items()
    if not name.startswith("__")
})

# This module was mechanically extracted from temp_personal_ops_tools.py.
# The compatibility wrapper injects cross-domain legacy globals after import.

def _load_approvals() -> Dict[str, Any]:
    data = _read_json(APPROVALS_PATH, {"pending": {}, "history": []})
    if not isinstance(data, dict):
        return {"pending": {}, "history": []}
    data.setdefault("pending", {})
    data.setdefault("history", [])
    return data


def _save_approvals(data: Dict[str, Any]) -> None:
    _write_json(APPROVALS_PATH, data)


SELF_IMPROVE_APPROVAL_TTL_SECONDS = 24 * 60 * 60
SELF_IMPROVE_APPROVAL_ACTIONS = {
    "apply_self_improve_report",
    "self_improve_pipeline_apply",
}


def _prune_stale_self_improve_approvals(approvals: Dict[str, Any], *, now_ts: Optional[int] = None) -> bool:
    """Expire stale self-improve approvals because their evidence is a snapshot."""
    now_ts = int(now_ts if now_ts is not None else _now())
    pending = approvals.get("pending") or {}
    if not isinstance(pending, dict):
        approvals["pending"] = {}
        return True

    expired: List[Dict[str, Any]] = []
    for request_id, item in list(pending.items()):
        if not isinstance(item, dict):
            continue
        if str(item.get("action") or "") not in SELF_IMPROVE_APPROVAL_ACTIONS:
            continue
        try:
            created_at = int(item.get("created_at") or 0)
        except (TypeError, ValueError):
            created_at = 0
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
        upstream = report.get("upstream") if isinstance(report.get("upstream"), dict) else {}
        stale_schema = (
            str(item.get("action") or "") == "apply_self_improve_report"
            and bool(report)
            and not str(upstream.get("origin_ref") or "").strip()
        )
        if created_at <= 0 or now_ts - created_at > SELF_IMPROVE_APPROVAL_TTL_SECONDS or stale_schema:
            expired.append(dict(item))
            pending.pop(request_id, None)

    if not expired:
        return False

    history = approvals.setdefault("history", [])
    for item in expired:
        history.append(
            {
                "request_id": item.get("request_id"),
                "event": "expired",
                "tool": item.get("tool"),
                "action": item.get("action"),
                "summary": item.get("summary"),
                "reason": "self_improve_snapshot_ttl",
                "ts": now_ts,
            }
        )
    return True


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    env_path = HERMES_HOME / ".env"
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if not raw or raw.lstrip().startswith("#") or "=" not in raw:
                continue
            key, val = raw.split("=", 1)
            if key.strip() == name:
                return val.strip()
    except Exception:
        pass
    return ""


def _env_first(*names: str) -> str:
    for name in names:
        value = _env(name)
        if value:
            return value
    return ""


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=30.0, follow_redirects=True)


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "..." + value[-4:]


def _read_yaml(path: Path, default: Any) -> Any:
    if yaml is None:
        return default
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _runtime_service_status(service_name: str = RUNTIME_SERVICE_NAME) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        state = (result.stdout or result.stderr or "").strip() or "unknown"
        return {
            "service": service_name,
            "active": state == "active",
            "state": state,
            "returncode": result.returncode,
            "active_since": _runtime_active_since(service_name),
        }
    except Exception as exc:
        return {
            "service": service_name,
            "active": False,
            "state": "unavailable",
            "error": str(exc),
        }


def _runtime_active_since(service_name: str = RUNTIME_SERVICE_NAME) -> Optional[str]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", service_name, "--property=ActiveEnterTimestamp", "--value"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        value = (result.stdout or result.stderr or "").strip()
        return value or None
    except Exception:
        return None


def _runtime_journal_lines(
    service_name: str = RUNTIME_SERVICE_NAME,
    lines: int = 200,
    since: Optional[str] = None,
) -> List[str]:
    try:
        command = ["journalctl", "--user", "-u", service_name]
        if since:
            command.extend(["--since", since])
        command.extend(["-n", str(lines), "--no-pager"])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        output = result.stdout if result.stdout else result.stderr
        return [line for line in output.splitlines() if line.strip()]
    except Exception:
        return []


def _runtime_incidents_from_lines(lines: List[str]) -> List[Dict[str, Any]]:
    incidents: List[Dict[str, Any]] = []
    for raw_line in lines:
        line = str(raw_line or "").strip()
        lower = line.lower()
        if not line:
            continue
        if "http 429" in lower or "tokens per minute limit exceeded" in lower:
            incidents.append({"kind": "rate_limit", "summary": "Provider rate limit hit", "raw": line})
        elif "http 413" in lower or "request too large for model" in lower:
            incidents.append({"kind": "request_too_large", "summary": "Fallback request exceeded model limits", "raw": line})
        elif "cannot compress further" in lower:
            incidents.append({"kind": "compression_failed", "summary": "Conversation compaction could not shrink context enough", "raw": line})
        elif "sms_webhook_url is required" in lower:
            incidents.append({"kind": "sms_misconfigured", "summary": "SMS gateway adapter is enabled without webhook configuration", "raw": line})
        elif "failed to detach context" in lower or "opentelemetry.context" in lower:
            incidents.append({"kind": "observability_error", "summary": "Langfuse/OpenTelemetry context error", "raw": line})
    return incidents


def _runtime_recent_incidents(limit: int = 20, service_name: str = RUNTIME_SERVICE_NAME) -> List[Dict[str, Any]]:
    since = _runtime_active_since(service_name)
    lines = _runtime_journal_lines(service_name=service_name, lines=max(limit * 8, 80), since=since)
    incidents = _runtime_incidents_from_lines(lines)
    if len(incidents) <= limit:
        return incidents
    return incidents[-limit:]


def _runtime_provider_chain(path: Path = HERMES_CONFIG_PATH) -> Dict[str, Any]:
    data = _read_yaml(path, {}) or {}
    model_cfg = data.get("model") or {}
    compression_cfg = data.get("compression") or {}
    fallbacks = data.get("fallback_providers") or []
    plugins_cfg = data.get("plugins") or {}
    enabled_plugins = plugins_cfg.get("enabled") or []
    return {
        "primary": {
            "provider": model_cfg.get("provider"),
            "model": model_cfg.get("default"),
        },
        "fallbacks": [
            {"provider": item.get("provider"), "model": item.get("model")}
            for item in fallbacks
            if isinstance(item, dict)
        ],
        "compression": {
            "protect_last_n": compression_cfg.get("protect_last_n"),
            "hygiene_hard_message_limit": compression_cfg.get("hygiene_hard_message_limit"),
        },
        "plugins_enabled": enabled_plugins if isinstance(enabled_plugins, list) else [],
    }


def _runtime_git_identity(repo_path: Optional[Path] = None) -> Dict[str, Any]:
    root = repo_path or Path(os.getenv("HERMES_REPO_ROOT") or Path(__file__).resolve().parents[2])
    git_dir = root / ".git"
    if not git_dir.exists():
        return {"repo_path": str(root), "available": False, "working_tree_state": "not_checked"}
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            commit_path = git_dir / ref
            commit = commit_path.read_text(encoding="utf-8").strip() if commit_path.exists() else ""
            branch = ref.rsplit("/", 1)[-1]
        else:
            commit = head
            branch = None
        return {
            "repo_path": str(root),
            "available": True,
            "branch": branch,
            "commit": commit[:12] if commit else None,
            "commit_full": commit or None,
            "working_tree_state": "not_checked",
            "state_note": "Git HEAD is read without shell access; uncommitted runtime overlays are not evaluated here.",
        }
    except Exception as exc:
        return {"repo_path": str(root), "available": False, "error": str(exc), "working_tree_state": "not_checked"}


def _runtime_hermes_version_status(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    try:
        from hermes_cli import __release_date__, __version__
    except Exception:
        __version__ = "unknown"  # type: ignore[assignment]
        __release_date__ = None  # type: ignore[assignment]

    provider_chain = _runtime_provider_chain()
    git_identity = _runtime_git_identity()
    primary = dict(provider_chain.get("primary") or {})
    provider = primary.get("provider") or "unknown"
    model = primary.get("model") or "unknown"
    return {
        "success": True,
        "action": "hermes_version_status",
        "hermes": {
            "package": "hermes-agent",
            "version": __version__,
            "release_date": __release_date__,
        },
        "runtime": {
            "pid": os.getpid(),
            "cwd": str(Path.cwd()),
            "hermes_home": str(HERMES_HOME),
        },
        "git": git_identity,
        "provider_chain": provider_chain,
        "summary": (
            f"Hermes Agent {__version__}"
            + (f" ({__release_date__})" if __release_date__ else "")
            + f"; primary model config: {provider}/{model}."
        ),
    }


def _runtime_hermes_update_request(args: Dict[str, Any]) -> Dict[str, Any]:
    version_status = _runtime_hermes_version_status({})
    upstream = _runtime_upstream_status(
        hours=int(args.get("hours") or 24),
        repo_path=Path(str(args.get("repo_path"))) if args.get("repo_path") else None,
    )
    behind = int(((upstream.get("local") or {}).get("behind")) or 0)
    origin_ref = str(((upstream.get("local") or {}).get("origin_ref")) or "origin/main")
    recent_count = int(upstream.get("recent_commit_count") or 0)
    updates_available = bool(behind > 0 or recent_count > 0)
    recommended_response = (
        "I can help start a Hermes update, but I cannot silently mutate code or deploy from Telegram. "
        "Updates are approval-gated: check upstream, create a branch/plan, run tests, show the diff, "
        "then deploy only after approval."
    )
    if not updates_available:
        recommended_response = (
            f"{recommended_response}\n\nCurrent check: Hermes appears current against the configured upstream "
            f"({origin_ref}: behind={behind}, recent upstream commits in window={recent_count})."
        )
    else:
        recommended_response = (
            f"{recommended_response}\n\nCurrent check: upstream changes may be available "
            f"({origin_ref}: behind={behind}, recent upstream commits in window={recent_count}). "
            "Safe next move: create a GitOps update proposal, not apply it blindly."
        )
    return {
        "success": True,
        "action": "hermes_update_request",
        "version_status": version_status,
        "upstream": upstream,
        "updates_available": updates_available,
        "approval_required": updates_available,
        "direct_update_allowed": False,
        "approval_policy": "code_update_requires_branch_tests_diff_approval_deploy_verify",
        "safe_next_actions": [
            {"tool": "personal_runtime", "args": {"action": "upstream_status"}, "purpose": "refresh upstream evidence"},
            {"tool": "personal_runtime", "args": {"action": "self_improve_pipeline", "mode": "propose"}, "purpose": "create an approval-gated branch/test/diff/rollback plan"},
        ],
        "recommended_response": recommended_response,
        "summary": "Hermes update requests are handled as approval-gated GitOps proposals, not direct Telegram mutations.",
    }


def _runtime_isolation_profile_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.orchestration_kernel import profiles_as_dict

    profiles = profiles_as_dict()
    requested = args.get("profile_name") or args.get("profile")
    if requested:
        profile_name = str(requested).strip()
        profiles = {profile_name: profiles[profile_name]} if profile_name in profiles else {}
    return {
        "success": True,
        "action": "isolation_profile_plan",
        "profiles": profiles,
        "summary": "Hermes profiles isolate personal ops, engineering, business, finance, and experiments so tools/context do not bleed across risk domains.",
    }


def _runtime_intention_gate(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.orchestration_kernel import evaluate_intention

    intent = str(args.get("intent") or args.get("request") or args.get("title") or "").strip()
    profile_name = str(args.get("profile_name") or args.get("profile") or "personal").strip()
    decision = evaluate_intention(intent, profile_name=profile_name)
    _append_event(
        "intention_gate",
        {
            "profile_name": decision.profile_name,
            "allowed": decision.allowed,
            "approval_required": decision.approval_required,
            "blocked_terms": decision.blocked_terms,
        },
    )
    return {"success": True, "action": "intention_gate", "decision": decision.to_dict()}


def _runtime_orchestration_job(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.orchestration_kernel import build_dispatch_plan, job_board_status, record_job

    mode = str(args.get("mode") or "status").strip().lower()
    if mode == "status":
        status = job_board_status(db_path=ORCHESTRATION_JOBS_DB_PATH, limit=int(args.get("limit") or 25))
        return {"success": True, "action": "orchestration_job", "mode": mode, **status}
    if mode == "plan":
        plan = build_dispatch_plan(
            title=str(args.get("title") or "Untitled Hermes job"),
            intent=str(args.get("intent") or ""),
            profile_name=str(args.get("profile_name") or args.get("profile") or "personal"),
        )
        return {"success": True, "action": "orchestration_job", "mode": mode, "dispatch_plan": plan}
    if mode == "create":
        job = record_job(
            db_path=ORCHESTRATION_JOBS_DB_PATH,
            profile_name=str(args.get("profile_name") or args.get("profile") or "personal"),
            title=str(args.get("title") or "Untitled Hermes job"),
            intent=str(args.get("intent") or ""),
            status=str(args.get("status") or "proposed"),
        )
        _append_event(
            "orchestration_job_created",
            {
                "job_id": job.get("job_id"),
                "profile_name": job.get("profile_name"),
                "status": job.get("status"),
                "approval_required": ((job.get("decision") or {}).get("approval_required")),
            },
        )
        return {
            "success": True,
            "action": "orchestration_job",
            "mode": mode,
            "job": job,
            "dispatch_plan": job.get("dispatch_plan"),
        }
    raise ValueError(f"Unsupported orchestration_job mode: {mode}")


def _runtime_summary(service: Dict[str, Any], incidents: List[Dict[str, Any]]) -> str:
    state = service.get("state")
    if not state:
        state = "active" if service.get("active") else "unknown"
    incident_count = len(incidents)
    qualifier = "current" if service.get("active_since") else "recent"
    return f"Hermes gateway is {state}. Found {incident_count} {qualifier} incident(s)."


def _runtime_default_repo_path() -> Path:
    configured = _env("HERMES_AGENT_REPO_PATH")
    if configured:
        return Path(configured).expanduser()
    current = Path("/home/ubuntu/hermes-agent-current")
    if current.exists():
        return current
    common = Path("/home/ubuntu/hermes-agent")
    if common.exists():
        return common
    return Path.cwd()


def _runtime_git_output(repo_path: Path, args: List[str], *, timeout: int = 20) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        output = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def _runtime_update_compare_branch(repo_path: Path) -> str:
    """Return the remote branch that represents this checkout's update target."""
    current_ok, current_output = _runtime_git_output(
        repo_path,
        ["rev-parse", "--abbrev-ref", "HEAD"],
    )
    current_branch = current_output.strip() if current_ok else ""
    if current_branch and current_branch != "HEAD":
        verify_ok, _ = _runtime_git_output(
            repo_path,
            ["rev-parse", "--verify", "--quiet", f"origin/{current_branch}"],
        )
        if verify_ok:
            return current_branch

    head_ok, head_output = _runtime_git_output(
        repo_path,
        ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
    )
    if head_ok:
        value = head_output.strip()
        if value.startswith("origin/"):
            return value.split("/", 1)[1]

    return "main"


def _runtime_local_git_status(repo_path: Path) -> Dict[str, Any]:
    repo_path = Path(repo_path)
    branch = _runtime_update_compare_branch(repo_path)
    origin_ref = f"origin/{branch}"
    fetch_ok, fetch_output = _runtime_git_output(repo_path, ["fetch", "origin", branch], timeout=45)
    behind_ok, behind_output = _runtime_git_output(repo_path, ["rev-list", "--count", f"HEAD..{origin_ref}"])
    head_ok, head_output = _runtime_git_output(repo_path, ["rev-parse", "--short", "HEAD"])
    origin_ok, origin_output = _runtime_git_output(repo_path, ["rev-parse", "--short", origin_ref])
    behind: Optional[int] = None
    if behind_ok:
        try:
            behind = int(str(behind_output).strip())
        except ValueError:
            behind = None
    return {
        "repo_path": str(repo_path),
        "fetch_ok": fetch_ok,
        "fetch_output": fetch_output if not fetch_ok else "",
        "behind": behind,
        "head": head_output if head_ok else None,
        "origin_branch": branch,
        "origin_ref": origin_ref,
        "origin": origin_output if origin_ok else None,
    }


def _runtime_fetch_recent_commits(*, hours: int = 24, repo: str = "NousResearch/hermes-agent") -> List[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(hours=max(int(hours), 1))).isoformat().replace("+00:00", "Z")
    commits: List[Dict[str, Any]] = []
    page = 1
    with _http_client() as client:
        while page <= 10:
            resp = client.get(
                f"https://api.github.com/repos/{repo}/commits",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Hermes personal runtime watcher"},
                params={"since": since, "per_page": 100, "page": page},
            )
            resp.raise_for_status()
            payload = resp.json() or []
            for item in payload:
                commit = item.get("commit") or {}
                author = commit.get("author") or {}
                message = str(commit.get("message") or "").splitlines()[0].strip()
                commits.append(
                    {
                        "sha": str(item.get("sha") or "")[:12],
                        "message": message,
                        "author": author.get("name"),
                        "date": author.get("date"),
                        "url": item.get("html_url"),
                    }
                )
            link_header = str(resp.headers.get("link") or "")
            if 'rel="next"' not in link_header:
                break
            page += 1
    return commits


def _runtime_upstream_summary(status: Dict[str, Any]) -> str:
    hours = int(status.get("hours") or 24)
    count = int(status.get("recent_commit_count") or 0)
    behind = (status.get("local") or {}).get("behind")
    if count:
        lead = f"Hermes upstream changed: {count} commit(s) in the last {hours}h."
    else:
        lead = f"No Hermes upstream commits in the last {hours}h."
    if behind is None:
        tail = "Local checkout status could not be determined."
    elif int(behind) > 0:
        origin_ref = (status.get("local") or {}).get("origin_ref") or "origin/main"
        tail = f"Local checkout is {behind} commit(s) behind {origin_ref}."
    else:
        origin_ref = (status.get("local") or {}).get("origin_ref") or "origin/main"
        tail = f"Local checkout is current with {origin_ref}."
    commits = list(status.get("recent_commits") or [])
    if commits:
        latest = str((commits[0] or {}).get("message") or "").strip()
        if latest:
            return f"{lead} Latest: {latest}. {tail}"
    return f"{lead} {tail}"


def _runtime_upstream_status(
    *,
    hours: int = 24,
    repo_path: Optional[Path] = None,
    repo: str = "NousResearch/hermes-agent",
) -> Dict[str, Any]:
    resolved_repo_path = Path(repo_path) if repo_path is not None else _runtime_default_repo_path()
    commits = _runtime_fetch_recent_commits(hours=hours, repo=repo)
    local = _runtime_local_git_status(resolved_repo_path)
    status = {
        "repo": repo,
        "hours": int(hours),
        "recent_commit_count": len(commits),
        "recent_commits": commits[:10],
        "local": local,
    }
    status["summary"] = _runtime_upstream_summary(status)
    return status


def _runtime_upstream_telegram_message(status: Dict[str, Any]) -> str:
    lines = ["Hermes Agent - Upstream Watch", str(status.get("summary") or "").strip()]
    for commit in list(status.get("recent_commits") or [])[:5]:
        sha = str(commit.get("sha") or "")[:7]
        message = str(commit.get("message") or "").strip()
        author = str(commit.get("author") or "").strip()
        suffix = f" ({author})" if author else ""
        lines.append(f"- {sha}: {message}{suffix}")
    return "\n".join(line for line in lines if line).strip()


def _runtime_write_event_state(data: Dict[str, Any]) -> None:
    _write_json(EVENT_ROUTER_STATE_PATH, data)


def _runtime_read_event_state() -> Dict[str, Any]:
    data = _read_json(EVENT_ROUTER_STATE_PATH, {"recent_events": [], "last_event": None})
    if not isinstance(data, dict):
        return {"recent_events": [], "last_event": None}
    data.setdefault("recent_events", [])
    data.setdefault("last_event", None)
    return data


def _runtime_local_tz() -> timezone:
    if ZoneInfo is not None:
        try:
            return ZoneInfo(HERMES_LOCAL_TIMEZONE)
        except Exception:
            pass
    return timezone.utc


def _presence_confidence_for_event(event_type: str, source: str) -> tuple[float, str]:
    source_l = source.lower()
    if event_type == "voice_memo_received" and "telegram" in source_l:
        return 0.85, "Telegram activity"
    if event_type == "wake" and "logon" in source_l:
        return 0.45, "Windows logon"
    if event_type == "desktop_unlocked":
        return 0.35, "desktop unlock signal"
    if event_type in {"leaving_house", "outing_request"}:
        return 0.70, "explicit outing request"
    return 0.50, event_type.replace("_", " ")


def _is_passive_presence_only_event(event_type: str, source: str) -> bool:
    source_l = source.lower()
    if event_type == "wake" and "logon" in source_l:
        return True
    if event_type == "desktop_unlocked" and ("windows" in source_l or "unlock" in source_l):
        return True
    if event_type == "activitywatch_heartbeat":
        return True
    return False


def _runtime_write_presence_signal(
    *,
    event_type: str,
    source: str,
    ts: datetime,
    override_confidence: Optional[float] = None,
    override_label: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    confidence, label = _presence_confidence_for_event(event_type, source)
    signal = {
        "ts": ts.isoformat(),
        "source": source,
        "event_type": event_type,
        "confidence": float(override_confidence if override_confidence is not None else confidence),
        "label": str(override_label or label),
    }
    if isinstance(extra, dict):
        for key, value in extra.items():
            if key not in {"ts", "source", "event_type"}:
                signal[key] = value
    state = _read_json(PRESENCE_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state["last_signal"] = signal
    state["recent_signals"] = (list(state.get("recent_signals") or []) + [signal])[-20:]
    _write_json(PRESENCE_STATE_PATH, state)
    return signal


def _activitywatch_base_url() -> str:
    return _env_first("HERMES_ACTIVITYWATCH_BASE_URL", "ACTIVITYWATCH_BASE_URL").rstrip("/")


def _runtime_activitywatch_signal(*, now: Optional[datetime] = None) -> Dict[str, Any]:
    base_url = _activitywatch_base_url()
    if not base_url:
        return {"configured": False, "active": False, "confidence": 0.0}
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    try:
        with _http_client() as client:
            afk_resp = client.get(f"{base_url}/api/0/buckets/aw-watcher-afk_/events", params={"limit": 1})
            afk_resp.raise_for_status()
            afk_events = afk_resp.json() or []
            window_resp = client.get(f"{base_url}/api/0/buckets/aw-watcher-window_/events", params={"limit": 1})
            window_resp.raise_for_status()
            window_events = window_resp.json() or []
    except Exception as exc:
        return {"configured": True, "active": False, "confidence": 0.0, "error": str(exc)}

    afk = afk_events[0] if afk_events else {}
    window = window_events[0] if window_events else {}
    afk_ts = _runtime_parse_iso(str(afk.get("timestamp") or ""))
    age_seconds = None
    if afk_ts is not None:
        age_seconds = max(int((checked_at - afk_ts).total_seconds()), 0)
    status = str(((afk.get("data") or {}).get("status")) or "").strip().lower()
    active = status == "not-afk" and (age_seconds is None or age_seconds <= 12 * 60 * 60)
    app_name = str(((window.get("data") or {}).get("app")) or "").strip().lower()
    title = str(((window.get("data") or {}).get("title")) or "").strip()
    category = "unknown"
    if app_name:
        if any(token in app_name for token in ["chrome", "firefox", "edge", "safari", "browser"]):
            category = "browser"
        elif any(token in app_name for token in ["code", "cursor", "pycharm", "idea", "studio"]):
            category = "editor"
        elif "todoist" in app_name or "todoist" in title.lower():
            category = "todoist"
        elif any(token in app_name for token in ["telegram", "discord", "slack", "signal"]):
            category = "messaging"
    confidence = 0.78 if active else 0.2
    if active and category in {"todoist", "editor", "browser"}:
        confidence = 0.82
    return {
        "configured": True,
        "active": active,
        "confidence": confidence,
        "last_activity_age_seconds": age_seconds,
        "active_category": category,
        "title_hint": title[:120] if title else "",
        "source": "activitywatch",
    }


def _runtime_presence_status(*, now: Optional[datetime] = None) -> Dict[str, Any]:
    # Evaluate global and plugin-specific bypass rules
    config_data = _read_yaml(HERMES_CONFIG_PATH, {}) or {}
    personal_ops_cfg = config_data.get("plugins", {}).get("personal_ops", {}) or {}
    bypass_presence = (
        bool(personal_ops_cfg.get("always_nudge_proactively")) or
        bool(personal_ops_cfg.get("proactive_bypass_presence")) or
        bool(personal_ops_cfg.get("always_nudge")) or
        bool(config_data.get("always_nudge_proactively")) or
        bool(config_data.get("proactive_bypass_presence")) or
        bool(config_data.get("always_nudge"))
    )

    rules_data = _read_json(TODOIST_RULES_PATH, {}) or {}
    bypass_presence = bypass_presence or (
        bool(rules_data.get("always_nudge_proactively")) or
        bool(rules_data.get("proactive_bypass_presence")) or
        bool(rules_data.get("always_nudge"))
    )

    state = _read_json(PRESENCE_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    activitywatch = _runtime_activitywatch_signal(now=now)
    signal = dict(state.get("last_signal") or {})
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    if not signal:
        aw_confidence = float(activitywatch.get("confidence") or 0.0)
        if activitywatch.get("configured"):
            aw_level = "active_now" if aw_confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM else "weak"
            can_proactively = bool(activitywatch.get("active") and aw_confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM)
            if bypass_presence:
                can_proactively = True
            return {
                "configured": True,
                "confidence": aw_confidence,
                "raw_confidence": aw_confidence,
                "level": aw_level,
                "can_proactively_message": can_proactively,
                "summary": "Presence derived from ActivityWatch local activity; this indicates recent device activity, not certainty about attention or willingness to be interrupted.",
                "last_signal": None,
                "recent_signals": [],
                "activitywatch": activitywatch,
            }
        return {
            "configured": False,
            "confidence": None,
            "level": "unknown",
            "can_proactively_message": True,
            "summary": "No presence signal has been recorded yet; proactive messages fall back to schedule, Todoist state, and quiet hours.",
            "last_signal": None,
            "activitywatch": activitywatch,
        }
    parsed = _runtime_parse_iso(str(signal.get("ts") or ""))
    age_minutes: Optional[int] = None
    fresh = False
    messaging_fresh = False
    if parsed is not None:
        age_minutes = max(int((checked_at - parsed).total_seconds() // 60), 0)
        source_name = str(signal.get("source") or "")
        freshness_window = 12 * 60 if source_name == "activitywatch-forwarder" else PRESENCE_SIGNAL_TTL_MINUTES
        fresh = age_minutes <= freshness_window
        messaging_fresh = age_minutes <= PRESENCE_SIGNAL_TTL_MINUTES
    raw_confidence = float(signal.get("confidence") or 0)
    confidence = raw_confidence if fresh else 0.0
    level = "strong" if confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM else "weak"
    if not fresh:
        level = "stale"
    aw_confidence = float(activitywatch.get("confidence") or 0.0)
    if activitywatch.get("configured") and bool(activitywatch.get("active")) and aw_confidence > confidence:
        confidence = aw_confidence
        level = "active_now" if confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM else "weak"
        fresh = True
        messaging_fresh = True
    can_message = bool(messaging_fresh and confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM)
    if bypass_presence:
        can_message = True
    label = str(signal.get("label") or signal.get("event_type") or "activity signal")
    source = str(signal.get("source") or "unknown")
    summary = (
        f"Latest presence signal is {label} from {source}; confidence {confidence:.2f}. "
        "This is evidence of recent activity, not proof of exact device state or Telegram device type."
    )
    if not fresh:
        summary = f"Latest presence signal is stale; last useful signal was {label} from {source}."
    if bypass_presence:
        summary += " (Proactive outreach enabled by configuration bypass.)"
    return {
        "configured": True,
        "confidence": confidence,
        "raw_confidence": raw_confidence,
        "level": level,
        "fresh": fresh,
        "age_minutes": age_minutes,
        "can_proactively_message": can_message,
        "summary": summary,
        "last_signal": signal,
        "recent_signals": list(state.get("recent_signals") or []),
        "activitywatch": activitywatch,
    }


def _nudge_budget_local_date(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(_runtime_local_tz()).date().isoformat()


def _nudge_budget_read_for_today(now: datetime) -> Dict[str, Any]:
    today = _nudge_budget_local_date(now)
    state = _read_json(NUDGE_BUDGET_STATE_PATH, {})
    if not isinstance(state, dict) or state.get("date") != today:
        state = {"date": today, "sent_counts": {"pressure": 0, "total": 0}, "events": []}
    state.setdefault("sent_counts", {"pressure": 0, "total": 0})
    state.setdefault("events", [])
    return state


def _nudge_budget_check(*, category: str, now: datetime) -> Optional[Dict[str, Any]]:
    state = _nudge_budget_read_for_today(now)
    counts = dict(state.get("sent_counts") or {})
    if int(counts.get(category, 0)) >= NUDGE_BUDGET_DAILY_PRESSURE_LIMIT:
        return {
            "reason": "nudge_budget_exhausted",
            "category": category,
            "limit": NUDGE_BUDGET_DAILY_PRESSURE_LIMIT,
            "sent_today": int(counts.get(category, 0)),
        }
    return None


def _nudge_budget_record_sent(*, category: str, now: datetime, task_label: Optional[str], message: str) -> Dict[str, Any]:
    state = _nudge_budget_read_for_today(now)
    counts = dict(state.get("sent_counts") or {})
    counts[category] = int(counts.get(category, 0)) + 1
    counts["total"] = int(counts.get("total", 0)) + 1
    state["sent_counts"] = counts
    state["events"] = (
        list(state.get("events") or [])
        + [{"ts": now.isoformat(), "category": category, "task_label": task_label, "message_preview": message[:160]}]
    )[-50:]
    _write_json(NUDGE_BUDGET_STATE_PATH, state)
    return state


def _mood_router_text_scores(text: str) -> Dict[str, float]:
    lowered = text.lower()
    lexicon = {
        "frustrated": ("frustrated", "annoyed", "angry", "mad", "nonsense", "broken", "mess", "irritated"),
        "confused": ("confused", "lost", "unclear", "gibberish", "don't understand", "doesn't make sense"),
        "low_energy": ("tired", "overwhelmed", "exhausted", "stuck", "drained", "low energy", "burned out"),
        "rushed": ("busy", "rushed", "quick", "no time", "hurry", "asap"),
        "engaged": ("good", "great", "go ahead", "continue", "approved", "yes"),
    }
    scores: Dict[str, float] = {}
    for label, terms in lexicon.items():
        hits = sum(1 for term in terms if term in lowered)
        if hits:
            scores[label] = min(0.35 + (hits * 0.18), 0.92)
    if not scores and text.strip():
        scores["neutral"] = 0.55
    return scores


def _mood_router_voice_scores(audio_emotions: Any) -> Dict[str, float]:
    if not isinstance(audio_emotions, dict):
        return {}
    mapping = {
        "angry": "frustrated",
        "anger": "frustrated",
        "annoyed": "frustrated",
        "sad": "low_energy",
        "sadness": "low_energy",
        "fear": "low_energy",
        "fearful": "low_energy",
        "tired": "low_energy",
        "neutral": "neutral",
        "happy": "engaged",
        "joy": "engaged",
        "surprise": "engaged",
    }
    scores: Dict[str, float] = {}
    for raw_label, raw_score in audio_emotions.items():
        try:
            score = float(raw_score)
        except Exception:
            continue
        label = mapping.get(str(raw_label).strip().lower())
        if not label:
            continue
        scores[label] = max(scores.get(label, 0.0), max(0.0, min(score, 1.0)))
    return scores


def _mood_router_style_policy(label: str) -> Dict[str, str]:
    policies = {
        "frustrated": {"tone": "warm", "pace": "steady", "detail": "explain_reason", "next_step_size": "small"},
        "confused": {"tone": "patient", "pace": "slow", "detail": "context_first", "next_step_size": "small"},
        "low_energy": {"tone": "encouraging", "pace": "slow", "detail": "minimal", "next_step_size": "tiny"},
        "rushed": {"tone": "concise", "pace": "fast", "detail": "action_only", "next_step_size": "small"},
        "engaged": {"tone": "direct", "pace": "normal", "detail": "normal", "next_step_size": "normal"},
        "neutral": {"tone": "direct", "pace": "normal", "detail": "normal", "next_step_size": "normal"},
    }
    return dict(policies.get(label, policies["neutral"]))


def _mood_router_fuse(*, text_scores: Dict[str, float], voice_scores: Dict[str, float]) -> Dict[str, Any]:
    combined: Dict[str, float] = {}
    for label, score in text_scores.items():
        combined[label] = max(combined.get(label, 0.0), float(score) * 0.92)
    for label, score in voice_scores.items():
        combined[label] = max(combined.get(label, 0.0), float(score))
    if text_scores.get("low_energy", 0) >= 0.5 and voice_scores.get("low_energy", 0) >= 0.5:
        combined["low_energy"] = min(max(combined.get("low_energy", 0), 0.78), 0.95)
    if text_scores.get("frustrated", 0) >= 0.5 and text_scores.get("confused", 0) >= 0.5:
        combined["frustrated"] = max(combined.get("frustrated", 0), 0.76)
    if not combined:
        combined["unknown"] = 0.0
    priority = {"frustrated": 5, "low_energy": 4, "confused": 3, "rushed": 2, "engaged": 1, "neutral": 0, "unknown": -1}
    label, confidence = max(combined.items(), key=lambda item: (item[1], priority.get(item[0], 0)))
    return {"label": label, "confidence": round(float(confidence), 3), "scores": {k: round(float(v), 3) for k, v in combined.items()}}


def _mood_router_model_status() -> Dict[str, Any]:
    providers = {
        "whisper": False,
        "goemotions": False,
        "emotion2vec": False,
    }
    try:
        import whisper  # type: ignore  # noqa: F401
        providers["whisper"] = True
    except Exception:
        pass
    try:
        import transformers  # type: ignore  # noqa: F401
        providers["goemotions"] = True
    except Exception:
        pass
    try:
        import funasr  # type: ignore  # noqa: F401
        providers["emotion2vec"] = True
    except Exception:
        pass
    return {
        "providers": providers,
        "intended_stack": ["Whisper", "GoEmotions", "emotion2vec"],
        "fallback": "lexicon_router",
    }


def _mood_router_status() -> Dict[str, Any]:
    state = _read_json(MOOD_ROUTER_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    return {
        "configured": bool(state.get("last_mood")),
        "last_mood": state.get("last_mood"),
        "recent_moods": list(state.get("recent_moods") or []),
        "model_status": _mood_router_model_status(),
    }


def _mood_router_route(args: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    text = str(args.get("text") or args.get("transcript") or "").strip()
    audio_emotions = args.get("audio_emotions") or args.get("voice_emotions")
    text_scores = _mood_router_text_scores(text)
    voice_scores = _mood_router_voice_scores(audio_emotions)
    fused = _mood_router_fuse(text_scores=text_scores, voice_scores=voice_scores)
    modalities = []
    if text_scores:
        modalities.append("text")
    if voice_scores:
        modalities.append("voice")
    label = str(fused["label"])
    mood = {
        "ts": (now or datetime.now(timezone.utc)).isoformat(),
        "source": str(args.get("source") or "unknown").strip(),
        "label": label,
        "confidence": fused["confidence"],
        "scores": fused["scores"],
        "modalities": modalities,
        "style_policy": _mood_router_style_policy(label),
        "evidence_summary": "text+voice mood signal" if set(modalities) == {"text", "voice"} else (f"{modalities[0]} mood signal" if modalities else "no mood signal"),
    }
    state = _read_json(MOOD_ROUTER_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state["last_mood"] = mood
    state["recent_moods"] = (list(state.get("recent_moods") or []) + [mood])[-30:]
    state["model_status"] = _mood_router_model_status()
    _write_json(MOOD_ROUTER_STATE_PATH, state)
    return mood


def _runtime_calendar_proposal(*, title: str, window: str, duration_minutes: int, notes: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "title": title,
        "window": window,
        "duration_minutes": int(duration_minutes),
        "notes": list(notes or []),
        "status": "proposal_only",
    }


def _calendar_provider() -> str:
    return str(_env_first("HERMES_CALENDAR_PROVIDER", "CALENDAR_PROVIDER") or "").strip().lower()


def _calendar_browser_url() -> str:
    return str(_env_first("HERMES_GOOGLE_CALENDAR_URL", "GOOGLE_CALENDAR_URL") or "https://calendar.google.com/calendar/u/0/r").strip()


def _calendar_read_state() -> Dict[str, Any]:
    data = _read_json(CALENDAR_STATE_PATH, {"drafts": [], "commits": []})
    if not isinstance(data, dict):
        return {"drafts": [], "commits": []}
    drafts = list(data.get("drafts") or [])
    commits = list(data.get("commits") or [])
    return {"drafts": [item for item in drafts if isinstance(item, dict)], "commits": [item for item in commits if isinstance(item, dict)]}


def _calendar_write_state(data: Dict[str, Any]) -> None:
    _write_json(CALENDAR_STATE_PATH, data)


def _calendar_compact_timestamp(value: str) -> str:
    dt = _runtime_parse_iso(value)
    if dt is None:
        return ""
    return dt.astimezone(_runtime_local_tz()).strftime("%Y%m%dT%H%M%S")


def _calendar_prefill_url(*, title: str, start: str, end: str, description: str = "") -> str:
    from urllib.parse import urlencode
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{_calendar_compact_timestamp(start)}/{_calendar_compact_timestamp(end)}",
        "details": description,
        "ctz": HERMES_LOCAL_TIMEZONE,
    }
    return f"{_calendar_browser_url()}?{urlencode(params)}"


def _runtime_calendar_status(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    provider = _calendar_provider()
    state = _calendar_read_state()
    configured = provider == "browser_google_calendar" and bool(_calendar_browser_url())
    return {
        "success": True,
        "action": "calendar_status",
        "provider": provider or "unconfigured",
        "configured": configured,
        "mode": "browser_handoff" if provider == "browser_google_calendar" else "unconfigured",
        "approval_policy": "commit_requires_approval",
        "draft_count": len(state.get("drafts") or []),
        "commit_count": len(state.get("commits") or []),
        "browser_url": _calendar_browser_url() if configured else "",
    }


def _runtime_calendar_event(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode") or "draft").strip().lower()
    provider = _calendar_provider()
    if provider != "browser_google_calendar":
        raise ValueError("calendar provider is not configured for browser_google_calendar")
    state = _calendar_read_state()
    drafts = list(state.get("drafts") or [])
    commits = list(state.get("commits") or [])
    if mode == "draft":
        title = str(args.get("title") or "").strip()
        start = str(args.get("start") or "").strip()
        end = str(args.get("end") or "").strip()
        description = str(args.get("description") or "").strip()
        if not title or not start or not end:
            raise ValueError("title, start, and end are required")
        draft = {
            "draft_id": f"calendar_draft_{uuid.uuid4().hex[:10]}",
            "provider": provider,
            "title": title,
            "start": start,
            "end": end,
            "description": description,
            "prefill_url": _calendar_prefill_url(title=title, start=start, end=end, description=description),
            "status": "draft_ready",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        drafts.append(draft)
        state["drafts"] = drafts[-100:]
        state["commits"] = commits[-100:]
        _calendar_write_state(state)
        return {"success": True, "action": "calendar_event", "mode": mode, "provider": provider, "draft": draft}
    if mode == "commit":
        draft_id = str(args.get("draft_id") or "").strip()
        draft = next((item for item in reversed(drafts) if str(item.get("draft_id") or "") == draft_id), None)
        if draft is None:
            raise ValueError("draft_id was not found")
        response = json.loads(_create_approval(
            tool_name="personal_runtime",
            action="calendar_event_commit",
            summary=f"Approve calendar event handoff for {draft.get('title')}",
            reason="Calendar writes should be explicit and approval-gated even in browser-backed mode.",
            benefit="Hermes prepares the event and you keep control over the final browser-backed calendar handoff.",
            payload={"action": "calendar_event_commit", "draft": draft},
        ))
        response["draft"] = draft
        return response
    raise ValueError(f"Unsupported calendar_event mode: {mode}")


def _runtime_create_todoist_task_direct(*, content: str, description: str = "", priority: int = 1, labels: Optional[List[str]] = None) -> Dict[str, Any]:
    payload = {
        "action": "add_task",
        "content": content,
        "description": description,
        "priority": priority,
        "labels": list(labels or []),
    }
    return _execute_todoist(payload)


def _runtime_event_window_label(now: Optional[datetime] = None) -> str:
    local = (now or datetime.now(timezone.utc)).astimezone(_runtime_local_tz())
    hour = local.hour
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "midday"
    if 17 <= hour < 22:
        return "evening"
    return "quiet_hours"


def _runtime_operator_event_brief(*, event_type: str, focus_state: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    window = _runtime_event_window_label(now)
    operator = None
    try:
        operator = _operator_brief({
            "filter": "today | overdue",
            "limit": 8,
            "allow_message": False,
            "send_telegram": False,
        })
    except Exception as exc:
        operator = {"success": False, "error": str(exc)}
    target = str(((focus_state.get("most_important_task") or {}).get("content") or "")).strip()
    top_task = operator.get("top_task") if isinstance(operator, dict) else None
    if isinstance(top_task, dict) and top_task.get("title"):
        target = str(top_task["title"])
    target = target or "No clear top task"
    return {
        "window": window,
        "operator": operator,
        "target": target,
        "risk": (operator or {}).get("risk") if isinstance(operator, dict) else None,
        "friction": (operator or {}).get("primary_friction") if isinstance(operator, dict) else None,
        "next_action": (operator or {}).get("recommended_next_action") if isinstance(operator, dict) else None,
    }


def _runtime_source_friendly(source: str) -> str:
    return {
        "windows-logon-trigger": "Windows logon",
        "windows-unlock-trigger": "desktop unlock",
        "desktop_unlocked": "desktop unlock",
        "manual": "manual command",
    }.get(source, source or "unknown")


def _runtime_task_link(title: str, task_id: Optional[str]) -> str:
    escaped = _escape_html(title)
    if task_id:
        return f'<b><a href="https://app.todoist.com/app/task/{task_id}">{escaped}</a></b>'
    return f'"{escaped}"'


def _runtime_purpose_preserving_next_action(raw: str, task_title: str) -> str:
    text = str(raw or "").strip()
    lowered = task_title.lower()
    if "laundry" in lowered:
        return "Minimum useful move: start, switch, fold one small piece, or mark no laundry needed."
    if not text:
        return "Pick one small action that still makes sense in this time window."
    return text.replace("finish it, split it, or reschedule it honestly", "do the smallest useful version or reschedule it honestly")


def _runtime_render_policy_event_briefing(
    *,
    event_type: str,
    focus_state: Dict[str, Any],
    detail: Dict[str, Any],
    now: datetime,
    source: str,
) -> str:
    local = now.astimezone(_runtime_local_tz())
    time_str = local.strftime('%I:%M %p').lstrip('0')
    source_friendly = _runtime_source_friendly(source)
    target = str(detail.get("target") or ((focus_state.get("most_important_task") or {}).get("content") or "") or "No clear top task").strip()
    mit = focus_state.get("most_important_task") or {}
    task_link = _runtime_task_link(target, mit.get("id")) if target and target != "No clear top task" else ""
    window = str(detail.get("window") or _runtime_event_window_label(now))
    is_late_evening = window == "evening" and local.hour >= 21

    signal_name = source_friendly
    lines = [
        f"I received a {signal_name} signal at {time_str}, so I'm treating this as possible activity, not guaranteed availability.",
        "",
    ]

    if window == "quiet_hours":
        lines.append("This is outside normal message hours, so this should stay quiet unless you asked for it.")
        if task_link:
            lines.append(f"Queued context: {task_link}.")
    elif is_late_evening:
        lines.append("Since it's late, I'm not going to push deep work, reference reading, or broad planning.")
        if task_link:
            lines.append(f"The one task that still makes sense tonight is {task_link}.")
    else:
        lines.append("Priority anchor:")
        if task_link:
            lines.append(task_link)
        else:
            lines.append("No clear top task is defined, so the useful move is to pick one small anchor before doing support work.")

    operator = detail.get("operator") if isinstance(detail.get("operator"), dict) else {}
    evidence = (operator.get("evidence") or {}) if isinstance(operator, dict) else {}
    todoist_evidence = (evidence.get("todoist_mcp") or {}) if isinstance(evidence, dict) else {}
    if todoist_evidence and not is_late_evening:
        active = todoist_evidence.get("active_count", 0)
        completed = todoist_evidence.get("completed_recently", 0)
        stats_parts = []
        if active:
            stats_parts.append(f"{active} active task{'s' if active != 1 else ''}")
        if completed:
            stats_parts.append(f"{completed} completed recently")
        if stats_parts:
            lines.append(f"Quick snapshot: {', '.join(stats_parts)}.")

    suspicious = list(focus_state.get("suspicious_tasks") or [])
    if suspicious:
        first_task = suspicious[0].get("task") or {}
        first = str(first_task.get("content") or "").strip()
        if first:
            first_link = _runtime_task_link(first, first_task.get("id"))
            if is_late_evening:
                lines.append(f"\nI would ignore {first_link} tonight unless you are intentionally doing review work. It looks more like reference/setup than execution.")
            else:
                lines.append(f"\nPotential distractions: {first_link} looks more like reference/setup or support work than the main action.")

    next_act = _runtime_purpose_preserving_next_action(str(detail.get("next_action") or ""), target)
    lines.append(f"\n\U0001f449 For the next 5\u201315 minutes: {next_act}")
    if is_late_evening:
        lines.append("If that is not realistic right now, tap it later mentally and let tonight be a clean reschedule, not a catch-up spiral.")
    else:
        lines.append("If that is not realistic, reschedule it honestly or write the blocker.")
    lines.append(f"\n\U0001f552 {time_str} \u00b7 triggered via {source_friendly}")
    return "\n".join(lines)


def _runtime_build_wake_briefing(*, focus_state: Dict[str, Any], now: Optional[datetime] = None, source: str = "") -> str:
    detail = _runtime_operator_event_brief(event_type="wake", focus_state=focus_state, now=now)
    local = (now or datetime.now(timezone.utc)).astimezone(_runtime_local_tz())
    return _runtime_render_policy_event_briefing(
        event_type="wake",
        focus_state=focus_state,
        detail=detail,
        now=local,
        source=source,
    )


def _runtime_build_unlock_briefing(*, focus_state: Dict[str, Any], now: Optional[datetime] = None, source: str = "") -> str:
    detail = _runtime_operator_event_brief(event_type="desktop_unlocked", focus_state=focus_state, now=now)
    local = (now or datetime.now(timezone.utc)).astimezone(_runtime_local_tz())
    return _runtime_render_policy_event_briefing(
        event_type="desktop_unlocked",
        focus_state=focus_state,
        detail=detail,
        now=local,
        source=source,
    )


def _runtime_outing_options(*, now: datetime, budget: str, time_window: str, energy: str) -> List[Dict[str, Any]]:
    local = now.astimezone()
    weekday = local.strftime("%A")
    options = [
        {
            "title": "Coffee and one short walk",
            "why": "Low setup, easy exit, good for rebuilding the habit of leaving.",
            "effort": "low",
            "budget": "low",
            "duration_minutes": 60,
            "window": time_window,
        },
        {
            "title": "Errand plus one pleasant stop",
            "why": "Turns a practical trip into a real outing without demanding too much novelty.",
            "effort": "medium",
            "budget": "low",
            "duration_minutes": 90,
            "window": time_window,
        },
        {
            "title": f"{weekday} anchor outing",
            "why": "A slightly more deliberate plan so the week has one memorable outside moment.",
            "effort": "medium" if energy != "low" else "low",
            "budget": budget,
            "duration_minutes": 120,
            "window": time_window,
        },
    ]
    if energy == "low":
        return options[:2]
    return options


def _runtime_handle_outing_event(args: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    budget = str(args.get("budget") or "low").strip().lower()
    time_window = str(args.get("time_window") or "today").strip()
    energy = str(args.get("energy") or "medium").strip().lower()
    options = _runtime_outing_options(now=now, budget=budget, time_window=time_window, energy=energy)
    top = options[0]
    todoist_result = None
    if bool(args.get("auto_create_todoist", True)):
        description = "Options:\n" + "\n".join(f"- {item['title']}: {item['why']}" for item in options)
        todoist_result = _runtime_create_todoist_task_direct(
            content=f"Pick and do one outing: {top['title']}",
            description=description,
            priority=3,
            labels=["outing", "hermes"],
        )
    proposal = _runtime_calendar_proposal(
        title=top["title"],
        window=top["window"],
        duration_minutes=int(top["duration_minutes"]),
        notes=[item["title"] for item in options],
    )
    return {
        "handled": True,
        "event_type": "outing_request",
        "options": options,
        "selected_default": top,
        "todoist": todoist_result,
        "calendar_proposal": proposal,
        "summary": f"Built {len(options)} outing options and defaulted to '{top['title']}'.",
    }


VOICE_CLI_WHITELIST = {
    "restart dashboard": ["systemctl", "--user", "restart", "hermes-dashboard"],
    "status dashboard": ["systemctl", "--user", "status", "hermes-dashboard"],
    "restart gateway": ["systemctl", "--user", "restart", "hermes-gateway"],
    "status gateway": ["systemctl", "--user", "status", "hermes-gateway"],
    "status webhook": ["systemctl", "--user", "status", "hermes-event-webhook"],
    "check disk": ["df", "-h"],
    "check memory": ["free", "-m"],
    "backup configuration": ["tar", "-czf", "/home/ubuntu/.hermes/backup_config.tar.gz", "-C", "/home/ubuntu/.hermes", "config.yaml", ".env"],
}

def _voice_core_apply_corrections(text: str) -> str:
    corrections = {
        r"\bcatty\s*file\b": "Caddyfile",
        r"\bcaddy\s*file\b": "Caddyfile",
        r"\bto\s*do\s*list\b": "Todoist",
        r"\bactivity\s*watch\b": "ActivityWatch",
        r"\bweb\s*hook\b": "webhook",
        r"\bfast\s*api\b": "FastAPI",
        r"\bsystem\s*d\b": "systemd",
        r"\bherms\b": "Hermes",
    }
    cleaned = text
    for pat, rep in corrections.items():
        cleaned = re.sub(pat, rep, cleaned, flags=re.IGNORECASE)
    return cleaned

def _voice_core_assemble_context() -> Dict[str, Any]:
    context = {}
    context["current_time"] = datetime.now(timezone.utc).isoformat()
    presence = _read_json(PRESENCE_STATE_PATH, {})
    context["current_presence"] = {
        "location": presence.get("location", "unknown"),
        "last_update": presence.get("last_location_update"),
        "source": presence.get("source")
    }
    aw_signal = _runtime_activitywatch_signal()
    if aw_signal.get("configured") and aw_signal.get("active"):
        context["active_window"] = {
            "app": aw_signal.get("active_category"),
            "title": aw_signal.get("title_hint")
        }
    try:
        tasks = _focus_guard_read_todoist_tasks()
        context["active_tasks"] = [
            {"id": t["id"], "content": t["content"], "priority": t["priority"], "labels": t.get("labels", [])}
            for t in tasks[:20]
        ]
    except Exception:
        context["active_tasks"] = []
    try:
        memos = _read_jsonl_recent(VOICE_CAPTURE_LOG_PATH, limit=5)
        context["recent_memos"] = [
            {"ts": m.get("ts"), "transcript": m.get("transcript"), "classification": m.get("kind")}
            for m in memos
        ]
    except Exception:
        context["recent_memos"] = []
    return context

def _get_todoist_projects() -> Dict[str, str]:
    projects_map = {}
    try:
        with _http_client() as client:
            resp = client.get(f"{TODOIST_BASE}/projects", headers=_todoist_headers())
            if resp.status_code == 200:
                results = resp.json().get("results") or []
                for p in results:
                    projects_map[p["name"].lower().strip()] = p["id"]
    except Exception:
        pass
    return projects_map

def _get_project_id_by_name(name: str) -> Optional[str]:
    if not name:
        return None
    p_map = _get_todoist_projects()
    name_lower = name.lower().strip()
    for key, val in p_map.items():
        if name_lower == key or name_lower in key or key in name_lower:
            return val
    return None

def _voice_core_answer_query(query: str, context: Dict[str, Any]) -> str:
    from agent.auxiliary_client import call_llm
    system_prompt = (
        "You are Hermes, a helpful personal assistant OS. Answer the user's spoken question based on the provided context state.\n"
        "Keep your answer extremely concise, professional, and conversational (max 3 sentences) since it will be sent to the user via Telegram.\n\n"
        "CONTEXT:\n"
        f"- Current Time: {context.get('current_time')}\n"
        f"- Presence: {context.get('current_presence')}\n"
        f"- Active Desktop Window: {context.get('active_window')}\n"
        f"- Active Todoist Tasks: {context.get('active_tasks')}\n"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"User question: {query}"}
    ]
    try:
        response = call_llm(
            task="title_generation",
            messages=messages,
            max_tokens=200,
            temperature=0.7,
            timeout=10.0,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        return f"Unable to answer query: {e}"

def _find_and_complete_todoist_task(query_str: str) -> Optional[Dict[str, Any]]:
    if not query_str:
        return None
    try:
        tasks = _focus_guard_read_todoist_tasks()
        query_lower = query_str.lower().strip()
        for task in tasks:
            title_lower = task.get("content", "").lower()
            if query_lower in title_lower or any(word in title_lower for word in query_lower.split() if len(word) > 3):
                res = _execute_todoist({"action": "close_task", "task_id": task["id"]})
                return task
    except Exception:
        pass
    return None

def _run_whitelist_system_command(command_key: str) -> str:
    if command_key not in VOICE_CLI_WHITELIST:
        return f"Execution rejected: Command key '{command_key}' is not whitelisted."
    cmd = VOICE_CLI_WHITELIST[command_key]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = (res.stdout or "") + (res.stderr or "")
        return f"Executed whitelisted command '{command_key}':\n{output[:500]}"
    except Exception as e:
        return f"Failed to run command '{command_key}': {e}"

def _voice_core_fallback(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    intent = "note_capture"
    details = {}
    if any(term in lowered for term in ["worked on", "spent", "hours", "today i did", "i was working on"]):
        intent = "WORK_PROGRESS"
        details = {"activity": text, "duration_hours": 0.0}
    elif any(term in lowered for term in ["remind me", "need to", "follow up", "todo", "to do", "i should"]):
        intent = "ACTION_TASK"
        details = {"title": text, "due_date": None, "priority": 2}
    elif any(term in lowered for term in ["idea", "what if", "i'm thinking", "could build", "maybe build"]):
        intent = "REFLECTION_JOURNAL"
        details = {"content": text, "mood": "neutral"}
    return {
        "corrected_transcript": text,
        "segments": [
            {
                "intent": intent,
                "reason": "fallback parser",
                "details": details
            }
        ]
    }

def _runtime_classify_voice_capture(text: str, context: Dict[str, Any]) -> Dict[str, Any]:
    from agent.auxiliary_client import call_llm
    whitelist_keys = list(VOICE_CLI_WHITELIST.keys())
    system_prompt = (
        "You are the Cognitive Vocal Core for Hermes, a personal agent OS.\n"
        "Analyze the user's spoken transcript, segment it into one or more distinct intents, "
        "and return a single JSON object in the exact format specified below.\n\n"
        "CONTEXT STATE:\n"
        f"- Current Time: {context.get('current_time')}\n"
        f"- Location/Presence: {context.get('current_presence')}\n"
        f"- Active Desktop Window: {context.get('active_window')}\n"
        f"- Recent Active Tasks: {context.get('active_tasks')}\n"
        f"- Recent Memos (Conversational Context): {context.get('recent_memos')}\n\n"
        "INTENT TYPES & DETAILS:\n"
        "1. ACTION_TASK: Something the user needs to do.\n"
        "   - title: Clean, concise title of the task (strip conversational junk like 'remind me to').\n"
        "   - due_date: Human relative date/time (e.g. 'tomorrow 3 PM', 'next Monday', or null).\n"
        "   - priority: Urgency level (4 for high/asap, 2 for normal, 1 for low).\n"
        "   - project: Suggested project name or null.\n"
        "2. WORK_PROGRESS: Update on work done/time spent.\n"
        "   - activity: Description of what was completed/worked on.\n"
        "   - duration_hours: Decimal hours spent (e.g. 1.5, 0.5) or 0 if not mentioned.\n"
        "   - associated_task_query: A string to search for in active tasks to auto-complete (or null).\n"
        "3. COMMAND_QUERY: A direct question about state, logs, or codebase config.\n"
        "   - query: Question text to search/resolve.\n"
        "4. EXECUTE_SYSTEM_COMMAND: Spoken request to run a whitelisted administrative shell command.\n"
        "   - command_key: MUST be exactly one of: " + ", ".join(whitelist_keys) + " (or null if no match).\n"
        "5. REFLECTION_JOURNAL: Personal reflections, journal inputs, mood indicators.\n"
        "   - content: Clean text of the reflection.\n"
        "   - mood: Guess the mood based on tone/content (productive, tired, stressed, happy, neutral).\n"
        "6. NOISE_FILLER: Conversational fill, hesitation, or non-actionable chatter.\n\n"
        "JSON SCHEMA:\n"
        "Respond ONLY with a JSON object in this format (no markdown, no backticks, no comments):\n"
        "{\n"
        "  \"corrected_transcript\": \"<the transcript corrected for typos and technical terms>\",\n"
        "  \"segments\": [\n"
        "    {\n"
        "      \"intent\": \"ACTION_TASK | WORK_PROGRESS | COMMAND_QUERY | EXECUTE_SYSTEM_COMMAND | REFLECTION_JOURNAL | NOISE_FILLER\",\n"
        "      \"reason\": \"<short explanation>\",\n"
        "      \"details\": { ... matching structure above ... }\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Spoken Transcript: {text}"},
    ]
    response = call_llm(
        task="title_generation",
        messages=messages,
        max_tokens=800,
        temperature=0.0,
        timeout=45.0,
    )
    content = (response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) >= 3 and lines[-1].startswith("```"):
            content = "\n".join(lines[1:-1]).strip()
        if content.startswith("json"):
            content = content[4:].strip()
    return json.loads(content)

def _runtime_handle_voice_capture(args: Dict[str, Any]) -> Dict[str, Any]:
    todoist_result = None
    raw_transcript = str(args.get("transcript") or args.get("text") or "").strip()
    if not raw_transcript:
        raise ValueError("transcript or text is required for voice capture")
    corrected_transcript = _voice_core_apply_corrections(raw_transcript)
    context = _voice_core_assemble_context()
    try:
        parsed = _runtime_classify_voice_capture(corrected_transcript, context)
    except Exception:
        parsed = _voice_core_fallback(corrected_transcript)
    corrected = parsed.get("corrected_transcript") or corrected_transcript
    segments = parsed.get("segments") or []
    summary_lines = []
    actions_taken = []
    for seg in segments:
        intent = seg.get("intent", "note_capture").upper()
        details = seg.get("details") or {}
        if intent == "ACTION_TASK":
            title = details.get("title") or corrected
            due_date = details.get("due_date")
            priority = int(details.get("priority") or 2)
            project = details.get("project")
            project_id = _get_project_id_by_name(project)
            todoist_payload = {
                "action": "add_task",
                "content": title,
                "description": f"Voice Capture: {raw_transcript}",
                "priority": priority,
            }
            if due_date:
                todoist_payload["due_string"] = due_date
            if project_id:
                todoist_payload["project_id"] = project_id
            todoist_payload["labels"] = ["voice-capture", "hermes"]
            res = _execute_todoist(todoist_payload)
            todoist_result = res
            if res.get("success"):
                summary_lines.append(f"???? **Created Task**: '{title}'" + (f" (Due: {due_date})" if due_date else ""))
                actions_taken.append(res)
            else:
                summary_lines.append(f"?????? **Failed to create task**: '{title}'")
        elif intent == "WORK_PROGRESS":
            activity = details.get("activity") or corrected
            duration = float(details.get("duration_hours") or 0.0)
            task_query = details.get("associated_task_query")
            work_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "activity": activity,
                "duration_hours": duration,
                "transcript_source": raw_transcript,
            }
            _append_jsonl(WORK_LOG_PATH, work_entry)
            summary_lines.append(f"?????? **Logged Work**: '{activity}' ({duration} hrs)")
            if task_query:
                completed_task = _find_and_complete_todoist_task(task_query)
                if completed_task:
                    summary_lines.append(f"??? **Auto-Completed Task**: '{completed_task.get('content')}'")
                    actions_taken.append({"completed_task": completed_task})
        elif intent == "COMMAND_QUERY":
            query = details.get("query") or corrected
            answer = _voice_core_answer_query(query, context)
            summary_lines.append(f"???? **Query**: '{query}'\n???? *{answer}*")
            actions_taken.append({"query": query, "answer": answer})
        elif intent == "EXECUTE_SYSTEM_COMMAND":
            cmd_key = details.get("command_key")
            if cmd_key:
                exec_summary = _run_whitelist_system_command(cmd_key)
                summary_lines.append(f"??????? **Executed Command**: {cmd_key}\n```{exec_summary}```")
                actions_taken.append({"system_command": cmd_key, "output": exec_summary})
            else:
                summary_lines.append("?????? **Command Rejected**: Invalid/unauthorized command requested.")
        elif intent == "REFLECTION_JOURNAL":
            content = details.get("content") or corrected
            mood = details.get("mood") or "neutral"
            journal_file = HERMES_HOME / "daily_journal.md"
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                journal_file.parent.mkdir(parents=True, exist_ok=True)
                with journal_file.open("a", encoding="utf-8") as f:
                    f.write(f"\n## {date_str} (Mood: {mood})\n")
                    f.write(f"- {content}\n")
                summary_lines.append(f"???? **Journaled Reflection** (Mood: {mood})")
            except Exception as e:
                summary_lines.append(f"?????? **Failed to save journal**: {e}")
            actions_taken.append({"journal": content, "mood": mood})
    vault_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": str(args.get("source") or "unknown").strip(),
        "raw_transcript": raw_transcript,
        "corrected_transcript": corrected,
        "segments": segments,
        "actions_taken": actions_taken,
    }
    VOICE_VAULT_LOG_PATH = HERMES_HOME / "voice_vault" / "vault_log.jsonl"
    _append_jsonl(VOICE_VAULT_LOG_PATH, vault_entry)
    legacy_entry = {
        "ts": vault_entry["ts"],
        "source": vault_entry["source"],
        "kind": segments[0].get("intent", "note_capture").lower() if segments else "note_capture",
        "reason": segments[0].get("reason", "") if segments else "",
        "transcript": raw_transcript,
    }
    _append_jsonl(VOICE_CAPTURE_LOG_PATH, legacy_entry)
    if summary_lines:
        telegram_message = "??????? **Voice Memo Processed**:\n" + "\n".join(summary_lines)
    else:
        telegram_message = "??????? **Voice Memo Received**: Logged reflection/note."
    # Ensure legacy compatibility for testing & tracking
    primary_intent = segments[0].get("intent", "note_capture").upper() if segments else "NOTE_CAPTURE"
    kind_map = {
        "ACTION_TASK": "task_capture",
        "WORK_PROGRESS": "work_log",
        "REFLECTION_JOURNAL": "note_capture",
        "COMMAND_QUERY": "note_capture",
        "EXECUTE_SYSTEM_COMMAND": "note_capture",
        "NOISE_FILLER": "note_capture"
    }
    legacy_kind = kind_map.get(primary_intent, "note_capture")
    legacy_reason = segments[0].get("reason", "") if segments else ""
    classification = {"kind": legacy_kind, "reason": legacy_reason}

    # Route mood updates
    mood = _mood_router_route(args, now=datetime.now(timezone.utc))

    _safe_send_telegram_message(telegram_message, force=True)
    return {
        "handled": True,
        "event_type": "voice_memo_received",
        "raw_transcript": raw_transcript,
        "corrected_transcript": corrected,
        "segments": segments,
        "summary": "Processed voice memo and executed actions.",
        "classification": classification,
        "mood": mood,
        "todoist": todoist_result,
        "logged_to": str(VOICE_CAPTURE_LOG_PATH),
    }



def _runtime_handle_activitywatch_heartbeat(args: Dict[str, Any]) -> Dict[str, Any]:
    signal = dict(args.get("presence_signal") or {})
    confidence = float(signal.get("confidence") or 0.0)
    label = str(signal.get("label") or "ActivityWatch heartbeat").strip()
    active = bool(signal.get("active"))

    # Read current location from presence state
    state = _read_json(PRESENCE_STATE_PATH, {})
    current_location = state.get("location", "").strip().lower()

    if active:
        if current_location != "desk":
            _handle_location_update({"location": "desk", "source": "activitywatch-forwarder"})
    else:
        if current_location == "desk":
            _handle_location_update({"location": "home", "source": "activitywatch-forwarder"})

    return {
        "handled": True,
        "event_type": "activitywatch_heartbeat",
        "presence_signal": {
            "confidence": confidence,
            "label": label,
            "active": active,
            "active_category": str(signal.get("active_category") or "").strip(),
            "last_activity_age_seconds": signal.get("last_activity_age_seconds"),
        },
        "summary": "Recorded ActivityWatch heartbeat from the user's computer.",
    }


GYM_AUTO_COMPLETE_MAX_MINUTES = 150


def _gym_session_minutes_from_message(message: str) -> Optional[int]:
    match = re.search(r"Session length:\s*(\d+)\s*min", message)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _gym_task_id_from_url(url: str) -> str:
    if "id=" in url:
        return url.split("id=")[-1]
    if "/" in url:
        return url.rstrip("/").split("/")[-1]
    return url


def _gym_location_verified_arg(args: Dict[str, Any]) -> Any:
    if "location_verified" in args:
        return args.get("location_verified")
    if "verified_location" in args:
        return args.get("verified_location")
    return None


def _gym_unverified_ios_result(event_type: str, source: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _gym_source_requires_location_verification is None or _gym_is_location_verified is None:
        return None
    if not _gym_source_requires_location_verification(source):
        return None
    if _gym_is_location_verified(_gym_location_verified_arg(args)):
        return None
    event = event_type.split(".", 1)[-1]
    if _gym_unverified_shortcut_message is not None:
        message = _gym_unverified_shortcut_message(event)
    else:
        message = "Gym event not logged: iOS shortcut did not include verified_location=1."
    return {
        "handled": True,
        "event_type": event_type,
        "message": message,
        "logged": False,
        "sent": False,
        "suppressed_reason": "unverified_ios_shortcut",
        "summary": message,
        "payload": {
            "gym_event": event,
            "source": source,
            "note": str(args.get("note") or args.get("message") or "").strip(),
        },
    }


def _gym_when_arg(args: Dict[str, Any]) -> Optional[datetime]:
    raw = args.get("when")
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _gym_off_schedule_ios_result(event_type: str, source: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _gym_automated_shortcut_is_off_schedule is None:
        return None
    when = _gym_when_arg(args)
    try:
        if not _gym_automated_shortcut_is_off_schedule(source=source, when=when):
            return None
    except Exception:
        return None
    event = event_type.split(".", 1)[-1]
    if _gym_off_schedule_shortcut_message is not None:
        message = _gym_off_schedule_shortcut_message(event, when)
    else:
        message = "Gym event not logged: this is not a scheduled lifting day."
    return {
        "handled": True,
        "event_type": event_type,
        "message": message,
        "logged": False,
        "sent": False,
        "suppressed_reason": "off_schedule_ios_shortcut",
        "summary": message,
        "payload": {
            "gym_event": event,
            "source": source,
            "note": str(args.get("note") or args.get("message") or "").strip(),
        },
    }


def _runtime_handle_gym_event(args: Dict[str, Any]) -> Dict[str, Any]:
    event_type = str(args.get("event_type") or "").strip().lower()
    if not event_type:
        event_type = "gym.arrived"
    event = event_type.split(".", 1)[-1]
    note = str(args.get("note") or args.get("message") or "").strip()
    source = str(args.get("source") or "gym-webhook").strip()
    when_raw = args.get("when")
    when: Optional[datetime] = None
    if isinstance(when_raw, str) and when_raw.strip():
        try:
            when = datetime.fromisoformat(when_raw.replace("Z", "+00:00"))
        except Exception:
            when = None

    buttons: List[Dict[str, str]] = []
    confirmation_required = False
    auto_completed = False

    if event == "arrived" and _gym_record_arrival is not None:
        message = _gym_record_arrival(source=source, note=note, when=when, location_verified=_gym_location_verified_arg(args))
        try:
            _safe_send_telegram_message(message, force=True)
        except Exception:
            pass
    elif event == "left" and _gym_record_departure is not None:
        message = _gym_record_departure(source=source, note=note, when=when, location_verified=_gym_location_verified_arg(args))
        if _gym_workout_task_for_day is not None:
            task = _gym_workout_task_for_day(when)
            if task:
                try:
                    name, url = task
                    task_id = _gym_task_id_from_url(url)
                    session_minutes = _gym_session_minutes_from_message(message)
                    if session_minutes is not None and session_minutes > GYM_AUTO_COMPLETE_MAX_MINUTES:
                        confirmation_required = True
                        message += (
                            f"\nYou were at the gym for {session_minutes} min, which is longer than a normal workout window. "
                            f"I did not auto-complete {name}. Please confirm what happened."
                        )
                        buttons = [
                            {"text": "Completed", "callback_data": f"po:gym:complete:{task_id}"},
                            {"text": "Partial", "callback_data": f"po:gym:partial:{task_id}"},
                            {"text": "Mistake", "callback_data": "po:gym:mistake"},
                        ]
                    else:
                        close_res = _execute_todoist({"action": "close_task", "task_id": task_id})
                        if close_res.get("success"):
                            auto_completed = True
                            message += f"\nAutomatically completed Todoist task: {name}."
                except Exception as e:
                    message += f"\n(Failed to auto-complete Todoist task: {e})"
        try:
            _safe_send_telegram_message(message, force=True, buttons=buttons or None)
        except Exception:
            pass
    elif event == "report" and _gym_monthly_report is not None:
        year = args.get("year")
        month = args.get("month")
        try:
            message = _gym_monthly_report(
                year=int(year) if year is not None and str(year).strip() else None,
                month=int(month) if month is not None and str(month).strip() else None,
            )
        except Exception:
            message = _gym_monthly_report()
    else:
        raise ValueError(f"Unsupported gym event: {event_type}")

    payload = {
        "gym_event": event,
        "source": source,
        "note": note,
    }
    if _gym_workout_task_for_day is not None:
        task = _gym_workout_task_for_day(when)
        if task:
            name, url = task
            task_id = url.split("id=")[-1] if "id=" in url else url
            payload["workout_task"] = {
                "name": name,
                "url": url,
                "app_url": f"todoist://task?id={task_id}"
            }
    if event == "arrived":
        payload["location"] = "gym"
    elif event == "left":
        payload["location"] = "away"
    return {
        "handled": True,
        "event_type": event_type,
        "summary": message.splitlines()[0] if message else f"Logged gym {event}.",
        "message": message,
        "confirmation_required": confirmation_required,
        "auto_completed": auto_completed,
        "presence_signal": {
            "confidence": 1.0,
            "label": f"Gym {event}",
            "active": event == "arrived",
            "active_category": "gym",
            "location": payload.get("location", "gym" if event == "arrived" else "away"),
        },
        "payload": payload,
    }


def _update_operator_state_from_event(event_type: str, source: str, payload: Dict[str, Any], now_dt: datetime) -> None:
    now_ts = int(now_dt.timestamp())
    presence_state = _read_json(PRESENCE_STATE_PATH, {})
    if not isinstance(presence_state, dict):
        presence_state = {}
    operator_state = _operator_read_state()

    # Track sensor heartbeats
    heartbeats = operator_state.setdefault("last_sensor_heartbeats", {})
    heartbeats[source] = now_ts

    # Extract info
    category = payload.get("category") or payload.get("active_category") or "unknown"
    duration = int(payload.get("duration_sec") or 0)

    # 1. Desktop Sentinel events
    if event_type == "desktop.active":
        presence_state["state"] = "desk"
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts
        presence_state["afk"] = False
    elif event_type == "desktop.idle":
        if presence_state.get("state") == "desk":
            presence_state["state"] = presence_state.get("location", "home")
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts
        presence_state["afk"] = True
    elif event_type in {"desktop.heartbeat", "desktop.category_changed"}:
        payload_state = payload.get("presence_state")
        if payload_state == "active_now":
            presence_state["state"] = "desk"
            presence_state["afk"] = False
        elif payload_state == "idle":
            if presence_state.get("state") == "desk":
                presence_state["state"] = presence_state.get("location", "home")
            presence_state["afk"] = True
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts

        att = operator_state.setdefault("attention", {})
        if category and category != "unknown":
            att["category"] = category
            att["last_updated_at"] = now_ts
    elif event_type == "desktop.category_ended":
        att = operator_state.setdefault("attention", {})
        att["category"] = "unknown"
        att["last_updated_at"] = now_ts

    # 2. iOS Focus & Sleep Events
    elif event_type == "ios.sleep_focus_on":
        presence_state["state"] = "sleep"
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts
        operator_state["day_phase"] = "quiet_hours"
    elif event_type == "ios.sleep_focus_off":
        presence_state["state"] = "home"
        presence_state["confidence"] = 0.8
        presence_state["last_seen_ts"] = now_ts
        operator_state["day_phase"] = "morning_horizon"
        operator_state["wake_candidate_ts"] = now_ts
    elif event_type == "ios.work_focus_on":
        operator_state["day_phase"] = "work_window"
    elif event_type == "ios.work_focus_off":
        operator_state["day_phase"] = "evening"

    # 3. Location events
    elif event_type == "location_update":
        loc = payload.get("location") or payload.get("value") or "home"
        presence_state["location"] = loc
        presence_state["state"] = loc
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts

    # 4. Decay and sensor watchdog freshness
    sentinel_last = heartbeats.get("desktop_sentinel")
    if sentinel_last and (now_ts - sentinel_last > 600):
        # Stale desktop sentinel -> decay confidence
        if presence_state.get("state") == "desk":
            presence_state["state"] = presence_state.get("location", "home")
        presence_state["confidence"] = max(0.0, presence_state.get("confidence", 1.0) - 0.5)

    _write_json(PRESENCE_STATE_PATH, presence_state)
    _operator_write_state(operator_state)


def _is_nudge_allowed_and_wise(now_dt: datetime, operator_state: Dict[str, Any]) -> tuple[bool, str]:
    now_hour = now_dt.hour
    now_ts = int(now_dt.timestamp())

    if not _telegram_messages_allowed_now(now_hour):
        return False, "outside_allowed_hours"

    day_phase = operator_state.get("day_phase")
    if day_phase == "quiet_hours":
        return False, "sleep_or_quiet_hours"

    nudge_state = operator_state.setdefault("nudge_fatigue", {})

    # Check mute_until lock
    mute_until = int(nudge_state.get("mute_until_ts") or 0)
    if mute_until > 0 and now_ts < mute_until:
        return False, "muted"

    last_nudge = int(nudge_state.get("last_nudge_ts") or 0)
    cooldown = int(nudge_state.get("cooldown_duration") or 3600)

    if last_nudge > 0 and (now_ts - last_nudge < cooldown):
        return False, "cooldown_active"

    return True, "ok"


def _record_nudge_sent(now_dt: datetime, cooldown: int = 3600) -> None:
    operator_state = _operator_read_state()
    nudge_state = operator_state.setdefault("nudge_fatigue", {})
    nudge_state["last_nudge_ts"] = int(now_dt.timestamp())
    nudge_state["cooldown_duration"] = cooldown
    _operator_write_state(operator_state)


def _build_distraction_nudge_message(duration_sec: int, category: str, salvage: Dict[str, Any]) -> str:
    dur_min = duration_sec // 60
    cat_name = category.replace("distraction_", "").capitalize()

    lines = [
        "<b>Focus check</b>",
        f"I received a desktop signal that looks like {cat_name.lower()} for about {dur_min} minutes. I am treating that as context, not proof of intent or availability.",
        ""
    ]

    if salvage.get("expired"):
        lines.append("<b>Expired as written:</b>")
        for t in salvage["expired"][:3]:
            lines.append(f"• <s>{_escape_html(t)}</s>")
        lines.append("")

    if salvage.get("closed"):
        lines.append("<b>Closed by time/window:</b>")
        for t in salvage["closed"][:3]:
            lines.append(f"• {t} (draft, schedule, or move to tomorrow)")
        lines.append("")

    if salvage.get("still_useful"):
        lines.append("<b>Still useful now:</b>")
        for t in salvage["still_useful"][:3]:
            lines.append(f"• {_escape_html(t)}")
        lines.append("")

    best_move = salvage.get("still_useful")[0] if salvage.get("still_useful") else "Draft tomorrow's items"
    lines.append("<b>Best recovery:</b>")
    lines.append(f"Spend 5 minutes on: {_escape_html(str(best_move))}. If that is wrong, mute or defer instead.")

    return "\n".join(lines)


def _handle_distraction_event(event_type: str, payload: Dict[str, Any], now_dt: datetime) -> Dict[str, Any]:
    operator_state = _operator_read_state()
    allowed, reason = _is_nudge_allowed_and_wise(now_dt, operator_state)
    if not allowed:
        return {"handled": True, "event_type": event_type, "nudge_sent": False, "reason": reason}

    try:
        intel = _todoist_intelligence({"filter": "today | overdue", "limit": 20})
        tasks = list(((intel.get("active_tasks") or {}).get("tasks")) or [])
    except Exception:
        tasks = []

    analysis = _common_sense_analyze_tasks(tasks, now=now_dt)
    salvage = analysis.get("late_day_salvage") or {}

    duration_sec = int(payload.get("duration_sec") or 0)
    category = str(payload.get("category") or "unknown")

    msg = _build_distraction_nudge_message(duration_sec, category, salvage)

    buttons = [
        {"text": "⚡ 5-Min Sprint", "callback_data": "po:sprint:start"},
        {"text": "☕ Take Break", "callback_data": "po:nudge_mute:1h"},
        {"text": "🔄 Defer Remaining", "callback_data": "po:defer_all_today"}
    ]

    _safe_send_telegram_message(msg, parse_mode="HTML", buttons=buttons)
    _record_nudge_sent(now_dt, cooldown=3600)

    return {"handled": True, "event_type": event_type, "nudge_sent": True, "message": msg, "summary": f"Sent distraction nudge for {category}."}


def _classify_task_role(task: Dict[str, Any]) -> str:
    content = str(task.get("content") or "").lower()
    labels = [str(l).lower() for l in task.get("labels") or []]
    due_info = task.get("due") or {}
    is_recurring = bool(due_info.get("is_recurring"))

    # 1. Check explicit classification labels first
    if "family_anchor" in labels:
        return "family_anchor"
    if "fitness_anchor" in labels:
        return "fitness_anchor"
    if "routine" in labels:
        return "routine"
    if "reference" in labels:
        return "reference"
    if "checklist_item" in labels:
        return "checklist_item"
    if "task_debt" in labels:
        return "task_debt"
    if "exclude_workload" in labels:
        return "exclude_workload"
    if "hermes_hidden" in labels:
        return "hermes_hidden"

    # 2. Fallbacks
    # Family & Life Anchors
    family_words = {"family", "son", "wife", "outing", "playtime", "parent"}
    if any(w in content for w in family_words) or "family_anchor" in labels:
        return "family_anchor"

    # Fitness / Gym / Workout
    fitness_words = {"workout", "gym", "fitness", "upper", "lower", "recovery day", "cardio", "nutrition"}
    if any(w in content for w in fitness_words) or "fitness_anchor" in labels or task.get("project_id") == "6ghFPf6XX9Hv3h6p":
        return "fitness_anchor"

    # Routines & Habits
    routine_words = {"routine", "daily", "habit", "checklist", "shut down", "morning launch", "reset"}
    routine_labels = {"routine", "daily", "habit", "health"}
    if is_recurring or any(w in content for w in routine_words) or any(l in routine_labels for l in labels):
        return "routine"

    # Focus Work
    priority = int(task.get("priority") or 1)
    if priority >= 3:
        return "focus"

    return "admin"


def _classify_task_type(task: Dict[str, Any]) -> str:
    return _classify_task_role(task)


def _classify_task_decision_load(task: Dict[str, Any], is_debt: bool = False) -> str:
    if is_debt:
        return "debt"

    role = _classify_task_role(task)
    if role in ("family_anchor", "routine"):
        return "routine"

    content = str(task.get("content") or "").lower()
    labels = [str(l).lower() for l in task.get("labels") or []]

    decision_words = {
        "plan", "choice", "choose", "communication", "review", "write", "decide",
        "call", "email", "meeting", "discuss", "strategy", "someday", "maybe",
        "triage", "cleanup", "clean up"
    }
    has_decision_word = any(w in content for w in decision_words)
    has_decision_label = any(l in ("deep_work", "focus", "decision") for l in labels)
    priority = int(task.get("priority") or 1)

    if role == "focus" or priority >= 3 or has_decision_word or has_decision_label:
        return "decision_heavy"

    return "execution_only"


def _operator_evaluate_yesterday_predictions(operator_state: Dict[str, Any], current_tasks: List[Dict[str, Any]]) -> None:
    briefing_predictions = operator_state.setdefault("briefing_predictions", {})
    current_ids = {t.get("id") for t in current_tasks if t.get("id")}

    analytics = operator_state.setdefault("behavioral_analytics", {
        "completions_count": 0,
        "ignores_count": 0,
        "history": []
    })

    recent_completions = []
    try:
        recent_completions = _get_recent_completions()
    except Exception:
        pass
    completed_task_ids = {str(c.get("task_id")) for c in recent_completions if c.get("task_id")}

    today_str = datetime.now(_runtime_local_tz()).date().isoformat()

    for date_str, pred in list(briefing_predictions.items()):
        if date_str == today_str or pred.get("completed"):
            continue

        predicted_ids = pred.get("predicted_top_tasks") or []
        if not predicted_ids:
            pred["completed"] = True
            continue

        completed_ids = []
        ignored_ids = []
        for pid in predicted_ids:
            if pid in completed_task_ids or pid not in current_ids:
                completed_ids.append(pid)
            else:
                ignored_ids.append(pid)

        pred["completed"] = True
        pred["completed_tasks"] = completed_ids
        pred["ignored_tasks"] = ignored_ids

        analytics["completions_count"] += len(completed_ids)
        analytics["ignores_count"] += len(ignored_ids)
        analytics["history"].append({
            "date": date_str,
            "completed_count": len(completed_ids),
            "ignored_count": len(ignored_ids)
        })


def _run_scheduler_checks(now_dt: datetime) -> None:
    now_ts = int(now_dt.timestamp())
    operator_state = _operator_read_state()
    state_changed = False
    sent_cycle_message = False

    # 1. Active Sprint check
    sprint = operator_state.get("active_sprint")
    if sprint:
        started_at = int(sprint.get("started_at", 0))
        duration = int(sprint.get("duration", 300))
        if now_ts >= started_at + duration:
            operator_state.pop("active_sprint", None)
            state_changed = True
            msg = "<b>🎉 Sprint Complete!</b>\nGreat job! You focused for 5 minutes. Would you like to start another, or take a clean 5-minute break?"
            buttons = [
                {"text": "⚡ Start Another Sprint", "callback_data": "po:sprint:start"},
                {"text": "☕ Take a Break", "callback_data": "po:nudge_mute:1h"}
            ]
            _safe_send_telegram_message(msg, parse_mode="HTML", buttons=buttons)
            sent_cycle_message = True

    # 2. Daily boundary checks / transitions
    tz = _runtime_local_tz()
    local_now = now_dt.astimezone(tz)
    local_hour = local_now.hour
    local_min = local_now.minute

    current_phase = "quiet_hours"
    if 9 <= local_hour < 18:
        current_phase = "work_window"
    elif 18 <= local_hour < 22:
        current_phase = "evening"
    else:
        current_phase = "quiet_hours"

    last_phase = operator_state.get("day_phase")
    if last_phase != current_phase:
        operator_state["day_phase"] = current_phase
        state_changed = True
        if last_phase is not None:
            if current_phase == "work_window":
                # Morning Repair Loop (7-Minute Clean)
                had_debt = operator_state.get("last_briefing_had_debt")
                if had_debt:
                    operator_state["last_briefing_had_debt"] = False

                    try:
                        all_tasks = _focus_guard_read_todoist_tasks()
                        from datetime import date
                        today_date = local_now.date()

                        overdue = []
                        for t in all_tasks:
                            # Skip reference, hidden, duplicate, and checklist items from workload calculation
                            lbls = [str(l).lower() for l in t.get("labels") or []]
                            if any(l in {"exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate"} for l in lbls):
                                continue

                            due_info = t.get("due") or {}
                            due_date_str = due_info.get("date")
                            if due_date_str:
                                try:
                                    date_part = due_date_str.split("T")[0]
                                    task_due_date = date.fromisoformat(date_part)
                                    if task_due_date < today_date:
                                        overdue.append(t)
                                except Exception:
                                    pass

                        shown_counts = operator_state.get("shown_task_counts", {})
                        critical_overdue = []
                        for t in overdue:
                            priority = int(t.get("priority") or 1)
                            t_id = t.get("id")
                            is_stuck = t_id and shown_counts.get(t_id, 0) >= 5
                            if priority >= 3 or is_stuck:
                                critical_overdue.append(t)

                        if not critical_overdue:
                            critical_overdue = overdue

                        lines = [
                            "<b>☀️ Morning Repair Loop (7-Minute Clean)</b>",
                            "Before starting work, let’s spend 7 minutes cleaning task debt. I’ll show only overdue items that are either high-priority, repeated, or stuck.",
                            ""
                        ]

                        to_show = critical_overdue[:3]
                        for t in to_show:
                            escaped_content = _escape_html(t.get("content", "").strip())
                            lines.append(f"  • <b>{escaped_content}</b>")

                        lines.append("\n<i>Tap one of the quick actions below to process these, or reply to clear the deck!</i>")

                        buttons = [
                            {"text": "🧹 Triage Backlog", "callback_data": "po:briefing:triage"},
                            {"text": "🔄 Defer All Today", "callback_data": "po:defer_all_today"}
                        ]
                        _safe_send_telegram_message("\n".join(lines), parse_mode="HTML", buttons=buttons)
                        sent_cycle_message = True
                    except Exception:
                        # Stay quiet if a concrete repair brief cannot be built.
                        pass
                else:
                    pass

            elif current_phase == "quiet_hours":
                cleanup_res = _run_auto_cleanup_routines()
                logs = cleanup_res.get("logs", [])
                msg = "<b>🌙 Quiet Hours Started</b>\nRemaining tasks deferred to keep evening clear.\n"
                if logs:
                    msg += "\n".join([f"• {_escape_html(l)}" for l in logs])
                _safe_send_telegram_message(msg, parse_mode="HTML")
                sent_cycle_message = True

    # 3. Evening Briefing check (9:45 PM tomorrow preview)
    if local_hour == 21 and local_min >= 45:
        today_str = local_now.date().isoformat()
        last_brief = operator_state.get("last_evening_briefing_date")
        if last_brief != today_str:
            # Mark as sent immediately to prevent concurrent triggers
            operator_state["last_evening_briefing_date"] = today_str
            state_changed = True

            try:
                from datetime import date
                # Fetch all tasks programmatically to separate tomorrow, missed today, and overdue
                all_tasks = _focus_guard_read_todoist_tasks()

                # Rule 1: Prediction vs reality loop - Evaluate yesterday's predictions
                _operator_evaluate_yesterday_predictions(operator_state, all_tasks)

                today_date = local_now.date()
                tomorrow_date = today_date + timedelta(days=1)

                tomorrow_tasks = []
                overdue_tasks = []
                missed_today_tasks = []

                for t in all_tasks:
                    # Skip reference, hidden, duplicate, and checklist items from workload calculation
                    lbls = [str(l).lower() for l in t.get("labels") or []]
                    if any(l in {"exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate"} for l in lbls):
                        continue

                    due_info = t.get("due") or {}
                    due_date_str = due_info.get("date")
                    if not due_date_str:
                        continue
                    try:
                        date_part = due_date_str.split("T")[0]
                        task_due_date = date.fromisoformat(date_part)
                    except Exception:
                        continue

                    if task_due_date == tomorrow_date:
                        tomorrow_tasks.append(t)
                    elif task_due_date == today_date:
                        missed_today_tasks.append(t)
                    elif task_due_date < today_date:
                        overdue_tasks.append(t)

                # Rule 3 & 4: Stale-task decay and quarantining
                active_overdue_tasks = []
                stale_backlog_tasks = []
                for t in overdue_tasks:
                    due_info = t.get("due") or {}
                    due_date_str = due_info.get("date")
                    is_stale = False
                    if due_date_str:
                        try:
                            date_part = due_date_str.split("T")[0]
                            task_due_date = date.fromisoformat(date_part)
                            overdue_days = (today_date - task_due_date).days
                            priority = int(t.get("priority") or 1)
                            if overdue_days >= 7 and priority < 4:
                                is_stale = True
                        except Exception:
                            pass
                    if is_stale:
                        stale_backlog_tasks.append(t)
                    else:
                        active_overdue_tasks.append(t)

                # Increment shown counts for all tasks evaluated (Rule 2: Task survivorship)
                shown_counts = operator_state.setdefault("shown_task_counts", {})
                for t in tomorrow_tasks + active_overdue_tasks:
                    t_id = t.get("id")
                    if t_id:
                        shown_counts[t_id] = shown_counts.get(t_id, 0) + 1

                # Separate stuck tasks
                stuck_tasks = []
                unstuck_tomorrow_tasks = []
                for t in tomorrow_tasks:
                    t_id = t.get("id")
                    if t_id and shown_counts.get(t_id, 0) >= 5:
                        stuck_tasks.append(t)
                    else:
                        unstuck_tomorrow_tasks.append(t)

                unstuck_overdue_tasks = []
                for t in active_overdue_tasks:
                    t_id = t.get("id")
                    if t_id and shown_counts.get(t_id, 0) >= 5:
                        stuck_tasks.append(t)
                    else:
                        unstuck_overdue_tasks.append(t)

                display_tomorrow_count = len(tomorrow_tasks)
                display_debt_count = len(unstuck_overdue_tasks) + len(missed_today_tasks)
                stale_count = len(stale_backlog_tasks)

                # Save whether this briefing had heavy debt for morning repair loop check
                operator_state["last_briefing_had_debt"] = (display_debt_count >= 10)

                # Rule 4: Protective Omission policy is explicit
                evening_briefing_should_not_show_full_backlog = True

                # Classify tomorrow's tasks for scoring decision load (Rule 2)
                family_anchors = []
                fitness_anchors = []
                focus_tasks = []
                routines = []
                admins = []

                decision_heavy_tasks = []
                execution_only_tasks = []

                for t in unstuck_tomorrow_tasks:
                    role = _classify_task_role(t)
                    if role == "family_anchor":
                        family_anchors.append(t)
                    elif role == "fitness_anchor" or "fitness_anchor" in [l.lower() for l in t.get("labels") or []]:
                        fitness_anchors.append(t)
                    elif role == "routine":
                        routines.append(t)
                    else:
                        load_cat = _classify_task_decision_load(t, is_debt=False)
                        if load_cat == "decision_heavy":
                            decision_heavy_tasks.append(t)
                        else:
                            execution_only_tasks.append(t)

                        if role == "focus":
                            focus_tasks.append(t)
                        else:
                            admins.append(t)

                # Filter tomorrow workload tasks: exclude family/fitness anchors
                tomorrow_workload_tasks = focus_tasks + admins + routines
                display_tomorrow_count = len(tomorrow_workload_tasks)
                display_debt_count = len(unstuck_overdue_tasks) + len(missed_today_tasks)
                stale_count = len(stale_backlog_tasks)

                # Save whether this briefing had heavy debt for morning repair loop check
                operator_state["last_briefing_had_debt"] = (display_debt_count >= 10)

                # Rule 4: Protective Omission policy is explicit
                evening_briefing_should_not_show_full_backlog = True

                triage_mode = (display_debt_count >= 10)

                # Briefing Memory Introductory copy (Rule 7)
                last_mode = operator_state.get("last_evening_briefing_mode")
                operator_state["last_evening_briefing_mode"] = "task_debt_triage" if triage_mode else "standard"

                lines = []

                # Done Enough celebratory header (Rule 8)
                completed_today = 0
                try:
                    recent_comps = _get_recent_completions()
                    for c in recent_comps:
                        completed_at_str = c.get("completed_at")
                        if completed_at_str:
                            comp_date = datetime.fromisoformat(completed_at_str.replace("Z", "+00:00")).astimezone(tz).date()
                            if comp_date == today_date:
                                completed_today += 1
                except Exception:
                    pass

                if completed_today >= 3:
                    lines.append("<b>🎉 You moved the important pieces today. Tomorrow has some cleanup, but nothing needs solving tonight.</b>\n")

                if triage_mode:
                    lines.append("<b>📅 Tomorrow's Preview: Sleep-Safe Triage</b>")
                    if last_mode == "task_debt_triage":
                        lines.append("<i>Same situation as last night: tomorrow itself is manageable, but the overdue queue still needs a cleanup pass.</i>\n")
                    else:
                        lines.append(f"Tomorrow's scheduled workload is manageable ({display_tomorrow_count} scheduled workload item{'s' if display_tomorrow_count != 1 else ''}).\n")
                else:
                    lines.append("<b>📅 Tomorrow's Todoist Preview</b>")

                # Workload / Decision Load statement (Rule 2)
                lines.append(f"Tomorrow has {display_tomorrow_count} scheduled workload item{'s' if display_tomorrow_count != 1 else ''}, but only {len(decision_heavy_tasks)} require{'s' if len(decision_heavy_tasks) == 1 else ''} real decisions.")
                lines.append("")

                # Carryover debt quarantine
                if display_debt_count > 0:
                    lines.append(f"There is also a backlog of {display_debt_count} overdue or carryover item{'s' if display_debt_count != 1 else ''} in quarantine. None of these need to be decided tonight—they need cleanup, not panic.")
                    lines.append("")

                # Rule 3: Stale task decay message
                if stale_count > 0:
                    lines.append(f"<i>{stale_count} overdue item{'s' if stale_count != 1 else ''} look stale rather than urgent. I’ll keep them out of tomorrow’s workload unless you promote them.</i>")
                    lines.append("")

                # Rule 4 & 5: Protective omission limit - Hard max of 3 focus items shown
                to_show = (focus_tasks + admins)[:3]
                if to_show:
                    lines.append("<b>⭐ Focus Work to Protect:</b>")
                    for t in to_show:
                        t_id = t.get("id")
                        escaped_content = _escape_html(t.get("content", "").strip())
                        due_time = t.get("due", {}).get("datetime")
                        time_str = ""
                        if due_time:
                            try:
                                dt_due = datetime.fromisoformat(due_time.replace("Z", "+00:00")).astimezone(tz)
                                time_str = f" [at {dt_due.strftime('%I:%M %p').lstrip('0')}]"
                            except Exception:
                                pass
                        if t_id:
                            lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{time_str}")
                        else:
                            lines.append(f"  • {escaped_content}{time_str}")
                    lines.append("")

                # Rule 6 & 8: Sacred Family & Fitness Anchors
                if family_anchors or fitness_anchors:
                    lines.append("<b>☖ Protected Family & Fitness Anchors:</b>")
                    for t in family_anchors + fitness_anchors:
                        t_id = t.get("id")
                        escaped_content = _escape_html(t.get("content", "").strip())
                        role = _classify_task_role(t)
                        emoji = "🌸" if role == "family_anchor" else "💪"
                        if t_id:
                            lines.append(f"  • {emoji} <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>")
                        else:
                            lines.append(f"  • {emoji} {escaped_content}")
                    lines.append("<i>Family & fitness anchors are already protected. I’m not counting them as workload.</i>")
                    lines.append("")

                # Stuck task intervention block (Rule 3)
                if stuck_tasks:
                    lines.append("<b>⚠️ Stuck Tasks Needing Intervention:</b>")
                    for t in stuck_tasks[:2]:
                        escaped_content = _escape_html(t.get("content", "").strip())
                        count = shown_counts.get(t.get("id"), 5)
                        lines.append(f"  • <b>{escaped_content}</b> (carried forward {count} times)")
                    lines.append("<i>These tasks keep surviving. Use the options below to shrink, defer, or archive them.</i>")
                    lines.append("")

                # Summarize remaining routine/admin items stress-free
                total_remaining_routines = len(tomorrow_workload_tasks) - len(to_show) - len([st for st in stuck_tasks if st in tomorrow_workload_tasks])
                if total_remaining_routines > 0:
                    lines.append("<b>🔄 Routines & Low-Pressure Backlog:</b>")
                    lines.append(f"Plus {total_remaining_routines} lower-priority routine/admin item{'s' if total_remaining_routines != 1 else ''}, summarized for tomorrow morning. No need to mentally sort them tonight.")
                    lines.append("")

                # Rule 1 & 8: Support and clean exit closure line (no disturb my nervous system)
                closure_options = [
                    "Nothing else needs sorting tonight.",
                    "Tomorrow has a first move. You can leave the rest for morning.",
                    "The list is captured. You do not need to keep it in your head."
                ]
                day_of_month = local_now.day
                closure_line = closure_options[day_of_month % len(closure_options)]
                lines.append(f"<i>{closure_line}</i>")
                lines.append("<i>Tomorrow morning: spend 10 minutes deciding what to reschedule, delete, delegate, or do. Enjoy a restful evening! 🌟</i>")

                # Inline buttons for feedback controls (Rule 5)
                buttons = [
                    {"text": "🧹 Triage Overdue", "callback_data": "po:briefing:triage"},
                    {"text": "🌙 Quiet Mode", "callback_data": "po:briefing:quiet"},
                    {"text": "⭐ Show Top 3 Only", "callback_data": "po:briefing:top3"}
                ]
                if stuck_tasks:
                    fs_id = stuck_tasks[0].get("id")
                    buttons.append({"text": "⚡ Shrink Stuck Task", "callback_data": f"po:stuck:shrink:{fs_id}"})
                    buttons.append({"text": "💤 Move to Someday", "callback_data": f"po:stuck:someday:{fs_id}"})

                # Track predicted top task IDs for learning loop evaluation tomorrow
                predicted_top_ids = [t.get("id") for t in to_show if t.get("id")]
                briefing_predictions = operator_state.setdefault("briefing_predictions", {})
                briefing_predictions[today_str] = {
                    "predicted_top_tasks": predicted_top_ids,
                    "completed": False
                }

                _safe_send_telegram_message("\n".join(lines), force=True, parse_mode="HTML", buttons=buttons)
                sent_cycle_message = True
            except Exception:
                pass

    # 4. Periodic past due task nudge checks
    # Only run the check every 15 minutes to avoid rate-limiting or heavy resources
    last_past_due_check = int(operator_state.get("last_past_due_check_ts") or 0)
    if not sent_cycle_message and 7 <= local_hour < 22 and (now_ts - last_past_due_check >= 900):
        operator_state["last_past_due_check_ts"] = now_ts
        state_changed = True

        try:
            from datetime import date

            # Fetch active tasks due today or overdue
            tasks = _focus_guard_read_todoist_tasks(filter="today | overdue")
            reminded_task_ids = operator_state.setdefault("past_due_reminders_sent", [])
            postpone_counts = operator_state.get("task_postpone_counts", {})

            # Load presence state
            presence_s = _read_json(PRESENCE_STATE_PATH, {})
            location = str(presence_s.get("location", "home")).strip().lower()
            state = str(presence_s.get("state", "")).strip().lower()
            active_cat = str(presence_s.get("active_category", "")).strip().lower()

            overdue_to_remind = []

            for t in tasks:
                t_id = t.get("id")
                if not t_id:
                    continue

                due = t.get("due") or {}
                due_date_str = due.get("date")
                if not due_date_str:
                    continue

                # Check category of the task
                task_content = t.get("content", "").strip()
                labels = [str(l).lower() for l in t.get("labels") or []]
                is_gym = "fitness_anchor" in labels or "workout" in task_content.lower() or "gym" in task_content.lower()
                is_family = "family_anchor" in labels or any(w in task_content.lower() for w in ["wife", "son", "playtime", "outing"])
                is_business = "business_owner" in labels or "deep_work" in labels or "owner" in task_content.lower() or "ceo" in task_content.lower()

                # 1. Focus Protection Rule
                if is_business and state == "desk" and active_cat == "editor":
                    # Deep Work Active -> Suppress work nudges to protect flow
                    continue

                # 2. Location & Boundary Rules
                if is_gym and location == "gym":
                    # Already at the gym -> suppress gym nudge
                    continue
                if is_business and location == "home":
                    # Work-to-Home boundary lock -> mute work nudges at home
                    continue

                is_past_due = False
                reason = ""
                milestone = ""

                # If there's a specific time component in due_date_str
                if "T" in due_date_str:
                    try:
                        dt_due = _parse_todoist_datetime(due_date_str)
                        if dt_due.tzinfo is None:
                            dt_due = dt_due.replace(tzinfo=tz)

                        elapsed_minutes = (local_now - dt_due).total_seconds() / 60

                        # Milestones:
                        if is_gym and location == "home" and -15 <= elapsed_minutes < 0:
                            # 15 minutes before gym time and still at home -> transition prep
                            milestone = "gym_transition"
                            is_past_due = True
                            reason = "gym_prep"
                        elif 0 <= elapsed_minutes <= 5:
                            # 0 to 5 minutes past (Due time)
                            milestone = "due_time"
                            is_past_due = True
                            reason = "past_due_time"
                        elif 15 <= elapsed_minutes <= 25:
                            # 20 minutes past (Short delay)
                            milestone = "short_delay"
                            is_past_due = True
                            reason = "past_due_time"
                        elif 55 <= elapsed_minutes <= 65:
                            # 60 minutes past (Long delay)
                            milestone = "long_delay"
                            is_past_due = True
                            reason = "past_due_time"
                    except Exception:
                        pass
                else:
                    # All-day task (e.g. '2026-05-25')
                    try:
                        date_part = due_date_str.split("T")[0]
                        task_due_date = date.fromisoformat(date_part)
                        if task_due_date < local_now.date():
                            milestone = "overdue_backlog"
                            is_past_due = True
                            reason = "past_due_date"
                    except Exception:
                        pass

                if is_past_due and milestone:
                    reminder_key = f"{t_id}:{due_date_str}:{milestone}"
                    if reminder_key not in reminded_task_ids:
                        overdue_to_remind.append((t, reminder_key, reason, milestone))

            if overdue_to_remind:
                # Limit to 1 task reminder per scan (highest priority first)
                overdue_to_remind.sort(key=lambda item: int(item[0].get("priority", 1)), reverse=True)

                target_task, reminder_key, reason, milestone = overdue_to_remind[0]
                task_content = target_task.get("content", "").strip()
                t_id = target_task.get("id")

                escaped_content = _escape_html(task_content)
                due_info = target_task.get("due") or {}
                time_str = ""
                if "T" in due_info.get("date", ""):
                    try:
                        dt_due = _parse_todoist_datetime(due_info["date"]).astimezone(tz)
                        time_str = f" scheduled for {dt_due.strftime('%I:%M %p').lstrip('0')}"
                    except Exception:
                        pass

                labels = [str(l).lower() for l in target_task.get("labels") or []]
                is_gym = "fitness_anchor" in labels or "workout" in task_content.lower() or "gym" in task_content.lower()
                is_family = "family_anchor" in labels or any(w in task_content.lower() for w in ["wife", "son", "playtime", "outing"])
                is_business = "business_owner" in labels or "deep_work" in labels or "owner" in task_content.lower() or "ceo" in task_content.lower()

                # Check Deferral Fatigue (postponed >= 3 times)
                deferral_count = postpone_counts.get(t_id, 0)

                if deferral_count >= 3:
                    # Deferral fatigue intervention message
                    msg = f"<b>⚠️ Deferral fatigue detected: {escaped_content}</b>\n\nMikail, we've deferred this priority {deferral_count} times today. Rather than pushing against friction, let's play it smart. We can either park it guilt-free in Someday/Maybe to clear your headspace, or resize it to a tiny 2-minute micro-step to build momentum. What's your play? 🌸"
                    buttons = [
                        {"text": "💤 Park in Someday", "callback_data": f"po:task_someday:{t_id}"},
                        {"text": "⚡ Shrink to 2-Min", "callback_data": f"po:task_shrink:{t_id}"},
                        {"text": "📅 Defer Tomorrow", "callback_data": f"po:task_defer:{t_id}"}
                    ]
                else:
                    # Specialized messaging based on category & milestone
                    if is_gym:
                        if reason == "gym_prep":
                            msg = f"<b>🏋️‍♂️ Transition Prep: Lower A Workout</b>\n\nHey Mikail, checking in. Your workout starts in 15 minutes. Let's pack your bag, put down the screen, and transition cleanly to gym mode! Your V-Taper habit starts with this one transition. 💪"
                        else:
                            msg = f"<b>💪 Fitness Nudge: {escaped_content}</b>\n\nHey Mikail! Just a gentle, supportive check-in. This workout{time_str} is past its scheduled time. Let's get this in, move some weight, and stick to your V-Taper habit today. You'll feel incredible once it's done! 🏋️‍♂️"
                    elif is_family:
                        msg = f"<b>☖ Family Focus: {escaped_content}</b>\n\nHi Mikail, checking in. This family connection anchor{time_str} is past its time. Let's make sure we put down the screen, step away from work, and give your full, loving attention to your family. They are the core of it all! 🌸"
                    elif is_business:
                        msg = f"<b>🎯 High-Priority Business Focus: {escaped_content}</b>\n\nHey Mikail! Quick check-in on this business focus item{time_str}. If possible, let's get this one main priority step done now so you can close the loop and protect your evening boundary. You've got this! 🚀"
                    else:
                        if reason == "past_due_time":
                            if milestone == "short_delay":
                                msg = f"<b>🌸 Gentle Reminder: {escaped_content}</b>\n\nHey Mikail! Just noticing this task is past its due time. If you can, let's get this minor piece done now and clear it off your list! ✨"
                            elif milestone == "long_delay":
                                msg = f"<b>⏳ Final Check-In: {escaped_content}</b>\n\nMikail, this task is an hour past due. Let's either get it done in a quick sprint now, or reschedule it honestly to keep your list clean! 🧹"
                            else:
                                msg = f"<b>🌸 Gentle Check-In: {escaped_content}</b>\n\nHey Mikail! Just noticing this task{time_str} is past its scheduled due time today. If it's realistic, let's jump in and get it done now so you can keep the day's momentum going! ✨"
                        else:
                            msg = (
                                f"<b>Backlog Check-In: {escaped_content}</b>\n\n"
                                "This is overdue, but I am not treating overdue as do-now by default. "
                                "Use one small move: finish it, shrink it, schedule the next real window, "
                                "or archive it if it is no longer real."
                            )

                    buttons = [
                        {"text": "✅ Done", "callback_data": f"po:task_complete:{t_id}"},
                        {"text": "📅 Tomorrow", "callback_data": f"po:task_defer:{t_id}"},
                        {"text": "🗑️ Archive", "callback_data": f"po:task_delete:{t_id}"}
                    ]

                _safe_send_telegram_message(msg, parse_mode="HTML", buttons=buttons)

                reminded_task_ids.append(reminder_key)
                if len(reminded_task_ids) > 200:
                    operator_state["past_due_reminders_sent"] = reminded_task_ids[-200:]
        except Exception as e:
            print(f"Error in past due task nudger: {e}")

    if state_changed:
        _operator_write_state(operator_state)


def _runtime_event_ingest(args: Dict[str, Any]) -> Dict[str, Any]:
    event_type = str(args.get("event_type") or "").strip().lower()
    if not event_type:
        raise ValueError("event_type is required")
    now = datetime.now(timezone.utc)

    # Parse payload if present (or flat payload fallback)
    payload = args.get("payload")
    if not isinstance(payload, dict):
        payload = {k: v for k, v in args.items() if k not in {"event_type", "source", "dedupe_key"}}

    # 1. Event Bus Log and Deduplication
    source = str(args.get("source") or "manual").strip()
    if event_type.startswith("gym."):
        unverified = _gym_unverified_ios_result(event_type, source, {**payload, **args})
        if unverified is not None:
            return unverified
        off_schedule = _gym_off_schedule_ios_result(event_type, source, {**payload, **args})
        if off_schedule is not None:
            return off_schedule

    dedupe_key = args.get("dedupe_key")
    dedupe_key_s = str(dedupe_key or "").strip()
    event_state_for_dedupe = _runtime_read_event_state()
    recent_dedupe_keys = [
        str(item).strip()
        for item in list(event_state_for_dedupe.get("recent_dedupe_keys") or [])
        if str(item).strip()
    ]
    if dedupe_key_s and dedupe_key_s in recent_dedupe_keys:
        return {"handled": True, "duplicate": True, "event_type": event_type, "summary": "Duplicate event ignored."}
    try:
        from .event_bus import log_event
        bus_res = log_event(source, event_type, payload, dedupe_key=dedupe_key)
        if bus_res.get("duplicate"):
            return {"handled": True, "duplicate": True, "event_type": event_type, "summary": "Duplicate event ignored."}
    except Exception:
        pass

    # 2. Update state builder
    try:
        _update_operator_state_from_event(event_type, source, payload, now)
    except Exception:
        pass

    # 3. Run scheduler checks
    try:
        _run_scheduler_checks(now)
    except Exception:
        pass

    # 4. Handle events
    focus_state = _focus_guard_read_state()
    send_telegram = bool(args.get("send_telegram", False))
    force_send = bool(args.get("force_send", False))
    now_hour = now.astimezone(_runtime_local_tz()).hour
    can_send_now = _telegram_messages_allowed_now(now_hour) or force_send
    passive_presence_only = _is_passive_presence_only_event(event_type, source)
    result: Dict[str, Any]

    if event_type == "location_update":
        _handle_location_update(args)
        result = {"handled": True, "event_type": event_type, "summary": "Updated location state."}
        cleanup_res = _run_auto_cleanup_routines()
        result["cleanup_logs"] = cleanup_res.get("logs", [])
    elif event_type == "wake":
        if not focus_state:
            focus_state = _focus_guard_run_once(filter="today | overdue")
        message = _runtime_build_wake_briefing(focus_state=focus_state, now=now, source=source)
        sent = False
        suppressed_reason = None
        if send_telegram and can_send_now and not (passive_presence_only and not force_send):
            presence_s = _read_json(PRESENCE_STATE_PATH, {})
            location = presence_s.get("location", "home")
            dock_buttons = _build_hermes_dock(location, now)
            try:
                tasks = _focus_guard_read_todoist_tasks(filter="today | overdue")
                top_tasks = _get_top_high_priority_tasks(tasks, 3)
                for t in top_tasks:
                    dock_buttons.append({
                        "text": f"✅ {t.get('content')[:20]}...",
                        "callback_data": f"po:task_complete:{t.get('id')}"
                    })
            except Exception:
                pass
            _safe_send_telegram_message(message, parse_mode="HTML", buttons=dock_buttons)
            sent = True
        elif send_telegram and not can_send_now:
            suppressed_reason = "outside_hours"
        elif send_telegram and passive_presence_only and not force_send:
            suppressed_reason = "presence_signal_only"
        result = {"handled": True, "event_type": event_type, "message": message, "sent": sent, "suppressed_reason": suppressed_reason, "summary": "Built detailed wake briefing."}
    elif event_type == "desktop_unlocked":
        fresh = _canonical_focus_guard_result(_focus_guard_run_once(filter=str(args.get("filter") or "today | overdue")))
        message = _runtime_build_unlock_briefing(focus_state=fresh, now=now, source=source)
        sent = False
        suppressed_reason = None
        if send_telegram and can_send_now and not (passive_presence_only and not force_send):
            presence_s = _read_json(PRESENCE_STATE_PATH, {})
            location = presence_s.get("location", "home")
            dock_buttons = _build_hermes_dock(location, now)
            try:
                tasks = _focus_guard_read_todoist_tasks(filter="today | overdue")
                top_tasks = _get_top_high_priority_tasks(tasks, 3)
                for t in top_tasks:
                    dock_buttons.append({
                        "text": f"✅ {t.get('content')[:20]}...",
                        "callback_data": f"po:task_complete:{t.get('id')}"
                    })
            except Exception:
                pass
            _safe_send_telegram_message(message, parse_mode="HTML", buttons=dock_buttons)
            sent = True
        elif send_telegram and not can_send_now:
            suppressed_reason = "outside_hours"
        elif send_telegram and passive_presence_only and not force_send:
            suppressed_reason = "presence_signal_only"
        result = {"handled": True, "event_type": event_type, "message": message, "sent": sent, "suppressed_reason": suppressed_reason, "focus_guard": fresh, "summary": "Built detailed unlock briefing."}
    elif event_type in {"leaving_house", "outing_request"}:
        result = _runtime_handle_outing_event(args)
    elif event_type == "voice_memo_received":
        result = _runtime_handle_voice_capture(args)
    elif event_type == "activitywatch_heartbeat":
        result = _runtime_handle_activitywatch_heartbeat(args)
    elif event_type.startswith("gym."):
        gym_args = {**payload, **args}
        gym_args["event_type"] = event_type
        gym_args["source"] = source
        result = _runtime_handle_gym_event(gym_args)
    elif event_type == "telegram_feedback":
        result = _operator_record_feedback(args, now=now)
    elif event_type.startswith("desktop.distraction_"):
        result = _handle_distraction_event(event_type, payload, now)
    elif event_type.startswith("desktop.") or event_type.startswith("ios."):
        result = {"handled": True, "event_type": event_type, "summary": f"Processed event {event_type}."}
    else:
        raise ValueError(f"Unsupported event_type: {event_type}")

    state = _runtime_read_event_state()
    record = {
        "ts": now.isoformat(),
        "event_type": event_type,
        "source": source,
        "result_summary": result.get("summary") or result.get("result_summary"),
    }
    explicit_signal = dict(result.get("presence_signal") or {})
    presence_signal = _runtime_write_presence_signal(
        event_type=event_type,
        source=record["source"],
        ts=now,
        override_confidence=(float(explicit_signal.get("confidence")) if explicit_signal.get("confidence") is not None else None),
        override_label=(str(explicit_signal.get("label")) if explicit_signal.get("label") else None),
        extra=explicit_signal,
    )
    state["last_event"] = record
    state["recent_events"] = (list(state.get("recent_events") or []) + [record])[-10:]
    if dedupe_key_s:
        state["recent_dedupe_keys"] = (recent_dedupe_keys + [dedupe_key_s])[-200:]
    _runtime_write_event_state(state)
    _append_event("runtime_event_ingested", {"event_type": event_type, "source": record["source"], "summary": result.get("summary", "")})
    return {**result, "record": record, "event_state": state, "presence_signal": presence_signal}



_LIVE_WATCH_STATE_MAX_LIST_ITEMS = 12
_LIVE_WATCH_STATE_MAX_TEXT_CHARS = 640
_LIVE_WATCH_STATE_MAX_DEPTH = 8
_LIVE_WATCH_STATE_DROP_KEYS = {
    "all_tasks",
    "completed_tasks",
    "raw",
    "raw_completed",
    "raw_completed_tasks",
    "raw_payload",
    "raw_tasks",
    "raw_updated",
    "raw_updated_tasks",
    "todoist_raw",
}


def _compact_live_watch_text(value: str) -> str:
    if len(value) <= _LIVE_WATCH_STATE_MAX_TEXT_CHARS:
        return value
    return value[:_LIVE_WATCH_STATE_MAX_TEXT_CHARS] + "...[truncated]"


def _compact_live_watch_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    compacted = _compact_live_watch_value(payload)
    return compacted if isinstance(compacted, dict) else {}


def _compact_live_watch_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > _LIVE_WATCH_STATE_MAX_DEPTH:
        return "[truncated-depth]"
    if isinstance(value, str):
        return _compact_live_watch_text(value)
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key_s = str(raw_key)
            key_l = key_s.lower()
            if key_l in _LIVE_WATCH_STATE_DROP_KEYS or key_l.startswith("raw_"):
                continue
            result[key_s] = _compact_live_watch_value(raw_value, key=key_s, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [
            _compact_live_watch_value(item, key=key, depth=depth + 1)
            for item in value[:_LIVE_WATCH_STATE_MAX_LIST_ITEMS]
        ]
    return value


def _runtime_live_watch_run(*, filter: Optional[str] = None, always_on: bool = False) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    # Run scheduler checks (day-phase transitions, sprint timers)
    try:
        _run_scheduler_checks(now)
    except Exception:
        pass
    # Run auto-cleanup routines on every live watch loop
    _run_auto_cleanup_routines()
    focus_guard = _canonical_focus_guard_result(_focus_guard_run_once(filter=filter))
    companion = json.loads(handle_adaptive_companion({"action": "run", "always_on": always_on}))
    companion_state = dict(companion.get("state") or {})
    if not companion_state:
        companion_state = _adaptive_companion_read_state()
        if companion_state:
            companion["state"] = companion_state
    surface_policy = dict((companion_state.get("insight_lenses") or {}).get("surface_policy") or {})
    success = bool(companion.get("success"))
    payload = {
        "ran_at": now.isoformat(),
        "filter": filter,
        "always_on": always_on,
        "focus_guard": focus_guard,
        "adaptive_companion": companion,
        "surface_policy": surface_policy,
    }
    try:
        payload["operator_brief"] = _operator_brief({
            "filter": filter or "today | overdue",
            "limit": 12,
            "allow_message": always_on,
            "send_telegram": False,
        })
    except Exception as exc:
        payload["operator_brief_error"] = str(exc)
    try:
        payload["agi_operator_cycle"] = _agi_operator_cycle({
            "filter": filter or "today | overdue",
            "limit": 12,
            "allow_message": always_on,
            "send_telegram": False,
        })
    except Exception as exc:
        payload["agi_operator_cycle_error"] = str(exc)
    status_message = None
    status_message_error = None
    try:
        status_message = _runtime_live_watch_update_status_message(payload)
    except Exception as exc:
        status_message_error = str(exc)
    if status_message:
        payload["status_message"] = status_message
    if status_message_error:
        payload["status_message_error"] = status_message_error
    _write_json(LIVE_WATCH_STATE_PATH, _compact_live_watch_payload(payload))
    _append_event(
        "live_watch_run",
        {
            "filter": filter,
            "focus_status": focus_guard.get("status"),
            "focus_task_count": focus_guard.get("task_count"),
            "always_on": always_on,
            "companion_sent": companion.get("sent"),
            "companion_reason": companion.get("reason"),
            "companion_success": success,
            "surface_mode": surface_policy.get("mode"),
            "status_message_updated": bool(status_message),
            "status_message_error": status_message_error,
            "agi_decision": ((payload.get("agi_operator_cycle") or {}).get("decision") or {}).get("best_move"),
        },
    )
    return {
        "success": success,
        "ran_at": payload["ran_at"],
        "filter": filter,
        "always_on": always_on,
        "focus_guard": focus_guard,
        "adaptive_companion": companion,
        "surface_policy": surface_policy,
        "status_message": status_message,
        "status_message_error": status_message_error,
        "operator_brief": payload.get("operator_brief"),
        "operator_brief_error": payload.get("operator_brief_error"),
        "agi_operator_cycle": payload.get("agi_operator_cycle"),
        "agi_operator_cycle_error": payload.get("agi_operator_cycle_error"),
    }


def _runtime_parse_iso(ts: Optional[str]) -> Optional[datetime]:
    raw = str(ts or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _runtime_read_cron_jobs() -> Dict[str, Any]:
    data = _read_json(CRON_JOBS_PATH, {"jobs": []})
    if not isinstance(data, dict):
        return {"jobs": []}
    data.setdefault("jobs", [])
    return data


def _runtime_write_cron_jobs(data: Dict[str, Any]) -> None:
    _write_json(CRON_JOBS_PATH, data)


def _runtime_ensure_job_enabled(*, data: Dict[str, Any], job_id: str, expected_script: str, expected_expr: str) -> bool:
    jobs = list(data.get("jobs") or [])
    for job in jobs:
        if job.get("id") != job_id:
            continue
        changed = False
        if job.get("script") != expected_script:
            job["script"] = expected_script
            changed = True
        schedule = dict(job.get("schedule") or {})
        if schedule.get("expr") != expected_expr:
            job["schedule"] = {"kind": "cron", "expr": expected_expr, "display": expected_expr}
            job["schedule_display"] = expected_expr
            changed = True
        if not bool(job.get("enabled")):
            job["enabled"] = True
            changed = True
        if job.get("state") != "scheduled":
            job["state"] = "scheduled"
            changed = True
        data["jobs"] = jobs
        return changed
    jobs.append({
        "id": job_id,
        "name": job_id,
        "prompt": f"Run {expected_script}.",
        "skills": [],
        "skill": None,
        "model": None,
        "provider": None,
        "base_url": None,
        "script": expected_script,
        "no_agent": True,
        "context_from": None,
        "schedule": {"kind": "cron", "expr": expected_expr, "display": expected_expr},
        "schedule_display": expected_expr,
        "repeat": {"times": None, "completed": 0},
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "next_run_at": None,
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
        "last_delivery_error": None,
        "deliver": "local",
        "origin": "self_improve",
        "enabled_toolsets": None,
        "workdir": None,
        "profile": None,
    })
    data["jobs"] = jobs
    return True


def _runtime_cron_job_matches(job: Optional[Dict[str, Any]], *, expected_script: str, expected_expr: str) -> bool:
    if not isinstance(job, dict):
        return False
    schedule = dict(job.get("schedule") or {})
    return (
        bool(job.get("enabled"))
        and job.get("state") == "scheduled"
        and job.get("script") == expected_script
        and schedule.get("expr") == expected_expr
    )


def _runtime_restart_user_service(service_name: str) -> Dict[str, Any]:
    result = subprocess.run(
        ["systemctl", "--user", "restart", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    return {
        "service": service_name,
        "ok": result.returncode == 0,
        "output": (result.stdout or result.stderr or "").strip(),
    }


_FORMALIZED_WORKFLOW_CHECKLISTS: Dict[tuple[str, str], Dict[str, Any]] = {
    ("location_update", "ios-shortcut"): {
        "title": "iOS location update",
        "checklist": [
            "Treat the event as location context, not proof of availability.",
            "Update presence/location state deterministically.",
            "Run only quiet cleanup routines; do not send a proactive nudge just because location changed.",
        ],
    },
    ("wake", "windows-logon-trigger"): {
        "title": "Windows wake/logon",
        "checklist": [
            "Treat this as possible activity, not guaranteed presence.",
            "Record a low-confidence presence signal.",
            "Suppress proactive Telegram unless another high-value reason passes policy.",
        ],
    },
    ("wake", "manual"): {
        "title": "Manual wake check",
        "checklist": [
            "Treat this as an explicit diagnostic or user-initiated check.",
            "Build the same cautious wake briefing without claiming physical presence.",
            "Prefer explainable task triage over motivational pressure.",
        ],
    },
    ("gym.arrived", "ios-shortcut"): {
        "title": "Verified gym arrival",
        "checklist": [
            "Require location verification from the iOS shortcut.",
            "Reject off-schedule lifting days before logging.",
            "Open or return the matching workout task instead of inventing attendance.",
        ],
    },
    ("gym.arrived", "ios-shortcut-url"): {
        "title": "Verified gym arrival URL shortcut",
        "checklist": [
            "Require location verification from the URL payload.",
            "Reject off-schedule lifting days before logging.",
            "Return the matching Todoist workout task/app URL when available.",
        ],
    },
    ("gym.left", "ios-shortcut"): {
        "title": "Verified gym departure",
        "checklist": [
            "Require location verification from the iOS shortcut.",
            "Reject off-schedule lifting days before logging.",
            "Avoid auto-completing long/implausible sessions without confirmation.",
        ],
    },
    ("gym.left", "ios-shortcut-url"): {
        "title": "Verified gym departure URL shortcut",
        "checklist": [
            "Require location verification from the URL payload.",
            "Reject off-schedule lifting days before logging.",
            "Avoid auto-completing long/implausible sessions without confirmation.",
        ],
    },
}


_FORMALIZED_INTERVENTION_PATTERNS: Dict[tuple[str, str], Dict[str, Any]] = {
    ("hierarchy_enforcement", "friction_avoidance"): {
        "title": "Evidence-first friction repair",
        "checklist": [
            "Name the higher-value task only when supported by Todoist/current state.",
            "Avoid shame or character judgments.",
            "Offer a concrete repair move: do, split, defer, or mark blocked.",
        ],
    },
}


def _runtime_formalized_workflow(event_type: str, source: str) -> Optional[Dict[str, Any]]:
    return _FORMALIZED_WORKFLOW_CHECKLISTS.get((event_type.strip().lower(), source.strip().lower()))


def _runtime_formalized_intervention(family: str, pattern: str) -> Optional[Dict[str, Any]]:
    return _FORMALIZED_INTERVENTION_PATTERNS.get((family.strip().lower(), pattern.strip().lower()))


def _runtime_detect_candidate_skills(*, companion_state: Dict[str, Any], runtime_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    event_counts: Dict[tuple[str, str], int] = {}
    for item in runtime_events:
        if str(item.get("type") or "") != "runtime_event_ingested":
            continue
        event_type = str(item.get("event_type") or "").strip()
        source = str(item.get("source") or "").strip() or "unknown"
        if not event_type:
            continue
        key = (event_type, source)
        event_counts[key] = event_counts.get(key, 0) + 1

    for (event_type, source), count in sorted(event_counts.items(), key=lambda pair: (-pair[1], pair[0][0], pair[0][1])):
        if count < 3:
            continue
        if _runtime_formalized_workflow(event_type, source):
            continue
        candidates.append(
            {
                "id": f"workflow:{event_type}:{source}",
                "kind": "workflow",
                "title": f"Stabilize {event_type} workflow from {source}",
                "evidence": f"{count} recent '{event_type}' events came from {source}.",
                "why_it_matters": "This looks like a recurring transition Hermes can support with a more explicit method.",
                "next_step": f"Capture the best-response checklist for the {event_type} event and keep it reusable.",
            }
        )

    completion_history = list(companion_state.get("completion_history") or [])
    family_counts: Dict[tuple[str, str], int] = {}
    for item in completion_history:
        family = str(item.get("intervention_family") or item.get("family") or "").strip()
        pattern = str(item.get("pattern") or "").strip()
        if not family or not pattern:
            continue
        key = (family, pattern)
        family_counts[key] = family_counts.get(key, 0) + 1

    for (family, pattern), count in sorted(family_counts.items(), key=lambda pair: (-pair[1], pair[0][0], pair[0][1])):
        if count < 2:
            continue
        if _runtime_formalized_intervention(family, pattern):
            continue
        candidates.append(
            {
                "id": f"intervention:{family}:{pattern}",
                "kind": "intervention",
                "title": f"Reuse {family} for {pattern}",
                "evidence": f"{count} completed tasks followed this intervention-family and pattern pairing.",
                "why_it_matters": "Hermes is seeing the same pressure shape work more than once.",
                "next_step": "Promote this into a stable response pattern instead of rediscovering it each time.",
            }
        )

    style_counts: Dict[str, int] = {}
    for item in completion_history:
        style = str(item.get("style") or "").strip()
        if style:
            style_counts[style] = style_counts.get(style, 0) + 1

    for style, count in sorted(style_counts.items(), key=lambda pair: (-pair[1], pair[0])):
        if count < 3:
            continue
        candidates.append(
            {
                "id": f"style:{style}",
                "kind": "style",
                "title": f"Lean on {style} when completion matters",
                "evidence": f"{count} recent completions followed interventions rendered in the {style} style.",
                "why_it_matters": "A reliable delivery style is emerging, not just a one-off lucky message.",
                "next_step": "Preserve the strongest phrasing patterns from this style as a reusable template.",
            }
        )

    return candidates[:6]


def _runtime_self_improve_run() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    prior_state = _read_json(SELF_IMPROVE_STATE_PATH, {}) if SELF_IMPROVE_STATE_PATH.exists() else {}
    actions: List[Dict[str, Any]] = []
    observations: List[str] = []
    service_memory = dict((prior_state or {}).get("service_memory") or {})
    services = [RUNTIME_SERVICE_NAME, "hermes-event-webhook.service"]
    if _env("TELEGRAM_CAPTURE_BOT_TOKEN"):
        services.append("hermes-capture-bot.service")
    for service_name in services:
        status = _runtime_service_status(service_name)
        if not status.get("active"):
            memory = dict(service_memory.get(service_name) or {})
            seen_failures = int(memory.get("inactive_streak") or 0) + 1
            service_memory[service_name] = {
                "inactive_streak": seen_failures,
                "last_state": status.get("state"),
                "last_checked_at": now.isoformat(),
            }
            if seen_failures >= 2:
                actions.append({"kind": "restart_service", **_runtime_restart_user_service(service_name), "inactive_streak": seen_failures})
                service_memory[service_name]["inactive_streak"] = 0
            else:
                observations.append(f"{service_name} inactive once; waiting for confirmation before restart")
        else:
            observations.append(f"{service_name} active")
            service_memory[service_name] = {
                "inactive_streak": 0,
                "last_state": status.get("state"),
                "last_checked_at": now.isoformat(),
            }

    live_watch = _read_json(LIVE_WATCH_STATE_PATH, {})
    live_watch_ran_at = _runtime_parse_iso((live_watch or {}).get("ran_at"))
    if live_watch_ran_at is None or (now - live_watch_ran_at) > timedelta(minutes=20):
        watch_result = _runtime_live_watch_run(filter="today | overdue", always_on=True)
        actions.append({"kind": "refresh_live_watch", "ok": bool(watch_result.get("success")), "ran_at": watch_result.get("ran_at")})
    else:
        observations.append("live watch current")
        if not (live_watch or {}).get("status_message") and _telegram_messages_allowed_now(now.astimezone().hour):
            payload = dict(live_watch or {})
            try:
                status_message = _runtime_live_watch_update_status_message(payload)
                if status_message:
                    payload["status_message"] = status_message
                    _write_json(LIVE_WATCH_STATE_PATH, _compact_live_watch_payload(payload))
                    actions.append({"kind": "restore_status_message", "ok": True, "message_id": status_message.get("message_id")})
            except Exception as exc:
                actions.append({"kind": "restore_status_message", "ok": False, "error": str(exc)})

    incidents = _runtime_recent_incidents(limit=10)
    if incidents:
        observations.append(f"{len(incidents)} recent incident(s)")
    upstream = _runtime_upstream_status(hours=24)
    behind = int(((upstream.get("local") or {}).get("behind")) or 0)
    origin_ref = str(((upstream.get("local") or {}).get("origin_ref")) or "origin/main")
    if behind > 0:
        observations.append(f"upstream behind by {behind}")

    cron_data = _runtime_read_cron_jobs()
    repaired_jobs: List[str] = []
    if _runtime_ensure_job_enabled(data=cron_data, job_id="hermeslivewatch24x7", expected_script="hermes_live_watch.py", expected_expr="*/15 * * * *"):
        repaired_jobs.append("hermeslivewatch24x7")
    if _runtime_ensure_job_enabled(data=cron_data, job_id="hermesselfimprove24x7", expected_script="hermes_self_improve.py", expected_expr="*/15 * * * *"):
        repaired_jobs.append("hermesselfimprove24x7")
    if repaired_jobs:
        _runtime_write_cron_jobs(cron_data)
        actions.append({"kind": "repair_cron_jobs", "ok": True, "jobs": repaired_jobs})
    else:
        observations.append("cron jobs current")

    companion_state = _read_json(ADAPTIVE_COMPANION_STATE_PATH, {})
    runtime_events = _read_jsonl_recent(EVENTS_PATH, limit=120)
    candidate_skills = _runtime_detect_candidate_skills(
        companion_state=companion_state if isinstance(companion_state, dict) else {},
        runtime_events=runtime_events,
    )
    if candidate_skills:
        observations.append(f"{len(candidate_skills)} candidate skill(s) surfaced")

    state = {
        "ran_at": now.isoformat(),
        "actions": actions,
        "observations": observations,
        "incidents": incidents,
        "service_memory": service_memory,
        "candidate_skills": candidate_skills,
        "upstream": {
            "behind": behind,
            "recent_commit_count": int(upstream.get("recent_commit_count") or 0),
        },
    }
    _write_json(SELF_IMPROVE_STATE_PATH, state)
    _append_event("self_improve_run", {"actions": len(actions), "observations": observations[:5], "behind": behind, "incident_count": len(incidents)})
    return {
        "success": True,
        "ran_at": state["ran_at"],
        "actions": actions,
        "observations": observations,
        "incident_count": len(incidents),
        "upstream_behind": behind,
        "candidate_skills": candidate_skills,
        "summary": f"Self-improve checked {len(services)} service(s), took {len(actions)} action(s), and saw {len(incidents)} incident(s).",
    }


def _runtime_self_improve_report_signature(report: Dict[str, Any]) -> str:
    recommendations = [
        {
            "kind": item.get("kind"),
            "summary": item.get("summary"),
            "requires_approval": item.get("requires_approval"),
        }
        for item in list(report.get("recommendations") or [])
        if item.get("kind") != "no_action"
    ]
    payload = {
        "recommendations": recommendations,
        "upstream": report.get("upstream"),
        "incident_count": report.get("incident_count"),
        "candidate_skill_count": len(report.get("candidate_skills") or []),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _runtime_self_improve_report_message(report: Dict[str, Any], request_id: Optional[str]) -> str:
    recommendations = list(report.get("recommendations") or [])
    actionable = [item for item in recommendations if item.get("kind") != "no_action"]
    completed = list(report.get("completed_improvements") or [])
    lines = [
        "Self-improvement report",
        report.get("summary") or f"Found {len(recommendations)} recommendation(s).",
    ]
    if completed:
        lines.append("Completed improvements:")
        for index, item in enumerate(completed[:5], start=1):
            label = str(item.get("summary") or item.get("message") or item.get("commit") or "").strip()
            if label:
                lines.append(f"{index}. {label}")
    if actionable:
        lines.append("Pending evidence-backed items:")
    for index, item in enumerate(actionable[:5], start=1):
        approval = "approval needed" if item.get("requires_approval") else "safe maintenance"
        lines.append(f"{index}. {item.get('kind')}: {item.get('summary')} ({approval})")
        if item.get("proposed_action"):
            lines.append(f"   Proposed: {item.get('proposed_action')}")
    if not actionable:
        lines.append("No evidence-backed improvement needs action right now.")
    if request_id:
        lines.extend([
            f"Request ID: {request_id}",
            f"Approve: personal_security(action='approve_request', request_id='{request_id}')",
            f"Deny: personal_security(action='deny_request', request_id='{request_id}')",
        ])
    return "\n".join(lines)


def _runtime_recent_completed_improvements(repo_path: Optional[Path] = None, *, limit: int = 8) -> List[Dict[str, Any]]:
    """Return recent deployed commits that represent concrete Hermes improvements."""
    repo_path = Path(repo_path) if repo_path is not None else _runtime_default_repo_path()
    ok, output = _runtime_git_output(
        repo_path,
        ["log", "--since=24 hours ago", f"--max-count={max(int(limit), 1)}", "--pretty=format:%h%x09%ct%x09%s"],
    )
    if not ok or not output:
        return []

    improvements: List[Dict[str, Any]] = []
    for raw in output.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            continue
        commit, ts_raw, message = parts
        try:
            committed_at = datetime.fromtimestamp(int(ts_raw), timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            committed_at = ""
        improvements.append(
            {
                "commit": commit.strip(),
                "committed_at": committed_at,
                "message": message.strip(),
                "summary": f"{commit.strip()}: {message.strip()}",
            }
        )
    return improvements


def _runtime_self_improve_report(*, create_approval: bool = False, send_telegram: bool = True, force_send: bool = False) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    services = [RUNTIME_SERVICE_NAME, "hermes-event-webhook.service"]
    if _env("TELEGRAM_CAPTURE_BOT_TOKEN"):
        services.append("hermes-capture-bot.service")
    service_statuses = [_runtime_service_status(service_name) for service_name in services]
    inactive_services = [item for item in service_statuses if not item.get("active")]
    live_watch = _read_json(LIVE_WATCH_STATE_PATH, {})
    live_watch_ran_at = _runtime_parse_iso((live_watch or {}).get("ran_at"))
    live_watch_age_minutes = None
    if live_watch_ran_at:
        live_watch_age_minutes = int((now - live_watch_ran_at).total_seconds() // 60)
    incidents = _runtime_recent_incidents(limit=10)
    upstream = _runtime_upstream_status(hours=24)
    behind = int(((upstream.get("local") or {}).get("behind")) or 0)
    origin_ref = str(((upstream.get("local") or {}).get("origin_ref")) or "origin/main")
    cron_data = _runtime_read_cron_jobs()
    cron_jobs = {str(job.get("id") or ""): job for job in list(cron_data.get("jobs") or []) if isinstance(job, dict)}
    companion_state = _read_json(ADAPTIVE_COMPANION_STATE_PATH, {})
    runtime_events = _read_jsonl_recent(EVENTS_PATH, limit=120)
    candidate_skills = _runtime_detect_candidate_skills(
        companion_state=companion_state if isinstance(companion_state, dict) else {},
        runtime_events=runtime_events,
    )
    recommendations: List[Dict[str, Any]] = []
    for service in inactive_services:
        recommendations.append({
            "kind": "service_health",
            "summary": f"{service.get('service')} is not active.",
            "proposed_action": "Confirm on the next self-improve run and restart only after repeated inactive checks.",
            "risk": "low_internal",
            "requires_approval": False,
            "evidence": service,
        })
    if live_watch_ran_at is None or (live_watch_age_minutes is not None and live_watch_age_minutes > 20):
        recommendations.append({
            "kind": "live_watch_refresh",
            "summary": "Live watch is stale or missing.",
            "proposed_action": "Run a live watch refresh so operator_brief and agi_operator_cycle stay current.",
            "risk": "low_internal",
            "requires_approval": False,
            "evidence": {"ran_at": (live_watch or {}).get("ran_at"), "age_minutes": live_watch_age_minutes},
        })
    if not (live_watch or {}).get("status_message"):
        recommendations.append({
            "kind": "status_message_restore",
            "summary": "Live watch status message is missing.",
            "proposed_action": "Restore the pinned/status message when Telegram quiet-hours allow it.",
            "risk": "low_internal",
            "requires_approval": False,
            "evidence": {"has_status_message": bool((live_watch or {}).get("status_message"))},
        })
    for job_id, expected_script in {"hermeslivewatch24x7": "hermes_live_watch.py", "hermesselfimprove24x7": "hermes_self_improve.py"}.items():
        job = cron_jobs.get(job_id)
        if not _runtime_cron_job_matches(job, expected_script=expected_script, expected_expr="*/15 * * * *"):
            recommendations.append({
                "kind": "cron_repair",
                "summary": f"{job_id} is missing, disabled, or points at the wrong script.",
                "proposed_action": f"Ensure {job_id} runs {expected_script} every 15 minutes.",
                "risk": "low_internal",
                "requires_approval": False,
                "evidence": job or {"missing": True},
            })
    if behind > 0:
        upstream_summary = f"Hermes upstream has changes; local checkout is {behind} commit(s) behind {origin_ref}."
        recommendations.append({
            "kind": "upstream_review",
            "summary": upstream_summary,
            "proposed_action": "Review upstream changes and compare them against the deployed branch before applying code updates.",
            "risk": "code_change_requires_review",
            "requires_approval": True,
            "evidence": {
                "behind": behind,
                "origin_ref": origin_ref,
                "recent_commit_count": int(upstream.get("recent_commit_count") or 0),
            },
        })
    if incidents:
        recommendations.append({
            "kind": "incident_review",
            "summary": f"{len(incidents)} recent incident(s) need inspection.",
            "proposed_action": "Inspect incidents and propose targeted fixes instead of guessing.",
            "risk": "diagnostic_only",
            "requires_approval": False,
            "evidence": incidents[:5],
        })
    if candidate_skills:
        recommendations.append({
            "kind": "candidate_skill_review",
            "summary": f"{len(candidate_skills)} candidate improvement pattern(s) surfaced.",
            "proposed_action": "Review candidate skills and approve implementation separately if useful.",
            "risk": "design_change_requires_review",
            "requires_approval": True,
            "evidence": candidate_skills[:5],
        })
    if not recommendations:
        recommendations.append({
            "kind": "no_action",
            "summary": "No useful self-improvement action is currently supported by evidence.",
            "proposed_action": "Stay quiet and check again later.",
            "risk": "none",
            "requires_approval": False,
            "evidence": {"services_checked": len(services), "incidents": 0, "upstream_behind": behind},
        })
    report = {
        "generated_at": now.isoformat(),
        "summary": f"Self-improve report found {len(recommendations)} recommendation(s).",
        "completed_improvements": _runtime_recent_completed_improvements(limit=8),
        "services": service_statuses,
        "live_watch": {
            "ran_at": (live_watch or {}).get("ran_at"),
            "age_minutes": live_watch_age_minutes,
            "has_operator_brief": bool((live_watch or {}).get("operator_brief")),
            "has_agi_operator_cycle": bool((live_watch or {}).get("agi_operator_cycle")),
        },
        "upstream": {
            "behind": behind,
            "origin_ref": origin_ref,
            "recent_commit_count": int(upstream.get("recent_commit_count") or 0),
        },
        "incident_count": len(incidents),
        "candidate_skills": candidate_skills,
        "recommendations": recommendations,
        "approval_policy": "Applying maintenance is approval-gated through personal_security. Code changes, external messages, public posts, financial actions, and destructive edits remain separate approvals.",
    }
    signature = _runtime_self_improve_report_signature(report)
    state = _read_json(SELF_IMPROVE_STATE_PATH, {}) if SELF_IMPROVE_STATE_PATH.exists() else {}
    state = state if isinstance(state, dict) else {}
    report_state = dict((state or {}).get("report_delivery") or {})
    last_sent_at = _runtime_parse_iso(str(report_state.get("last_sent_at") or ""))
    last_signature = str(report_state.get("last_signature") or "")
    recently_sent = bool(last_sent_at and (now - last_sent_at) < timedelta(hours=12) and last_signature == signature)
    can_send_now = bool(force_send or _telegram_messages_allowed_now())
    should_create_approval = bool(create_approval and (not send_telegram or (not recently_sent and can_send_now)))
    request_id: Optional[str] = None
    response: Dict[str, Any]
    if not should_create_approval:
        response = {"success": True, "action": "self_improve_report", "report": report, "approval_required": False}
    else:
        approval_payload = {"action": "self_improve_apply", "report": report}
        response = json.loads(_create_approval(
            tool_name="personal_runtime",
            action="apply_self_improve_report",
            summary="apply Hermes self-improvement maintenance plan",
            reason="Hermes found maintenance or review items and should not apply them invisibly.",
            benefit="You get a visible report first, then approve only if the plan looks right.",
            payload=approval_payload,
        ))
        request_id = str(response.get("request_id") or "")
        response = {
            **response,
            "action": "self_improve_report",
            "report": report,
        }
    if send_telegram and not recently_sent and can_send_now:
        message = _runtime_self_improve_report_message(report, request_id or str(response.get("request_id") or ""))
        send_result = _focus_guard_send_telegram_message(message)
        response["sent"] = not bool(send_result.get("suppressed"))
        response["send_result"] = send_result
        response["send_reason"] = "sent" if response["sent"] else str(send_result.get("reason") or "suppressed")
        state = state if isinstance(state, dict) else {}
        state["report_delivery"] = {
            "last_sent_at": now.isoformat(),
            "last_signature": signature,
            "last_request_id": request_id or response.get("request_id"),
        }
        _write_json(SELF_IMPROVE_STATE_PATH, state)
    elif send_telegram:
        response["sent"] = False
        response["send_reason"] = "same_report_recently_sent" if recently_sent else "outside_hours"
    else:
        response["sent"] = False
        response["send_reason"] = "telegram_disabled"
    return response


def _self_improve_pipeline_stages() -> List[str]:
    return ["detect", "classify", "branch", "patch", "test", "diff", "approval", "deploy", "verify", "rollback"]


def _self_improve_pipeline_artifacts(pipeline_id: str) -> Dict[str, str]:
    artifact_dir = HERMES_HOME / "self_improve_artifacts" / pipeline_id
    return {
        "artifact_dir": str(artifact_dir),
        "patch_plan_path": str(artifact_dir / "patch_plan.md"),
        "test_summary_path": str(artifact_dir / "test_summary.json"),
        "diff_summary_path": str(artifact_dir / "diff_summary.md"),
        "rollback_notes_path": str(artifact_dir / "rollback_notes.md"),
    }


def _self_improve_pipeline_write_artifacts(pipeline: Dict[str, Any], *, stage_label: str) -> None:
    artifacts = dict(pipeline.get("artifacts") or {})
    artifact_dir = Path(str(artifacts.get("artifact_dir") or "")).expanduser()
    if not artifact_dir:
        return
    artifact_dir.mkdir(parents=True, exist_ok=True)
    def _write_artifact_text(path_value: str, content: str) -> None:
        path = Path(str(path_value or "")).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    proposal_ids = list(pipeline.get("proposal_ids") or [])
    verify_checklist = list(pipeline.get("verify_checklist") or [])
    rollback = dict(pipeline.get("rollback") or {})
    test_commands = list(pipeline.get("test_commands") or [])
    proposal_lines = [f"- `{proposal_id}`" for proposal_id in proposal_ids] or ["- `runtime_self_improve_report`"]
    stage_lines = [f"- `{stage}`" for stage in list(pipeline.get("stages") or [])]
    checklist_lines = [f"- `{item}`" for item in verify_checklist]
    rollback_lines = [f"- `{item}`" for item in list(rollback.get("preserve_artifacts") or [])]
    patch_plan = "\n".join(
        [
            "# Hermes Self-Improve Patch Plan",
            "",
            f"- Pipeline ID: `{pipeline.get('pipeline_id')}`",
            f"- Stage: `{stage_label}`",
            f"- Branch: `{pipeline.get('branch_name')}`",
            f"- Summary: {pipeline.get('summary')}",
            "",
            "## Proposal Scope",
            *proposal_lines,
            "",
            "## Planned Stages",
            *stage_lines,
            "",
            "## Verify Checklist",
            *checklist_lines,
            "",
        ]
    ).strip() + "\n"
    _write_artifact_text(str(artifacts.get("patch_plan_path") or ""), patch_plan)

    test_summary = {
        "pipeline_id": pipeline.get("pipeline_id"),
        "stage": stage_label,
        "test_commands": test_commands,
        "verify_checklist": verify_checklist,
        "status": "pending_execution" if stage_label == "proposed" else "approved_ready_for_patch",
    }
    _write_json(Path(str(artifacts.get("test_summary_path") or "")).expanduser(), test_summary)

    diff_summary = "\n".join(
        [
            "# Hermes Diff Summary",
            "",
            f"- Pipeline ID: `{pipeline.get('pipeline_id')}`",
            f"- Stage: `{stage_label}`",
            f"- Diff Strategy: {pipeline.get('diff_strategy')}",
            "",
            "No patch has been generated yet. This artifact reserves the review surface for the eventual branch diff.",
            "",
        ]
    ).strip() + "\n"
    _write_artifact_text(str(artifacts.get("diff_summary_path") or ""), diff_summary)

    rollback_notes = "\n".join(
        [
            "# Hermes Rollback Notes",
            "",
            f"- Pipeline ID: `{pipeline.get('pipeline_id')}`",
            f"- Stage: `{stage_label}`",
            f"- Strategy: {rollback.get('strategy') or 'unspecified' }",
            "",
            "## Preserve Artifacts",
            *rollback_lines,
            "",
        ]
    ).strip() + "\n"
    _write_artifact_text(str(artifacts.get("rollback_notes_path") or ""), rollback_notes)


def _build_self_improve_pipeline(proposals: List[Dict[str, Any]]) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    first = dict(proposals[0] if proposals else {})
    slug_source = str(first.get("kind") or first.get("task_title") or "general").lower().replace(" ", "-").replace("_", "-")
    slug = "".join(ch for ch in slug_source if ch.isalnum() or ch == "-").strip("-") or "general"
    pipeline_id = f"pipeline_{uuid.uuid4().hex[:10]}"
    return {
        "pipeline_id": pipeline_id,
        "created_at": now_iso,
        "proposal_ids": [item.get("proposal_id") for item in proposals if item.get("proposal_id")],
        "branch_name": f"hermes/self-improve/{slug}",
        "stages": _self_improve_pipeline_stages(),
        "current_stage": "detect",
        "next_stage": "classify",
        "test_commands": [
            "pytest tests/plugins/test_personal_ops_todoist.py -q",
            "$env:PYTHONPATH='C:\\Users\\Marketplace\\temp-personal-ops'; pytest tests -q",
        ],
        "diff_strategy": "review_generated_patch_and_runtime_trace_changes_before_apply",
        "rollback": {
            "strategy": "revert_branch_or_restore_previous_runtime_state",
            "preserve_artifacts": ["self_improve_report", "promptfoo_eval_cases", "runtime_traces"],
        },
        "artifacts": _self_improve_pipeline_artifacts(pipeline_id),
        "verify_checklist": ["run_targeted_tests", "run_full_plugin_suite", "inspect_diff_summary", "confirm_rollback_notes"],
        "status": "proposed",
        "summary": f"Reviewed GitOps self-improvement pipeline for {len(proposals)} proposal(s).",
    }


def _runtime_self_improve_pipeline(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode") or "status").strip().lower()
    state = _self_improve_pipelines_read()
    pipelines = list(state.get("pipelines") or [])
    if mode == "status":
        return {"success": True, "action": "self_improve_pipeline", "mode": mode, "pipeline_count": len(pipelines), "pipelines": pipelines[-20:]}
    if mode == "propose":
        proposals = list((_self_improve_proposals_read().get("proposals") or []))
        if not proposals:
            proposals = [{
                "proposal_id": "runtime_self_improve_report",
                "kind": "maintenance_review",
                "task_title": "Hermes self-improvement maintenance",
            }]
        pipeline = _build_self_improve_pipeline(proposals)
        _self_improve_pipeline_write_artifacts(pipeline, stage_label="proposed")
        pipelines.append(pipeline)
        state["pipelines"] = pipelines[-100:]
        _self_improve_pipelines_write(state)
        response = json.loads(_create_approval(
            tool_name="personal_runtime",
            action="self_improve_pipeline_apply",
            summary="Approve Hermes self-improvement GitOps pipeline",
            reason="Code and systems improvements should move through a visible reviewed pipeline instead of silent mutation.",
            benefit="You get an explicit branch/test/diff/rollback plan before Hermes advances the pipeline.",
            payload={"action": "self_improve_pipeline_apply", "pipeline": pipeline},
        ))
        response["pipeline"] = pipeline
        return response
    raise ValueError(f"Unsupported self_improve_pipeline mode: {mode}")


def _runtime_external_systems_status(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    calendar_status = _runtime_calendar_status({})
    calendar_provider = _calendar_provider()
    systems = {
        "calendar": {
            "configured": bool(calendar_provider),
            "role": "timing_and_availability_signal",
            "access_mode": "observe_or_draft",
            "risk_policy": "never_mutate_without_explicit_approval",
            "provider": calendar_status.get("provider"),
            "status_mode": calendar_status.get("mode"),
        },
        "home_assistant": {
            "configured": bool(_env_first("HERMES_HOME_ASSISTANT_URL", "HOME_ASSISTANT_URL")),
            "role": "household_context_signal",
            "access_mode": "observe_first",
            "risk_policy": "no_device_control_without_explicit_approval",
        },
        "paperless": {
            "configured": bool(_env_first("HERMES_PAPERLESS_URL", "PAPERLESS_URL")),
            "role": "document_lookup_and_admin_grounding",
            "access_mode": "read_only",
            "risk_policy": "never_delete_or_modify_documents_without_explicit_approval",
        },
        "actual_budget": {
            "configured": bool(_env_first("HERMES_ACTUAL_BUDGET_URL", "ACTUAL_BUDGET_URL")),
            "role": "budget_review_and_cost_visibility",
            "access_mode": "read_only",
            "risk_policy": "read_only_budget_review",
        },
    }
    return {"success": True, "action": "external_systems_status", "systems": systems}


def _runtime_hermes_capabilities_dossier(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    calendar = _runtime_calendar_status({})
    external = _runtime_external_systems_status({})
    profiles = _runtime_isolation_profile_plan({})
    jobs = _runtime_orchestration_job({"mode": "status", "limit": 10})
    return {
        "success": True,
        "action": "hermes_capabilities_dossier",
        "identity": {
            "mode": "bounded_personal_operations_kernel",
            "scope": "Hermes is a disciplined personal operator with memory, common sense, approvals, traces, and task-system operations.",
        },
        "calendar": {
            "provider": calendar.get("provider"),
            "status": "browser_handoff_ready" if calendar.get("configured") else "unconfigured",
            "approval_policy": calendar.get("approval_policy"),
            "mode": calendar.get("mode"),
        },
        "external_systems": external.get("systems"),
        "orchestration_governance": {
            "profiles": profiles.get("profiles"),
            "job_board": {
                "status": "live" if jobs.get("success") else "degraded",
                "job_count": jobs.get("job_count"),
                "latest_jobs": jobs.get("jobs"),
            },
            "controller_worker_rule": "Hermes may plan/review/approve-request; workers produce artifacts only and never deploy or approve themselves.",
        },
        "live_layers": [
            "core_state_machine",
            "adaptive_nudge_intelligence",
            "memory_and_todoist_operations",
            "observability_and_evals",
            "gitops_self_improve_pipeline",
            "controller_worker_job_board",
        ],
        "boundaries": [
            "approval_gated",
            "approval_gated_external_writes",
            "browser_backed_calendar_handoff",
            "read_only_budget_review",
            "no_silent_destructive_actions",
            "intention_gate_before_worker_dispatch",
        ],
    }


def _runtime_hermes_system_audit(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    snapshot = _operating_snapshot({})
    presence = _runtime_presence_status()
    trace_status = _runtime_trace_status({})
    calendar = _runtime_calendar_status({})
    external = _runtime_external_systems_status({})
    memory = _runtime_memory_console({"mode": "list"})
    rules = _runtime_todoist_rule_store({"mode": "status"})
    pipeline = _runtime_self_improve_pipeline({"mode": "status"})
    eval_export = _runtime_eval_suite_export({})
    snapshot_payload = dict(snapshot.get("snapshot") or {})
    presence_snapshot = dict(snapshot_payload.get("presence") or {})
    trace_runtime_ok = bool(trace_status.get("success"))
    trace_langfuse_ok = bool((trace_status.get("langfuse") or {}).get("configured"))
    surfaces = {
        "core_state_machine": {
            "status": "live" if snapshot.get("success") and snapshot_payload else "degraded",
            "details": {
                "has_presence_slice": bool(presence_snapshot),
                "has_adaptive_nudge_slice": bool(snapshot_payload.get("adaptive_nudge")),
                "event_count": int((snapshot.get("normalized_events") or {}).get("count") or 0),
            },
        },
        "presence_model": {
            "status": "live" if presence.get("configured") and str((presence.get("last_signal") or {}).get("source") or "") == "activitywatch-forwarder" else "degraded",
            "details": {
                "source": (presence.get("last_signal") or {}).get("source"),
                "confidence": presence.get("confidence"),
                "activitywatch_forwarder_primary": str((presence.get("last_signal") or {}).get("source") or "") == "activitywatch-forwarder",
                "server_local_activitywatch_configured": bool((presence.get("activitywatch") or {}).get("configured")),
            },
        },
        "adaptive_nudge": {
            "status": "live" if snapshot_payload.get("adaptive_nudge") else "degraded",
            "details": dict(snapshot_payload.get("adaptive_nudge") or {}),
        },
        "memory_console": {
            "status": "live" if memory.get("success") else "degraded",
            "details": {"memory_count": memory.get("memory_count"), "mode": memory.get("mode")},
        },
        "todoist_rule_store": {
            "status": "live" if rules.get("success") else "degraded",
            "details": {"rule_count": rules.get("rule_count"), "task_metadata_count": rules.get("task_metadata_count")},
        },
        "tracing": {
            "status": "live" if (trace_runtime_ok and trace_langfuse_ok) else "local_live" if trace_runtime_ok else "degraded",
            "details": {
                "trace_count": trace_status.get("trace_count"),
                "langfuse_configured_now": trace_langfuse_ok,
            },
        },
        "evals": {
            "status": "live" if eval_export.get("success") else "degraded",
            "details": {"case_count": eval_export.get("case_count"), "config_path": eval_export.get("config_path")},
        },
        "self_improve_pipeline": {
            "status": "live" if pipeline.get("success") else "degraded",
            "details": {"pipeline_count": pipeline.get("pipeline_count")},
        },
        "calendar": {
            "status": "live" if calendar.get("configured") and calendar.get("provider") == "browser_google_calendar" else "degraded",
            "details": {
                "provider": calendar.get("provider"),
                "mode": calendar.get("mode"),
                "approval_policy": calendar.get("approval_policy"),
            },
        },
        "home_assistant": {
            "status": "scaffolded" if (external.get("systems") or {}).get("home_assistant", {}).get("configured") else "unconfigured",
            "details": (external.get("systems") or {}).get("home_assistant", {}),
        },
        "paperless": {
            "status": "scaffolded" if (external.get("systems") or {}).get("paperless", {}).get("configured") else "unconfigured",
            "details": (external.get("systems") or {}).get("paperless", {}),
        },
        "actual_budget": {
            "status": "scaffolded" if (external.get("systems") or {}).get("actual_budget", {}).get("configured") else "unconfigured",
            "details": (external.get("systems") or {}).get("actual_budget", {}),
        },
    }
    non_connected = []
    if not bool((trace_status.get("langfuse") or {}).get("configured")):
        non_connected.append("Langfuse is not currently configured in the live Hermes runtime; local trace receipts still work.")
    if not bool((presence.get("activitywatch") or {}).get("configured")):
        non_connected.append("Server-local ActivityWatch polling is not configured; forwarded ActivityWatch heartbeats are the real live presence source.")
    for name in ("home_assistant", "paperless", "actual_budget"):
        if surfaces[name]["status"] == "scaffolded":
            non_connected.append(f"{name} is scaffolded and policy-bounded, not a fully exercised end-to-end integration yet.")
    overall_status = "honest_with_gaps" if non_connected else "fully_live_for_audited_surfaces"
    return {
        "success": True,
        "action": "hermes_system_audit",
        "overall_status": overall_status,
        "surfaces": surfaces,
        "non_connected": non_connected,
    }


def _runtime_live_watch_status() -> Dict[str, Any]:
    payload = _read_json(LIVE_WATCH_STATE_PATH, {})
    if not isinstance(payload, dict) or not payload:
        return {
            "configured": False,
            "summary": "No live watch run recorded yet.",
            "ran_at": None,
            "focus_guard": None,
            "adaptive_companion": None,
            "status_message": None,
        }

    companion = payload.get("adaptive_companion") or {}
    focus_guard = payload.get("focus_guard") or {}
    if companion.get("sent"):
        summary = "Live watch is active and the last cycle sent a Telegram message."
    else:
        reason = str(companion.get("reason") or "unknown").strip() or "unknown"
        summary = f"Live watch is active. Last cycle stayed quiet because: {reason}."
    return {
        "configured": True,
        "summary": summary,
        "ran_at": payload.get("ran_at"),
        "filter": payload.get("filter"),
        "focus_guard": focus_guard,
        "adaptive_companion": companion,
        "operator_brief": payload.get("operator_brief"),
        "operator_brief_error": payload.get("operator_brief_error"),
        "agi_operator_cycle": payload.get("agi_operator_cycle"),
        "agi_operator_cycle_error": payload.get("agi_operator_cycle_error"),
        "status_message": payload.get("status_message"),
    }


def _runtime_live_watch_status_message(payload: Dict[str, Any]) -> str:
    focus_guard = dict(payload.get("focus_guard") or {})
    companion = dict(payload.get("adaptive_companion") or {})
    companion_state = dict(companion.get("state") or {})
    lenses = dict(companion_state.get("insight_lenses") or {})
    surface = dict(payload.get("surface_policy") or lenses.get("surface_policy") or {})
    if not surface:
        fallback_state = dict(companion_state)
        fallback_state["insight_lenses"] = lenses
        surface = _adaptive_companion_surface_policy(state=fallback_state, focus_state=focus_guard)
    target = str(((focus_guard.get("most_important_task") or {}).get("content") or "")).strip() or "None"
    suspicious_labels = [
        str(((item.get("task") or {}).get("content") or "")).strip()
        for item in list(focus_guard.get("suspicious_tasks") or [])[:3]
        if str(((item.get("task") or {}).get("content") or "")).strip()
    ]
    reason = str(companion.get("reason") or "").strip()
    summary = "sent a Telegram nudge" if companion.get("sent") else f"stayed quiet ({reason or 'unknown'})"
    ran_at = str(payload.get("ran_at") or "").strip() or "unknown"
    filter_text = str(payload.get("filter") or "all tasks").strip()
    lines = ["Hermes Live Watch", f"Last run: {ran_at}", f"Top task: {target}", f"Last decision: {summary}"]
    if suspicious_labels:
        lines.insert(3, f"Flagged side task: {suspicious_labels[0]}")
    if not surface.get("compact_status"):
        lines.insert(2, f"Filter: {filter_text}")
        lines.insert(3, f"Focus status: {focus_guard.get('status', 'unknown')}")
    threshold = dict(lenses.get("threshold_detection") or {})
    if threshold:
        lines.append(f"Threshold: {threshold.get('level', 'low')} - {threshold.get('signal', '')}".strip())
    recovery = dict(lenses.get("recovery_intelligence") or {})
    if recovery:
        lines.append(f"Recovery: {recovery.get('mode', 'pressure')} - {recovery.get('suggestion', '')}".strip())
    respect = dict(lenses.get("respect_engine") or {})
    if respect and respect.get("note") and not surface.get("compact_status"):
        lines.append(f"Respect: {respect.get('note')}")
    silent = list(lenses.get("silent_interventions") or [])
    if silent:
        lines.append(f"Silent move: {silent[0]}")
    if surface.get("mode"):
        lines.append(f"Surface: {surface.get('mode')}")
    return "\n".join(line for line in lines if line).strip()


def _runtime_live_watch_update_status_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _env("LIVE_WATCH_STATUS_MESSAGE").strip().lower() in {"0", "false", "no", "off"}:
        return None

    state = _read_json(LIVE_WATCH_STATE_PATH, {})
    prior_status = dict((state or {}).get("status_message") or {})
    _, default_chat_id = _focus_guard_telegram_config()
    target_chat_id = str(prior_status.get("chat_id") or default_chat_id).strip()
    text = _runtime_live_watch_status_message(payload)
    message_id = prior_status.get("message_id")

    if message_id:
        response = _focus_guard_telegram_post(
            "editMessageText",
            {
                "chat_id": target_chat_id,
                "message_id": int(message_id),
                "text": text,
            },
        )
        result = response.get("result")
        resolved_message_id = int(message_id)
        if isinstance(result, dict):
            resolved_message_id = int(result.get("message_id") or resolved_message_id)
        return {"chat_id": target_chat_id, "message_id": resolved_message_id}

    response = _focus_guard_telegram_post(
        "sendMessage",
        {
            "chat_id": target_chat_id,
            "text": text,
            "disable_notification": True,
        },
    )
    result = response.get("result") or {}
    resolved_message_id = int(result.get("message_id") or 0)
    status_payload = {"chat_id": target_chat_id, "message_id": resolved_message_id}
    if resolved_message_id and _env("LIVE_WATCH_PIN_STATUS").strip().lower() in {"1", "true", "yes", "on"}:
        _focus_guard_telegram_post(
            "pinChatMessage",
            {
                "chat_id": target_chat_id,
                "message_id": resolved_message_id,
                "disable_notification": True,
            },
        )
    return status_payload


def _runtime_ensure_todoist_mcp() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if HERMES_CONFIG_PATH.exists():
        raw = HERMES_CONFIG_PATH.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw) if yaml is not None else _minimal_yaml_load(raw)
        loaded = loaded or {}
        if isinstance(loaded, dict):
            data = loaded
    servers = dict(data.get("mcp_servers") or {})
    todoist_mcp_main = (
        Path.home()
        / ".hermes"
        / "mcp"
        / "todoist"
        / "node_modules"
        / "@doist"
        / "todoist-mcp"
        / "dist"
        / "main.js"
    )
    expected = {
        "command": "node",
        "args": [str(todoist_mcp_main)],
        "env": {"TODOIST_API_KEY": "${TODOIST_API_KEY}"},
        "enabled": True,
    }
    prior = dict(servers.get("todoist") or {})
    changed = prior != {**prior, **expected}
    servers["todoist"] = {**prior, **expected}
    data["mcp_servers"] = servers
    if changed or not HERMES_CONFIG_PATH.exists():
        HERMES_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if yaml is not None:
            rendered = yaml.safe_dump(data, sort_keys=False)
        else:
            rendered = _minimal_yaml_dump(data)
        HERMES_CONFIG_PATH.write_text(rendered, encoding="utf-8")
    return {
        "success": True,
        "changed": changed,
        "mcp_servers": sorted(servers.keys()),
        "todoist": servers["todoist"],
        "summary": (
            "Todoist MCP is configured as a local official Doist MCP process using TODOIST_API_KEY. "
            "Hosted OAuth MCP is not used for unattended Hermes runtime."
        ),
    }


def _approval_response(request_id: str, summary: str, reason: str, benefit: str, action: str = "") -> str:
    return _tool_result(
        success=False,
        action=action or None,
        approval_required=True,
        request_id=request_id,
        summary=summary,
        reason=reason,
        benefit=benefit,
        message=(
            f"Approval required for {summary}. Reason: {reason} Benefit: {benefit}. "
            f"Approve with personal_security(action='approve_request', request_id='{request_id}') "
            f"or deny with personal_security(action='deny_request', request_id='{request_id}')."
        ),
    )


def _create_approval(*, tool_name: str, action: str, summary: str, reason: str, benefit: str, payload: Dict[str, Any]) -> str:
    approvals = _load_approvals()
    _prune_stale_self_improve_approvals(approvals)
    request_id = f"req_{uuid.uuid4().hex[:10]}"
    approvals["pending"][request_id] = {
        "request_id": request_id,
        "tool": tool_name,
        "action": action,
        "summary": summary,
        "reason": reason,
        "benefit": benefit,
        "payload": payload,
        "created_at": _now(),
    }
    approvals["history"].append(
        {
            "request_id": request_id,
            "event": "created",
            "tool": tool_name,
            "action": action,
            "summary": summary,
            "ts": _now(),
        }
    )
    _save_approvals(approvals)
    _append_event(
        "approval_created",
        {"request_id": request_id, "tool": tool_name, "action": action, "summary": summary},
    )
    return _approval_response(request_id, summary, reason, benefit, action)


def _pop_pending(request_id: str) -> Optional[Dict[str, Any]]:
    approvals = _load_approvals()
    if _prune_stale_self_improve_approvals(approvals):
        _save_approvals(approvals)
    pending = approvals.get("pending", {}).pop(request_id, None)
    if pending is not None:
        approvals["history"].append(
            {
                "request_id": request_id,
                "event": "removed",
                "tool": pending.get("tool"),
                "action": pending.get("action"),
                "summary": pending.get("summary"),
                "ts": _now(),
            }
        )
        _save_approvals(approvals)
    return pending
