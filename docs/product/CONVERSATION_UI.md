# Conversation UI

Conversation is the primary Product Alpha surface. It presents one history region, one composer,
real execution state, and a discreet settings entry. There are no default fixture missions or open
context rail. The UI talks only to the host bridge; it never imports Kernel or Provider classes.

Recent history is supplied to the private application adapter, which invokes the canonical Kernel.
The host persists up to 100 turns locally. Demo turns remain labelled and are not sent to the PKB.

