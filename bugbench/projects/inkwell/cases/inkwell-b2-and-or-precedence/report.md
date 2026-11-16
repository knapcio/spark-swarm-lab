# Admins lose the Edit link on published posts

Our post header template shows an Edit link to admins on every post, and to
authors on their drafts:

```python
from inkwell import Environment

header = Environment().from_string(
    "{% if user.is_admin or user.is_author and post.draft %}[Edit]{% endif %}{{ post.title }}")
header.render(user={"is_admin": True, "is_author": False}, post={"draft": False, "title": "News"})
header.render(user={"is_admin": False, "is_author": True}, post={"draft": True, "title": "Draft"})
```

Expected: `[Edit]News` and `[Edit]Draft`.
Actual: `News` (no link for the admin) and `[Edit]Draft`.

The author case works. If we add parentheses, as in
`user.is_admin or (user.is_author and post.draft)`, the admin gets the link
again. The README says `a or b and c` means `a or (b and c)`, as in Python,
so the parentheses should not be needed.
