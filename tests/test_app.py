"""Smoke tests for the Streamlit app, run headless with Streamlit's AppTest.

They read the committed results/ files, so run `python run.py` first if those are missing.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from sitefinder.score import FACTORS

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture()
def app():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def test_app_renders_without_error(app):
    assert not app.exception
    assert app.title[0].value.startswith("Where to open")
    assert len(app.sidebar.slider) == len(FACTORS)
    assert len(app.dataframe) == 1


def test_moving_a_slider_reorders_the_ranking(app):
    before = app.dataframe[0].value["area"].tolist()
    for slider in app.sidebar.slider:
        slider.set_value(0)
    app.sidebar.slider[0].set_value(10)  # only "less competition" counts
    app.run()
    assert not app.exception
    assert app.dataframe[0].value["area"].tolist() != before


def test_all_zero_weights_shows_a_warning(app):
    for slider in app.sidebar.slider:
        slider.set_value(0)
    app.run()
    assert not app.exception
    assert any("at least one factor" in w.value for w in app.warning)
    assert len(app.dataframe) == 0
