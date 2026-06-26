from app.models.enums import PostStatus
from app.models.post import Post

# The only place status changes happen. Any caller that bypasses this is a bug.
_ALLOWED: dict[PostStatus, list[PostStatus]] = {
    PostStatus.draft: [PostStatus.pending_approval],
    PostStatus.pending_approval: [PostStatus.approved, PostStatus.rejected],
    PostStatus.approved: [PostStatus.pending_approval, PostStatus.scheduled, PostStatus.rejected],
    PostStatus.scheduled: [PostStatus.published],
}


class InvalidTransition(Exception):
    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Cannot transition post from '{from_status}' to '{to_status}'"
        )


def transition(post: Post, to_status: PostStatus | str) -> Post:
    to = PostStatus(to_status) if isinstance(to_status, str) else to_status
    current = PostStatus(post.status)
    if to not in _ALLOWED.get(current, []):
        raise InvalidTransition(current.value, to.value)
    post.status = to.value
    return post
