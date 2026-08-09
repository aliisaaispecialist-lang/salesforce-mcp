"""Deciding that a write may happen, and asking the person who decides.

Two halves of one question. `gate` issues and verifies the signed ticket that
binds an approval to exact arguments; `elicit` is what actually puts the write
in front of a human before the connector is called. Neither is much use
without the other, which is why they are no longer in different places.
"""
