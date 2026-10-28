# Chronicler Rule: lease_expired

**Insight:** The execution bot attempted to retry or re-acquire a task whose ownership lease had already expired, skipping the required reconciliation step (acknowledging the stale worker's partial state and formally releasing/transferring the old lease) before re-grabbing ownership.

**The Golden Rule:** Before retrying any task that returns a lease-expired or ownership-expired error, always run a reconciliation pass—inspect and clean up the prior worker's partial state, explicitly release or transfer the expired lease, and only then re-acquire the task; never blindly retry without this precondition.

**Source:** failure `9dd627750523e987` on task `badge-demo`.
