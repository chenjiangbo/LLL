from backend.screening.hot_theme_filter_service import SCOPES, normalize_theme_text


def test_theme_normalization_handles_alias_punctuation_and_width():
    assert normalize_theme_text(" 低空经济·无人机 ") == normalize_theme_text("低空经济/无人机")
    assert normalize_theme_text("ＡＩ—算力") == normalize_theme_text("AI算力")


def test_hot_theme_scopes_do_not_include_decayed():
    assert "DECAYED" not in SCOPES["HISTORICAL"]
    assert SCOPES["HISTORICAL"] == {"CURRENT_ACTIVE", "RECENTLY_ACTIVE", "DORMANT_BUT_TRADED"}
