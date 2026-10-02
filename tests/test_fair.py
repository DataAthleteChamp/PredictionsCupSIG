"""Tests for fair-value mapping and blending. All pure, no network."""
import pytest

from sigbot.fair import Crosswalk, FairValueEngine, poly_key, sig_key


# ------------------------------------------------------------ key mapping ---

def test_sig_key_senate_governor_house():
    assert sig_key("Will the Republican Party win the Texas Senate?") == ("SENATE", "TEXAS", "R")
    assert sig_key("Will the Democratic Party win the Iowa Governor?") == ("GOV", "IOWA", "D")
    assert sig_key("Will the Republican Party win the PA-07 House race?") == ("HOUSE", "PA-07", "R")


def test_sig_key_chamber_control():
    assert sig_key("Will the Republican Party win the U.S. Senate?") == ("CONTROL", "SENATE", "R")
    assert sig_key("Will the Democratic Party win the U.S. House?") == ("CONTROL", "HOUSE", "D")


def test_sig_key_independent_party():
    assert sig_key("Will the Independent Party win the Nebraska Senate?") == ("SENATE", "NEBRASKA", "I")


def test_sig_key_rejects_unknown():
    assert sig_key("Something else entirely") is None
    assert sig_key("") is None
    assert sig_key(None) is None


def test_poly_key_matches_the_three_question_shapes():
    assert poly_key("Will the Democrats win the Texas Senate race in 2026?") == ("SENATE", "TEXAS", "D")
    assert poly_key("Will the Republicans win the Wisconsin governor race in 2026?") == ("GOV", "WISCONSIN", "R")
    assert poly_key("Will the Republican Party win the PA-07 House seat?") == ("HOUSE", "PA-07", "R")
    assert poly_key("Will the Democratic Party control the Senate after the 2026 Midterm elections?") == ("CONTROL", "SENATE", "D")


def test_poly_and_sig_keys_agree_so_the_crosswalk_joins():
    """The whole crosswalk depends on these two producing identical keys."""
    pairs = [
        ("Will the Republican Party win the Texas Senate?",
         "Will the Republicans win the Texas Senate race in 2026?"),
        ("Will the Democratic Party win the PA-07 House race?",
         "Will the Democratic Party win the PA-07 House seat?"),
        ("Will the Republican Party win the U.S. Senate?",
         "Will the Republican Party control the Senate after the 2026 Midterm elections?"),
    ]
    for ours, theirs in pairs:
        assert sig_key(ours) == poly_key(theirs), ours


def test_poly_key_normalises_district_zero_padding():
    assert poly_key("Will the Democratic Party win the FL-7 House seat?") == ("HOUSE", "FL-07", "D")


def test_poly_key_rejects_margin_markets():
    assert poly_key("Will the Democratic candidate win the 2026 TX-28 election by 5%-10%?") is None


# ------------------------------------------------------------- crosswalk ----

def xw():
    return Crosswalk(
        token_by_exchange={"1": "tokA", "2": "tokB"},
        key_by_exchange={"1": ("SENATE", "TEXAS", "R"),
                         "2": ("SENATE", "TEXAS", "D"),
                         "3": ("SENATE", "MAINE", "R")},
    )


def test_crosswalk_roundtrips(tmp_path):
    p = tmp_path / "xw.json"
    xw().save(str(p))
    back = Crosswalk.load(str(p))
    assert back.token_by_exchange == xw().token_by_exchange
    assert back.key_by_exchange["1"] == ("SENATE", "TEXAS", "R")


def test_crosswalk_len():
    assert len(xw()) == 2


# ------------------------------------------------------------- engine ------

def test_external_maps_tokens_onto_exchanges():
    eng = FairValueEngine(xw())
    assert eng.external({"tokA": 0.6, "tokB": 0.4}) == {"1": 0.6, "2": 0.4}


def test_external_ignores_missing_tokens():
    assert FairValueEngine(xw()).external({"tokA": 0.6}) == {"1": 0.6}


def test_devig_normalises_within_a_race():
    """R and D are separate books here, so raw prices carry an overround."""
    out = FairValueEngine(xw()).devig_by_race({"1": 0.60, "2": 0.45})
    assert out["1"] + out["2"] == pytest.approx(1.0)
    assert out["1"] > out["2"]


def test_devig_leaves_separate_races_independent():
    out = FairValueEngine(xw()).devig_by_race({"1": 0.6, "2": 0.45, "3": 0.9})
    assert out["1"] + out["2"] == pytest.approx(1.0)
    # Alone in its race: must pass through UNCHANGED. Normalising a lone
    # probability to 1.0 would fabricate certainty and drive a bad trade.
    assert out["3"] == pytest.approx(0.9)


def test_devig_never_fabricates_certainty_from_a_lone_market():
    """Groups lose members routinely (one-sided books, dropped CLOB calls)."""
    eng = FairValueEngine(xw())
    for anchor in (0.05, 0.20, 0.50, 0.90):
        assert eng.devig_by_race({"3": anchor})["3"] == pytest.approx(anchor)


def test_internal_uses_microprice_not_mid():
    books = {"1": {"bestBid": 0.40, "bestAsk": 0.44,
                   "bidSize": 10_000, "askSize": 10}}
    assert FairValueEngine(xw()).internal(books)["1"] > 0.42


def test_internal_skips_incomplete_books():
    assert FairValueEngine(xw()).internal({"1": {"bestBid": None, "bestAsk": 0.5}}) == {}


def test_combine_blends_toward_the_anchor():
    eng = FairValueEngine(xw(), anchor_weight=1.0)
    books = {"1": {"bestBid": 0.50, "bestAsk": 0.52},
             "2": {"bestBid": 0.50, "bestAsk": 0.52}}
    out = eng.combine(books, {"tokA": 0.80, "tokB": 0.20})
    assert out["1"] == pytest.approx(0.80, abs=1e-6)


def test_combine_falls_back_to_internal_without_an_anchor():
    eng = FairValueEngine(Crosswalk(token_by_exchange={},
                                    key_by_exchange={"1": ("SENATE", "X", "R")}))
    out = eng.combine({"1": {"bestBid": 0.40, "bestAsk": 0.44}}, {})
    assert out["1"] == pytest.approx(0.42)     # microprice, not fabricated 1.0


def test_dropped_anchor_leg_does_not_corrupt_its_partner():
    """
    Issue found in review: if one leg's CLOB midpoint is missing, de-vigging the
    survivor alone returned 1.0 and the anchor had no effect on the output.
    """
    eng = FairValueEngine(xw(), anchor_weight=0.65)
    books = {"1": {"bestBid": 0.28, "bestAsk": 0.32},
             "2": {"bestBid": 0.68, "bestAsk": 0.72}}
    low = eng.combine(books, {"tokA": 0.20})    # tokB missing
    high = eng.combine(books, {"tokA": 0.90})
    assert low["1"] != high["1"], "anchor must still influence the result"
    assert low["1"] < high["1"]


def test_combine_respects_anchor_weight():
    eng = FairValueEngine(xw(), anchor_weight=0.5)
    books = {"1": {"bestBid": 0.50, "bestAsk": 0.50},
             "2": {"bestBid": 0.50, "bestAsk": 0.50}}
    out = eng.combine(books, {"tokA": 0.90, "tokB": 0.10})
    assert out["1"] == pytest.approx(0.5 * 0.90 + 0.5 * 0.50, abs=1e-6)


def test_anchor_weight_is_validated():
    with pytest.raises(ValueError):
        FairValueEngine(xw(), anchor_weight=1.5)
