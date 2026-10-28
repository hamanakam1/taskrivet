# Chronicler Rule: lease_expired

**Insight:** The bot attempted to retry or proceed with a lease-gated operation (context auto-check) after the ownership lease had already expired, failing to reconcile or release the stale worker's lease first, and the error went unhandled with no resolution recorded.

**The Golden Rule:** Before retrying any lease-gated operation, always verify lease validity; if the lease is expired, reconcile and release the previous worker's ownership claim before acquiring a new lease or proceeding—never blind-retry on a lease_expired condition.

**Source:** failure `9dd627750523e987` on task `CTX-AUTO-CHECK`.
