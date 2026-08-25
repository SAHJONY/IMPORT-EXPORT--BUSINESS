from voice_agent_api import _pathway_edges, _pathway_nodes, _safe_pathway_summary


def test_governed_pathway_graph_is_complete_and_loop_safe():
    nodes = _pathway_nodes()
    edges = _pathway_edges()
    node_ids = {node["id"] for node in nodes}
    node_names = {node["data"]["name"] for node in nodes}

    assert len(nodes) == 8
    assert len(node_ids) == len(nodes)
    assert len(edges) == 11
    assert sum(bool(node["data"].get("isStart")) for node in nodes) == 1
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in edges)
    assert all(node["type"] != "Transfer Call" for node in nodes)
    assert all(node["type"] != "Webhook" for node in nodes)
    assert "Fuel & Isotank Qualification" in node_names
    assert "Partner Enrollment" in node_names
    assert "Opt Out" in node_names


def test_pathway_prompts_do_not_enable_recording_or_live_transfer():
    prompts = " ".join(str(node["data"].get("prompt") or "") for node in _pathway_nodes()).lower()

    assert "call is not being recorded" in prompts
    assert "live transfer is unavailable" in prompts
    assert "+12164804413" not in prompts
    assert "+13465214387" not in prompts


def test_safe_summary_excludes_prompt_content():
    payload = {
        "name": "Version 6",
        "version_number": 6,
        "nodes": _pathway_nodes(),
        "edges": _pathway_edges(),
        "secret": "must-not-leak",
    }

    summary = _safe_pathway_summary(payload)

    assert summary["node_count"] == 8
    assert summary["edge_count"] == 11
    assert "secret" not in summary
    assert "prompt" not in summary
