import pytest

from app.models.enums import PostStatus
from app.services.post_status import InvalidTransition, transition


def _post(status: str):
    """Minimal post-like object for testing transitions."""
    class FakePost:
        pass
    p = FakePost()
    p.status = status
    return p


# ── Legal transitions ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("from_s, to_s", [
    ("draft", "pending_approval"),
    ("pending_approval", "approved"),
    ("pending_approval", "rejected"),
    ("approved", "pending_approval"),
    ("approved", "scheduled"),
    ("approved", "rejected"),
    ("scheduled", "published"),
])
def test_legal_transitions(from_s, to_s):
    post = _post(from_s)
    result = transition(post, PostStatus(to_s))
    assert result.status == to_s


# ── Illegal transitions ────────────────────────────────────────────────────────

@pytest.mark.parametrize("from_s, to_s", [
    ("draft", "published"),
    ("draft", "scheduled"),
    ("draft", "rejected"),
    ("pending_approval", "published"),
    ("pending_approval", "scheduled"),
    ("approved", "draft"),
    ("published", "approved"),
    ("published", "scheduled"),
    ("rejected", "approved"),
])
def test_illegal_transitions(from_s, to_s):
    post = _post(from_s)
    with pytest.raises(InvalidTransition) as exc_info:
        transition(post, PostStatus(to_s))
    assert from_s in str(exc_info.value)
    assert to_s in str(exc_info.value)
