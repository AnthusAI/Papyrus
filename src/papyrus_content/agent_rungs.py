"""The ladder's rungs, in one place with no imports, so the operation table and the policy document can both name them."""

#: The ladder, lowest first. The position is the order: ``RUNGS.index(a) < RUNGS.index(b)`` means ``a`` allows less.
RUNGS = ("off", "observe", "propose", "draft", "prepare", "publish_soft", "publish_auto")

#: In the operation table, the value of ``agent_rung`` for an operation no rung allows an agent to do.
PERSON_ONLY = "person"
