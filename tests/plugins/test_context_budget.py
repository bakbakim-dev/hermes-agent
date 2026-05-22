import json
from pathlib import Path

from plugins.personal_ops.context_budget import (
    audit_context_budget,
    classify_memory_destination,
    log_turn_context_contributors,
    prune_profile_recommendations,
)


def test_audit_context_budget_counts_prompt_memory_and_skills(tmp_path):
    hermes_home = tmp_path / ".hermes"
    repo = tmp_path / "repo"
    (hermes_home / "memories").mkdir(parents=True)
    (repo / "skills" / "big").mkdir(parents=True)
    (repo / "skills" / "small").mkdir(parents=True)
    (hermes_home / "memories" / "MEMORY.md").write_text("fact A\n§\nfact B", encoding="utf-8")
    (hermes_home / "memories" / "USER.md").write_text("pref A", encoding="utf-8")
    (repo / "skills" / "big" / "SKILL.md").write_text("x" * 16000, encoding="utf-8")
    (repo / "skills" / "small" / "SKILL.md").write_text("short", encoding="utf-8")

    report = audit_context_budget(hermes_home=hermes_home, repo_path=repo)

    assert report["success"] is True
    assert report["prompt_memory"]["memory_chars"] == len("fact A\n§\nfact B")
    assert report["prompt_memory"]["user_chars"] == len("pref A")
    assert report["skills"]["skill_count"] == 2
    assert report["skills"]["largest_skills"][0]["name"] == "big"
    assert report["recommendations"][0]["kind"] == "split_large_skill"


def test_prune_profile_recommendations_keep_personal_operator_stack():
    config = {
        "plugins": {
            "enabled": [
                "personal-ops",
                "memory",
                "todoist",
                "telegram",
                "slack",
                "discord",
                "clickup",
            ]
        }
    }

    report = prune_profile_recommendations(config_data=config)

    assert report["success"] is True
    assert "personal-ops" in report["keep_enabled"]
    assert "todoist" in report["keep_enabled"]
    assert "telegram" in report["keep_enabled"]
    assert "slack" in report["disable_candidates"]
    assert "discord" in report["disable_candidates"]
    assert report["approval_required"] is True


def test_memory_destination_keeps_behavior_rules_out_of_prompt_memory():
    result = classify_memory_destination(
        "Business contact tasks after hours should become draft or schedule tasks.",
        memory_type="common_sense_rule",
    )

    assert result["destination"] == "operator_rule_store"
    assert result["inject_into_prompt"] is False
    assert "structured" in result["reason"]


def test_audit_writes_jsonl_event_when_requested(tmp_path):
    hermes_home = tmp_path / ".hermes"
    repo = tmp_path / "repo"
    (hermes_home / "memories").mkdir(parents=True)
    repo.mkdir()

    report = audit_context_budget(hermes_home=hermes_home, repo_path=repo, write_event=True)

    event_path = hermes_home / "context_budget_events.jsonl"
    assert event_path.exists()
    record = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["type"] == "context_budget_audit"
    assert record["summary"]["total_estimated_tokens"] == report["total_estimated_tokens"]


def test_log_turn_context_contributors_records_per_turn_sources(tmp_path):
    hermes_home = tmp_path / ".hermes"
    (hermes_home / "memories").mkdir(parents=True)
    (hermes_home / "memories" / "MEMORY.md").write_text("memory fact", encoding="utf-8")
    (hermes_home / "memories" / "USER.md").write_text("user pref", encoding="utf-8")

    record = log_turn_context_contributors(
        hermes_home=hermes_home,
        platform="telegram",
        session_key="telegram:123",
        message_id="42",
        model="example-model",
        context_prompt="system note",
        history=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
        agent_result={
            "last_prompt_tokens": 321,
            "context_length": 1000,
            "tools": [{"name": "memory"}, {"name": "personal_runtime"}],
            "compression_exhausted": False,
        },
    )

    assert record["type"] == "turn_context_contributors"
    assert record["platform"] == "telegram"
    assert record["contributors"]["prompt_memory"]["memory_chars"] == len("memory fact")
    assert record["contributors"]["history"]["message_count"] == 2
    assert record["contributors"]["context_prompt"]["chars"] == len("system note")
    assert record["contributors"]["tools"]["schema_count"] == 2
    assert record["runtime"]["last_prompt_tokens"] == 321
    assert record["runtime"]["context_pct"] == 32.1
    event_path = hermes_home / "turn_context_events.jsonl"
    assert event_path.exists()
