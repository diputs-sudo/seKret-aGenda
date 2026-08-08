from scripts.sekret import _handle_command


def test_mode_command_changes_mode():
    result = _handle_command("/mode search", "draft")

    assert result.handled is True
    assert result.mode == "search"


def test_mode_command_accepts_no_ai_alias():
    result = _handle_command("/mode no-ai", "draft")

    assert result.handled is True
    assert result.mode == "search"


def test_mode_command_accepts_ai_alias():
    result = _handle_command("/mode ai", "search")

    assert result.handled is True
    assert result.mode == "draft"


def test_mode_command_rejects_unknown_mode():
    result = _handle_command("/mode chaos", "draft")

    assert result.handled is True
    assert result.mode is None


def test_non_command_is_not_handled():
    result = _handle_command("AI cautious", "draft")

    assert result.handled is False
