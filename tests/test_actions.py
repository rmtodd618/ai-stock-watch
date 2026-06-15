from src.scoring.actions import Action, action_for_score

THRESHOLDS = {"add": 80, "starter": 65, "watch": 50}


def test_tier_boundaries():
    assert action_for_score(80, THRESHOLDS) is Action.ADD
    assert action_for_score(79.9, THRESHOLDS) is Action.STARTER
    assert action_for_score(65, THRESHOLDS) is Action.STARTER
    assert action_for_score(64.9, THRESHOLDS) is Action.WATCH
    assert action_for_score(50, THRESHOLDS) is Action.WATCH
    assert action_for_score(49.9, THRESHOLDS) is Action.AVOID
    assert action_for_score(0, THRESHOLDS) is Action.AVOID


def test_labels_are_research_framed():
    assert Action.ADD.label == "ADD SIGNAL"
    assert Action.STARTER.label == "STARTER SIGNAL"
    assert Action.WATCH.label == "WATCH"
    assert Action.AVOID.label == "AVOID FOR NOW"
