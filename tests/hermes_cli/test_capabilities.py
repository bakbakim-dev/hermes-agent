from __future__ import annotations


def test_capability_matrix_marks_default_enabled_and_credentialed_rows():
    from hermes_cli.capabilities import build_capability_matrix, render_capability_markdown

    rows = build_capability_matrix(
        plugin_infos=[
            {
                "key": "google_meet",
                "name": "google_meet",
                "kind": "standalone",
                "source": "bundled",
                "enabled": False,
                "error": "not enabled in config",
                "tools": 0,
                "requires_env": ["GOOGLE_CLIENT_ID"],
            },
            {
                "key": "image_gen/openai",
                "name": "openai",
                "kind": "backend",
                "source": "bundled",
                "enabled": True,
                "tools": 2,
                "requires_env": ["OPENAI_API_KEY"],
            },
        ],
        toolsets={
            "terminal": {"available": True, "tools": ["terminal_run"], "requirements": []},
            "spotify": {"available": False, "tools": ["spotify_play"], "requirements": ["SPOTIFY_CLIENT_ID"]},
        },
    )

    by_id = {row["id"]: row for row in rows}
    assert by_id["plugin:google_meet"]["enabled"] is False
    assert by_id["plugin:google_meet"]["default_status"] == "opt-in"
    assert by_id["plugin:image_gen/openai"]["default_status"] == "default-on"
    assert by_id["toolset:terminal"]["enabled"] is True
    assert by_id["toolset:spotify"]["requires_credentials"] is True

    markdown = render_capability_markdown(rows)
    assert "| Capability | Type | Implemented | Enabled | Default | Credentials | Notes |" in markdown
    assert "google_meet" in markdown
    assert "SPOTIFY_CLIENT_ID" in markdown
