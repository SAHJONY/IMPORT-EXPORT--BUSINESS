from voice_agent_api import _realtime_session, _voice_instructions


def test_openai_realtime_is_the_only_conversational_voice_engine():
    session = _realtime_session()

    assert session["type"] == "realtime"
    assert session["model"]
    assert session["output_modalities"] == ["audio"]
    assert len(session["tools"]) == 1
    assert session["tools"][0]["type"] == "mcp"
    assert session["tools"][0]["allowed_tools"] == ["consult_sol"]
    assert "nodes" not in session
    assert "edges" not in session
    assert "pathway" not in session


def test_bland_is_restricted_to_telephony_transport():
    instructions = _voice_instructions().lower()

    assert "bland provides telephony/sip transport only" in instructions
    assert "bland conversational pathways" in instructions
    assert "not part of this architecture" in instructions


def test_voice_policy_disables_recording_and_unverified_commitments():
    instructions = _voice_instructions().lower()

    assert "do not intentionally record the call" in instructions
    assert "never bind sahjony" in instructions
    assert "never invent pricing" in instructions
    assert "+12164804413" not in instructions
    assert "+13465214387" not in instructions
