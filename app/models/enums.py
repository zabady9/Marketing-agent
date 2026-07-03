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


class OnboardingStatus(str, enum.Enum):
    in_progress = "in_progress"
    pending_review = "pending_review"   # set when user enters Step 7 review screen
    active = "active"


class DocumentStatus(str, enum.Enum):
    processing = "processing"
    indexed = "indexed"
    failed = "failed"
