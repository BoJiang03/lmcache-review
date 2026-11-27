"""lmreview: AI pull-request review for any GitHub repository, with rules learned from its own reviewers,
as a library and a CLI (this checkout's own repository is LMCache/LMCache; others via `lmreview watch`).

    from lmreview import review_pr, to_markdown
    print(to_markdown(review_pr(5876)))

Agents run in a hard sandbox; see docs/agent_context.md. Nothing is posted to GitHub.
"""

from .config import Config
from .reviewer import review_pr, run_reviewer, to_markdown

__all__ = ["Config", "review_pr", "run_reviewer", "to_markdown"]
