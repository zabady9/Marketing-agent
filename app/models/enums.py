import enum


class PostStatus(str, enum.Enum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    scheduled = "scheduled"
    published = "published"
    rejected = "rejected"


class PlanStatus(str, enum.Enum):
    generating = "generating"
    ready = "ready"
    failed = "failed"


class AutonomyLevel(str, enum.Enum):
    supervised = "supervised"
    assisted = "assisted"
    autonomous = "autonomous"
