"""Making a repeated call safe, in the two ways a call can repeat.

`ledger` remembers a key that already finished, so the same write asked for
twice is performed once. `journal` remembers a step inside a write that has
several, so a resumed attempt does not redo the part that already landed.

Both exist because a lost answer is indistinguishable from a lost request.
"""
