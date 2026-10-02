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
    eng = FairValueEngine(xw())
    books = {"1": {"bestBid": 0.50, "bestAsk": 0.52},
             "2": {"bestBid": 0.50, "bestAsk": 0.52}}
    out = eng.combine(books, {"tokA": 0.80, "tokB": 0.20})
    assert out["1"] == pytest.approx(0.80, abs=1e-6)


def test_combine_emits_nothing_without_an_external_anchor():
    """
    This previously asserted that a missing anchor falls back to SIG's own
    microprice. That fallback is how the bot traded against a fair value
    derived from the very book it was quoting into: de-vigging moves the
    internal value off its own touch, manufacturing a relative-value signal
    from nothing. Replaying our tape with the feed emptied still produced 33
    orders. No anchor must mean no fair value, so strategies stand down.
    """
    eng = FairValueEngine(Crosswalk(token_by_exchange={},
                                    key_by_exchange={"1": ("SENATE", "X", "R")}))
    assert eng.combine({"1": {"bestBid": 0.40, "bestAsk": 0.44}}, {}) == {}


def test_dropped_anchor_leg_does_not_corrupt_its_partner():
    """
    Issue found in review: if one leg's CLOB midpoint is missing, de-vigging the
    survivor alone returned 1.0 and the anchor had no effect on the output.
    """
    eng = FairValueEngine(xw())
    books = {"1": {"bestBid": 0.28, "bestAsk": 0.32},
             "2": {"bestBid": 0.68, "bestAsk": 0.72}}
    low = eng.combine(books, {"tokA": 0.20})    # tokB missing
    high = eng.combine(books, {"tokA": 0.90})
    assert low["1"] != high["1"], "anchor must still influence the result"
    assert low["1"] < high["1"]


def test_fair_value_is_the_anchor_not_a_blend_with_our_own_book():
    """
    Blending with SIG's microprice is circular: the gap between the venues IS
    the trade. A 0.65/0.35 blend pulled a 0.025 Polymarket longshot up to
    0.0329 against a SIG book of 0.045/0.050, dropping the edge below the
    trading threshold -- destroying the favourite-longshot signal in exactly
    the tails where it was validated.
    """
    eng = FairValueEngine(xw())
    books = {"1": {"bestBid": 0.50, "bestAsk": 0.50},
             "2": {"bestBid": 0.50, "bestAsk": 0.50}}
    out = eng.combine(books, {"tokA": 0.90, "tokB": 0.10})
    assert out["1"] == pytest.approx(0.90, abs=1e-6)


def test_our_own_book_cannot_move_the_fair_value():
    """Own-quote feedback: adding depth to our side must not shift fair."""
    eng = FairValueEngine(xw())
    thin = {"1": {"bestBid": 0.40, "bestAsk": 0.44, "bidSize": 100,
                  "askSize": 100},
            "2": {"bestBid": 0.56, "bestAsk": 0.60, "bidSize": 100,
                  "askSize": 100}}
    stacked = {"1": {**thin["1"], "bidSize": 10_000},
               "2": thin["2"]}
    mids = {"tokA": 0.42, "tokB": 0.58}
    assert eng.combine(thin, mids) == eng.combine(stacked, mids)


def test_partial_outcome_set_is_not_normalised_to_one():
    """
    Nebraska/Montana Senate and Rhode Island Governor carry a real Independent,
    so P(R) + P(D) < 1. Forcing a partial set to sum to 1 redistributed the
    Independent's mass: raw R=0.70/D=0.05 came back as 0.933/0.067.
    """
    three_way = Crosswalk(
        token_by_exchange={"r": "tr", "d": "td"},
        key_by_exchange={"r": ("SENATE", "NEBRASKA", "R"),
                         "d": ("SENATE", "NEBRASKA", "D"),
                         "i": ("SENATE", "NEBRASKA", "I")})
    out = FairValueEngine(three_way).combine({}, {"tr": 0.70, "td": 0.05})
    assert out["r"] == pytest.approx(0.70)
    assert out["d"] == pytest.approx(0.05)


def test_complete_outcome_set_is_still_devigged():
    """A fully-mapped two-way race must still have its overround removed."""
    out = FairValueEngine(xw()).combine({}, {"tokA": 0.60, "tokB": 0.60})
    assert out["1"] + out["2"] == pytest.approx(1.0)
