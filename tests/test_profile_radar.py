"""The profile radar (placement vs now): drawn by the role's Core areas once three are assessed,
and by the track's areas until then. A placement interview asks five of the track's areas
whatever the role, so on its own it often reaches fewer than three Core areas; before this the
radar then disappeared ("Answer a few more questions")."""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
JS = (APP / "static" / "ui" / "profile.js").read_text(encoding="utf-8")


def test_radar_falls_back_to_the_track_areas():
    assert "let shown = draw(track.areas, byRole ? role.area_topics : null), fellBack = false;" in JS
    assert "if (byRole && !shown.chart.svg) {" in JS and "const wide = draw(found.areas, null);" in JS
    assert "Shown by the track's areas until three of the ${role.name} Core areas are assessed." in JS


def test_placement_on_the_role_areas_comes_from_the_placement_answers_topics():
    assert "const mine = profile.answers.filter((a) => a.t === current && a.p);" in JS
    assert "(a.a === area || (t && a.tp && t.has(a.tp)))" in JS


def test_the_table_follows_the_drawn_areas_and_the_radar_stays_off_the_landing():
    assert '$("area-rows").innerHTML = shown.rows.map(' in JS
    assert "radar" not in (APP / "templates" / "landing.html").read_text(encoding="utf-8")
    assert 'id="radar"' in (APP / "templates" / "profile.html").read_text(encoding="utf-8")
